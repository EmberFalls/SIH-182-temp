"""Clearly marked curated scenarios for offline SIH demonstration only."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .attribution import AttributionEngine
from .flow import FlowAllocator
from .models import CaseCreate, Chain, GraphNode, TraceRequest, TraceResult, TransferEvidence, VaspCandidate, VaspLabelCreate
from .risk import RiskEngine
from .storage import Store
from .tracing import TraceService


DEMO_FIR = "DEMO/SIH182/001"
ROOT = "0x1f2e3d4c5b6a79808192a3b4c5d6e7f8091a2b3c"
MULE_ONE = "0x2f3e4d5c6b7a8990a1b2c3d4e5f60718293a4b5c"
DEPOSIT = "0x3f4e5d6c7b8a9901a2b3c4d5e6f708192a3b4c5d"
BINANCE = "0x28c6c06298d514db089934071355e5743bf21d60"


class DemoScenarioService:
    """Produces a reproducible, intentionally synthetic multi-hop training trace."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.flow_allocator = FlowAllocator()
        self.attribution_engine = AttributionEngine()
        self.risk_engine = RiskEngine()

    def create_multihop_deposit_sweep(self) -> tuple[object, TraceResult]:
        case = next((item for item in self.store.list_cases() if item.fir_number == DEMO_FIR), None)
        if case is None:
            case = self.store.create_case(CaseCreate(
                title="SIMULATED DEMO — Multi-hop USDT deposit path",
                suspect_wallet=ROOT,
                chain=Chain.ETHEREUM,
                token_symbol="USDT",
                disputed_amount=Decimal("2500"),
                fir_number=DEMO_FIR,
                notes="Training-only curated scenario. Every synthetic transfer is visibly marked SIMULATED_DEMO; Binance label evidence remains public-source reviewed.",
            ))

        label = self.store.find_label(BINANCE, Chain.ETHEREUM.value)
        if label is None:
            label = self.store.add_label(VaspLabelCreate(
                address=BINANCE,
                chain=Chain.ETHEREUM,
                vasp_name="Binance",
                entity_kind="vasp",
                label_type="hot_wallet",
                confidence="verified",
                reviewer="Project public-source review",
                expires_at=datetime(2026, 12, 24, tzinfo=timezone.utc),
                source={
                    "url": f"https://etherscan.io/address/{BINANCE}",
                    "source_name": "Etherscan public address label: Binance 14",
                    "observed_at": "2026-09-24T00:00:00Z",
                },
            ))

        started = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)
        transfers = [
            self._transfer("01", ROOT, MULE_ONE, "2500", started),
            self._transfer("02", MULE_ONE, DEPOSIT, "2450", started + timedelta(minutes=11)),
            self._transfer("03", DEPOSIT, BINANCE, "2430", started + timedelta(minutes=19)),
        ]
        flow = self.flow_allocator.analyze(transfers, ROOT, Decimal("2500"))
        candidate = VaspCandidate(
            label_id=label.id,
            vasp_name=label.vasp_name,
            address=BINANCE,
            hop=3,
            label_type=label.label_type,
            evidence_grade=label.confidence,
            supporting_transaction=transfers[-1].transaction_hash,
        )
        candidates = self.attribution_engine.rank([candidate], flow)
        nodes = {
            ROOT: GraphNode(address=ROOT, chain=Chain.ETHEREUM, role="suspect", label="Simulated suspect wallet"),
            MULE_ONE: GraphNode(address=MULE_ONE, chain=Chain.ETHEREUM, role="observed", label="Observed intermediary wallet"),
            DEPOSIT: GraphNode(address=DEPOSIT, chain=Chain.ETHEREUM, role="observed", label="Observed deposit wallet"),
            BINANCE: GraphNode(address=BINANCE, chain=Chain.ETHEREUM, role="vasp", label=label.vasp_name, label_evidence=label),
        }
        provenance = [{
            "provider": "CURATED_SCENARIO",
            "address": ROOT,
            "status": "SIMULATED",
            "detail": "Training scenario generated from a fixed local fixture. It is not a live blockchain retrieval.",
            "retrieved_at": started.isoformat(),
        }]
        graph_nodes, graph = TraceService(self.store)._build_graph(case, nodes, transfers, flow, candidates, provenance, 3)
        run_id = f"DEMO-RUN-{uuid.uuid4().hex[:12].upper()}"
        manifest = {
            "run_id": run_id,
            "case_id": case.id,
            "data_mode": "SIMULATED_DEMO",
            "scenario": "multihop_deposit_sweep",
            "transfers": [item.model_dump(mode="json") for item in transfers],
            "candidates": [item.model_dump(mode="json") for item in candidates],
            "flow_analysis": flow.model_dump(mode="json"),
            "graph": graph.model_dump(mode="json"),
            "provenance": provenance,
        }
        manifest_sha256 = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        result = TraceResult(
            run_id=run_id,
            case_id=case.id,
            status="COMPLETED",
            nodes=graph_nodes,
            transfers=transfers,
            candidates=candidates,
            limitations=["SIMULATED_DEMO: This curated path is for training and demonstration. It cannot be used for operational attribution or SAHYOG routing."],
            provenance={"data_mode": "SIMULATED_DEMO", "events": provenance, "wallets_queried": 0, "max_hops": 3},
            manifest_sha256=manifest_sha256,
            manifest_payload=manifest,
            created_at=datetime.now(timezone.utc),
            flow_analysis=flow,
            risk_alerts=self.risk_engine.analyze(transfers, graph_nodes),
            graph=graph,
        )
        self.store.save_run(run_id, case.id, result.model_dump(mode="json"), result.created_at)
        return case, result

    @staticmethod
    def _transfer(suffix: str, source: str, destination: str, amount: str, timestamp: datetime) -> TransferEvidence:
        return TransferEvidence(
            transaction_hash=f"0x{'d' * 60}{suffix.zfill(4)}",
            source_address=source,
            destination_address=destination,
            token_symbol="USDT",
            token_contract="0xdac17f958d2ee523a2206206994597c13d831ec7",
            amount=Decimal(amount),
            timestamp=timestamp,
            block_number=99_000_000 + int(suffix),
            confirmed=True,
            provider="CURATED_SCENARIO (SIMULATED_DEMO)",
            retrieved_at=timestamp,
        )
