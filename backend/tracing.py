import hashlib
import json
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .config import settings
from .attribution import AttributionEngine
from .cross_case import CrossCaseEngine
from .cross_chain import CrossChainAnalyzer
from .ethereum import EtherscanClient, EvmScanClient
from .chains import UnavailableChainClient
from .flow import FlowAllocator
from .models import CaseSummary, Chain, GraphEdge, GraphNode, TraceFrontier, TraceGraph, TracePath, TraceRequest, TraceResult, TransferEvidence, VaspCandidate
from .risk import RiskEngine
from .storage import Store
from .tron import TronGridClient


class TraceService:
    def __init__(self, store: Store, tron_client: TronGridClient | None = None, ethereum_client: EtherscanClient | None = None) -> None:
        self.store = store
        self.tron = tron_client or TronGridClient()
        self.ethereum = ethereum_client or EtherscanClient()
        self.bnb = EvmScanClient(chain_id=56, chain_name="BNB Chain")
        self.polygon = EvmScanClient(chain_id=137, chain_name="Polygon")
        self.bitcoin = UnavailableChainClient("Bitcoin")
        self.solana = UnavailableChainClient("Solana")
        self.flow_allocator = FlowAllocator()
        self.attribution_engine = AttributionEngine()
        self.risk_engine = RiskEngine()
        self.cross_case_engine = CrossCaseEngine(store)
        self.cross_chain_analyzer = CrossChainAnalyzer()

    async def trace_case(self, case: CaseSummary, request: TraceRequest) -> TraceResult:
        max_hops = min(request.max_hops, settings.max_hops)
        max_wallets = settings.max_wallets
        root_address = case.suspect_wallet.lower() if case.chain in {Chain.ETHEREUM, Chain.BNB_CHAIN, Chain.POLYGON} else case.suspect_wallet
        nodes: dict[str, GraphNode] = {
            root_address: GraphNode(address=root_address, chain=case.chain, role="suspect")
        }
        transfers: list[TransferEvidence] = []
        candidates: list[VaspCandidate] = []
        limitations: list[str] = []
        provenance_events: list[dict[str, Any]] = []
        frontier = [root_address]
        visited = {root_address}
        queried = 0

        for hop in range(1, max_hops + 1):
            next_frontier: list[str] = []
            for wallet in frontier:
                if queried >= max_wallets:
                    limitations.append(f"Wallet query limit ({max_wallets}) reached; the graph is partial.")
                    provenance_events.append({"provider": case.chain.value, "address": wallet, "status": "LIMIT_REACHED", "detail": f"Wallet query limit ({max_wallets}) reached."})
                    break
                queried += 1
                try:
                    found, source_event = await self._outgoing_transfers(case.chain, wallet, case.token_symbol, request.max_transfers_per_wallet)
                except Exception as exc:
                    if not transfers and queried == 1:
                        raise
                    limitations.append(f"Provider retrieval failed for {wallet}; returning confirmed partial evidence. Detail: {exc}")
                    provenance_events.append({"provider": case.chain.value, "address": wallet, "status": "FAILED", "detail": str(exc)})
                    continue
                provenance_events.append({**source_event, "address": wallet, "status": "CONFIRMED"})
                for transfer in found:
                    if not self._inside_case_window(transfer, case):
                        continue
                    transfers.append(transfer)
                    label = self.store.find_label(transfer.destination_address, case.chain.value)
                    if label and label.entity_kind == "vasp":
                        nodes[transfer.destination_address] = GraphNode(address=transfer.destination_address, chain=case.chain, role="vasp", label=label.vasp_name, label_evidence=label)
                        candidates.append(VaspCandidate(label_id=label.id, vasp_name=label.vasp_name, address=transfer.destination_address, hop=hop, label_type=label.label_type, evidence_grade=label.confidence, supporting_transaction=transfer.transaction_hash))
                    else:
                        role = label.entity_kind if label else "observed"
                        nodes.setdefault(transfer.destination_address, GraphNode(address=transfer.destination_address, chain=case.chain, role=role, label=label.vasp_name if label else None, label_evidence=label))
                        if transfer.destination_address not in visited and hop < max_hops:
                            visited.add(transfer.destination_address)
                            next_frontier.append(transfer.destination_address)
            frontier = next_frontier
            if not frontier:
                break

        flow_analysis = self.flow_allocator.analyze(transfers, root_address, case.disputed_amount)
        candidates = self.attribution_engine.rank(candidates, flow_analysis)
        risk_alerts = self.risk_engine.analyze(transfers, list(nodes.values()))
        bridge_observations = self.cross_chain_analyzer.inspect(case.chain, transfers, list(nodes.values()))
        cross_case_alerts = self.cross_case_engine.find_links(case.id, list(nodes.values()))
        graph_nodes, graph = self._build_graph(case, nodes, transfers, flow_analysis, candidates, provenance_events, max_hops)
        if not transfers:
            limitations.append("No confirmed outbound transfers matching the selected token and time window were retrieved.")
        if not candidates:
            limitations.append("No receiving address has a reviewed VASP label with attributed case funds in the local evidence registry. This is unresolved, not a negative ownership finding.")
        created_at = datetime.now(timezone.utc)
        run_id = f"RUN-{uuid.uuid4().hex[:16].upper()}"
        manifest = {
            "run_id": run_id, "case_id": case.id, "chain": case.chain.value, "data_mode": "LIVE_CONFIRMED",
            "transfers": [transfer.model_dump(mode="json") for transfer in transfers],
            "candidates": [candidate.model_dump(mode="json") for candidate in candidates], "flow_analysis": flow_analysis.model_dump(mode="json"), "provenance": provenance_events,
            "graph": graph.model_dump(mode="json"),
        }
        manifest_sha256 = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        status = "COMPLETED" if candidates else ("PARTIAL" if transfers else "UNRESOLVED")
        result = TraceResult(run_id=run_id, case_id=case.id, status=status, nodes=graph_nodes, transfers=transfers, candidates=candidates,
                             limitations=limitations, provenance={"data_mode": "LIVE_CONFIRMED", "events": provenance_events, "wallets_queried": queried, "max_hops": max_hops},
                             manifest_sha256=manifest_sha256, manifest_payload=manifest, created_at=created_at, flow_analysis=flow_analysis,
                             risk_alerts=risk_alerts, cross_case_alerts=cross_case_alerts, bridge_observations=bridge_observations, graph=graph)
        self.store.save_run(run_id, case.id, result.model_dump(mode="json"), created_at)
        return result

    async def _outgoing_transfers(self, chain: Chain, wallet: str, token_symbol: str, limit: int) -> tuple[list[TransferEvidence], dict]:
        if chain == Chain.TRON:
            return await self.tron.outgoing_trc20_transfers(wallet, token_symbol, limit)
        if chain == Chain.ETHEREUM:
            return await self.ethereum.outgoing_erc20_transfers(wallet, token_symbol, limit)
        if chain == Chain.BNB_CHAIN:
            return await self.bnb.outgoing_erc20_transfers(wallet, token_symbol, limit)
        if chain == Chain.POLYGON:
            return await self.polygon.outgoing_erc20_transfers(wallet, token_symbol, limit)
        if chain == Chain.BITCOIN:
            return await self.bitcoin.outgoing_transfers(wallet, token_symbol, limit)
        if chain == Chain.SOLANA:
            return await self.solana.outgoing_transfers(wallet, token_symbol, limit)
        raise ValueError(f"Unsupported chain: {chain.value}")

    @staticmethod
    def _inside_case_window(transfer: TransferEvidence, case: CaseSummary) -> bool:
        return (case.incident_start is None or transfer.timestamp >= case.incident_start) and (case.incident_end is None or transfer.timestamp <= case.incident_end)

    def _build_graph(
        self,
        case: CaseSummary,
        nodes: dict[str, GraphNode],
        transfers: list[TransferEvidence],
        flow_analysis: Any,
        candidates: list[VaspCandidate],
        provenance_events: list[dict[str, Any]],
        max_hops: int,
    ) -> tuple[list[GraphNode], TraceGraph]:
        """Create a presentation graph without changing the evidentiary trace record."""
        root = case.suspect_wallet.lower() if case.chain in {Chain.ETHEREUM, Chain.BNB_CHAIN, Chain.POLYGON} else case.suspect_wallet
        allocation_by_transfer = {
            (allocation.transaction_hash.lower(), allocation.source_address, allocation.destination_address): allocation.attributed_amount
            for allocation in flow_analysis.allocations
        }
        outgoing: dict[str, list[TransferEvidence]] = defaultdict(list)
        edge_ids: dict[tuple[str, str, str], str] = {}
        for transfer in transfers:
            outgoing[transfer.source_address].append(transfer)
            edge_ids[(transfer.transaction_hash.lower(), transfer.source_address, transfer.destination_address)] = self._edge_id(transfer)
        for address in outgoing:
            outgoing[address].sort(key=lambda item: (item.timestamp, item.transaction_hash))

        distances: dict[str, int] = {root: 0}
        parents: dict[str, tuple[str, str]] = {}
        queue: deque[str] = deque([root])
        while queue:
            source = queue.popleft()
            for transfer in outgoing.get(source, []):
                target = transfer.destination_address
                if target in distances:
                    continue
                distances[target] = distances[source] + 1
                parents[target] = (source, edge_ids[(transfer.transaction_hash.lower(), transfer.source_address, transfer.destination_address)])
                queue.append(target)

        case_inflow: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        case_outflow: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        graph_edges: list[GraphEdge] = []
        for transfer in sorted(transfers, key=lambda item: (item.timestamp, item.transaction_hash, item.destination_address)):
            amount = allocation_by_transfer.get((transfer.transaction_hash.lower(), transfer.source_address, transfer.destination_address), Decimal("0"))
            case_outflow[transfer.source_address] += amount
            case_inflow[transfer.destination_address] += amount
            destination_role = nodes.get(transfer.destination_address, GraphNode(address=transfer.destination_address, chain=case.chain, role="observed")).role
            relationship = "bridge_interaction" if destination_role == "bridge" else ("vasp_receipt" if destination_role == "vasp" else "transfer")
            graph_edges.append(GraphEdge(
                id=edge_ids[(transfer.transaction_hash.lower(), transfer.source_address, transfer.destination_address)],
                transaction_hash=transfer.transaction_hash,
                source=transfer.source_address,
                target=transfer.destination_address,
                hop=distances.get(transfer.source_address, 0) + 1,
                token_symbol=transfer.token_symbol,
                token_contract=transfer.token_contract,
                transfer_amount=transfer.amount,
                attributed_amount=amount,
                timestamp=transfer.timestamp,
                block_number=transfer.block_number,
                confirmed=transfer.confirmed,
                provider=transfer.provider,
                retrieved_at=transfer.retrieved_at,
                explorer_url=self._explorer_url(case.chain, transfer.transaction_hash, is_transaction=True),
                relationship=relationship,
            ))

        enriched_nodes = [
            node.model_copy(update={
                "hop": distances.get(address, 0),
                "case_inflow": case_inflow[address],
                "case_outflow": case_outflow[address],
                "explorer_url": self._explorer_url(case.chain, address),
            })
            for address, node in nodes.items()
        ]

        paths: list[TracePath] = []
        for candidate in candidates:
            supporting = next((transfer for transfer in transfers if transfer.transaction_hash.lower() == candidate.supporting_transaction.lower() and transfer.destination_address == candidate.address), None)
            if not supporting:
                continue
            node_addresses = [candidate.address]
            path_edge_ids = [edge_ids[(supporting.transaction_hash.lower(), supporting.source_address, supporting.destination_address)]]
            cursor = supporting.source_address
            while cursor != root:
                parent = parents.get(cursor)
                if not parent:
                    node_addresses = []
                    path_edge_ids = []
                    break
                cursor, parent_edge_id = parent
                node_addresses.append(cursor)
                path_edge_ids.append(parent_edge_id)
            if node_addresses:
                if node_addresses[-1] != root:
                    node_addresses.append(root)
                paths.append(TracePath(
                    candidate_label_id=candidate.label_id,
                    candidate_address=candidate.address,
                    hop=distances.get(candidate.address, candidate.hop),
                    node_addresses=list(reversed(node_addresses)),
                    edge_ids=list(reversed(path_edge_ids)),
                ))

        frontiers: list[TraceFrontier] = []
        seen_frontiers: set[tuple[str, str]] = set()

        def add_frontier(address: str, reason: str, detail: str) -> None:
            key = (address, reason)
            if key in seen_frontiers:
                return
            seen_frontiers.add(key)
            frontiers.append(TraceFrontier(address=address, hop=distances.get(address, 0), reason=reason, detail=detail, explorer_url=self._explorer_url(case.chain, address)))

        successful_queries = {event.get("address") for event in provenance_events if event.get("status") == "CONFIRMED"}
        for event in provenance_events:
            address = event.get("address")
            if not address:
                continue
            if event.get("status") == "FAILED":
                add_frontier(address, "provider_failure", event.get("detail", "Provider retrieval failed."))
            elif event.get("status") == "LIMIT_REACHED":
                add_frontier(address, "wallet_query_limit", event.get("detail", "Wallet query limit reached."))

        for node in enriched_nodes:
            if node.role == "vasp":
                continue
            if node.hop >= max_hops and node.address != root:
                add_frontier(node.address, "hop_limit", f"Configured trace depth of {max_hops} hops reached.")
            elif node.address in successful_queries and not outgoing.get(node.address):
                add_frontier(node.address, "no_matching_outbound_transfer", f"No confirmed outbound {case.token_symbol} transfer was retrieved within the selected scope.")

        return enriched_nodes, TraceGraph(root_address=root, edges=graph_edges, paths=paths, frontiers=frontiers)

    @staticmethod
    def _edge_id(transfer: TransferEvidence) -> str:
        digest = hashlib.sha256(f"{transfer.transaction_hash}:{transfer.source_address}:{transfer.destination_address}".encode()).hexdigest()[:18]
        return f"EDGE-{digest.upper()}"

    @staticmethod
    def _explorer_url(chain: Chain, value: str, is_transaction: bool = False) -> str | None:
        segment = "tx" if is_transaction else "address"
        if chain == Chain.ETHEREUM:
            return f"https://etherscan.io/{segment}/{value}"
        if chain == Chain.BNB_CHAIN:
            return f"https://bscscan.com/{segment}/{value}"
        if chain == Chain.POLYGON:
            return f"https://polygonscan.com/{segment}/{value}"
        if chain == Chain.TRON:
            return f"https://tronscan.org/#/{'transaction' if is_transaction else 'address'}/{value}"
        return None
