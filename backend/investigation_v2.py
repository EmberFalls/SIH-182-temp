"""End-to-end v2 investigation orchestration with explicit live and recorded evidence boundaries."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable

from .adapters import LegacyExplorerAdapter
from .attribution_v2 import AttributionEngineV2
from .canonical import canonical_sha256
from .deposit_inference import DepositPatternResolver, persist_unreviewed_inference
from .domain import (
    AssetRef,
    CanonicalTransfer,
    CaseContextV2,
    DataMode,
    FlowSeed,
    HistoricalBalanceQuality,
    InvestigationCaseV2,
    InvestigationResultV2,
    InvestigationTraceRequestV2,
    RawEvidenceArtifact,
    SeedPrecision,
    SeedType,
    TerminalReason,
    TracePolicyV2,
    WalletAssetStateSnapshot,
)
from .entity_resolution import EntityResolver
from .flow_v2 import FundFlowEngineV2
from .models import Chain
from .results_v2 import InvestigationResultService
from .storage import Store


class ProviderSnapshotRepository:
    """A bounded, cached transfer snapshot backed by configured read-only providers."""

    def __init__(self, case: InvestigationCaseV2, store: Store, adapter_factory: Callable[[Chain], LegacyExplorerAdapter], limit: int) -> None:
        self.case = case
        self.store = store
        self.adapter_factory = adapter_factory
        self.limit = limit
        self._transfers: list[CanonicalTransfer] = []
        self._loaded_addresses: set[str] = set()
        self.warnings: list[str] = []

    @property
    def transfers(self) -> list[CanonicalTransfer]:
        return sorted(self._transfers, key=lambda item: (item.timestamp, item.id))

    async def load(self, address: str, asset: AssetRef) -> None:
        normalized = address.lower() if address.startswith("0x") else address
        if normalized in self._loaded_addresses:
            return
        self._loaded_addresses.add(normalized)
        result = await self.adapter_factory(asset.chain).outgoing_transfers(normalized, asset.symbol, self.limit)
        self.store.save_raw_evidence_artifact_v2(result.evidence)
        self.warnings.extend(result.warnings)
        known = {item.id for item in self._transfers}
        self._transfers.extend(item for item in result.transfers if item.id not in known and self._matches_asset(item, asset))

    async def outgoing_transfers(self, address: str, asset: AssetRef, start_time: datetime, end_time: datetime | None) -> list[CanonicalTransfer]:
        await self.load(address, asset)
        normalized = address.lower() if address.startswith("0x") else address
        return [
            item for item in self.transfers
            if item.source_address == normalized and item.timestamp >= start_time and (end_time is None or item.timestamp <= end_time)
        ]

    @staticmethod
    def _matches_asset(transfer: CanonicalTransfer, asset: AssetRef) -> bool:
        if transfer.asset.symbol != asset.symbol:
            return False
        if asset.contract_address and transfer.asset.contract_address:
            return transfer.asset.contract_address.lower() == asset.contract_address.lower()
        return True


class RecordedSnapshotRepository:
    """Immutable caller-supplied evidence replay. No network requests are made."""

    def __init__(self, transfers: list[CanonicalTransfer]) -> None:
        self._transfers = sorted(transfers, key=lambda item: (item.timestamp, item.id))
        self.warnings: list[str] = []

    @property
    def transfers(self) -> list[CanonicalTransfer]:
        return self._transfers

    async def outgoing_transfers(self, address: str, asset: AssetRef, start_time: datetime, end_time: datetime | None) -> list[CanonicalTransfer]:
        normalized = address.lower() if address.startswith("0x") else address
        return [
            item for item in self._transfers
            if item.source_address == normalized and item.timestamp >= start_time and (end_time is None or item.timestamp <= end_time)
            and ProviderSnapshotRepository._matches_asset(item, asset)
        ]


class UnknownHistoricalBalances:
    async def state_at(self, address: str, asset: AssetRef, timestamp: datetime) -> WalletAssetStateSnapshot:
        return WalletAssetStateSnapshot(
            address=address,
            asset=asset,
            historical_balance_quality=HistoricalBalanceQuality.UNKNOWN,
        )


class InvestigationRunnerV2:
    """Coordinates canonical collection, fund accounting, labels, inference, and immutable output."""

    def __init__(self, store: Store, adapter_factory: Callable[[Chain], LegacyExplorerAdapter]) -> None:
        self.store = store
        self.adapter_factory = adapter_factory

    async def run(self, case: InvestigationCaseV2, request: InvestigationTraceRequestV2) -> InvestigationResultV2:
        self._validate_mode(case.context, request)
        policy = request.trace_policy or case.trace_policy
        repository = await self._repository(case, request)
        seed = await self._seed(case, request, repository)
        resolver = EntityResolver(self.store)
        engine = FundFlowEngineV2(
            repository,
            UnknownHistoricalBalances(),
            terminal_classifier=lambda transfer: self._terminal_reason(resolver, transfer),
        )
        flow = await engine.trace(seed, policy)
        transfers = repository.transfers
        observed_at = max((item.timestamp for item in transfers), default=datetime.now(timezone.utc))
        inferences = self._infer_deposits(resolver, transfers, case.context.asset, observed_at)
        attribution = AttributionEngineV2(resolver).build(flow, case.context.chain.value, observed_at)
        limitations = self._limitations(case, repository, transfers, seed)
        return InvestigationResultService(self.store).create(
            case=case,
            flow=flow,
            attribution=attribution,
            transfers=transfers,
            deposit_inferences=inferences,
            limitations=limitations,
            generated_at=datetime.now(timezone.utc),
        )

    async def _repository(self, case: InvestigationCaseV2, request: InvestigationTraceRequestV2):
        if case.context.data_mode == DataMode.LIVE:
            repository = ProviderSnapshotRepository(case, self.store, self.adapter_factory, request.max_transfers_per_wallet)
            if case.context.seed_type == SeedType.WALLET_CONTEXT and case.context.seed_wallet:
                await repository.load(case.context.seed_wallet, case.context.asset)
            return repository
        for artifact in request.recorded_evidence:
            self.store.save_raw_evidence_artifact_v2(artifact)
        artifacts = {item.id for item in request.recorded_evidence}
        now = datetime.now(timezone.utc)
        for evidence_id in {item.raw_evidence_id for item in request.recorded_transfers} - artifacts:
            self.store.save_raw_evidence_artifact_v2(RawEvidenceArtifact(
                id=evidence_id,
                kind="provider_response",
                provider="recorded_import" if case.context.data_mode == DataMode.RECORDED_REAL else "synthetic_fixture",
                retrieved_at=now,
                content_hash_sha256=canonical_sha256([item for item in request.recorded_transfers if item.raw_evidence_id == evidence_id]),
                metadata={"generated_by": "v2_recorded_trace_import", "transfer_count": sum(1 for item in request.recorded_transfers if item.raw_evidence_id == evidence_id)},
            ))
        return RecordedSnapshotRepository(request.recorded_transfers)

    async def _seed(self, case: InvestigationCaseV2, request: InvestigationTraceRequestV2, repository) -> FlowSeed:
        context = case.context
        if context.seed_type == SeedType.WALLET_CONTEXT:
            return FlowSeed(
                id=f"SEED-{case.id}", address=context.seed_wallet or "", asset=context.asset,
                amount=context.disputed_amount, timestamp=context.incident_time,
                seed_type=SeedType.WALLET_CONTEXT,
            )
        if context.data_mode == DataMode.LIVE:
            raise ValueError("Live transaction-seeded tracing is unavailable until a transaction-by-hash provider adapter is configured. Use a wallet-context case or import recorded transaction evidence.")
        transfer = self._find_seed_transfer(context, request, repository.transfers)
        return FlowSeed(
            id=f"SEED-{case.id}", address=transfer.destination_address, asset=transfer.asset,
            amount=min(context.disputed_amount, transfer.normalized_amount), timestamp=transfer.timestamp,
            seed_type=SeedType.TRANSACTION, source_transaction_id=transfer.transaction_id,
            source_evidence_id=transfer.raw_evidence_id,
        )

    @staticmethod
    def _find_seed_transfer(context: CaseContextV2, request: InvestigationTraceRequestV2, transfers: list[CanonicalTransfer]) -> CanonicalTransfer:
        if request.seed_transfer_id:
            candidate = next((item for item in transfers if item.id == request.seed_transfer_id), None)
        else:
            tx_hash = (context.seed_tx_hash or "").lower()
            candidate = next((item for item in transfers if item.transaction_id.lower().endswith(tx_hash)), None)
        if candidate is None:
            raise ValueError("Recorded evidence does not contain the requested seed transaction. Supply seed_transfer_id or a canonical transfer whose transaction_id ends with seed_tx_hash.")
        if not ProviderSnapshotRepository._matches_asset(candidate, context.asset):
            raise ValueError("The selected seed transfer does not match the case asset.")
        return candidate

    def _infer_deposits(self, resolver: EntityResolver, transfers: list[CanonicalTransfer], asset: AssetRef, observed_at: datetime):
        addresses = sorted({item.destination_address for item in transfers})
        output = []
        inference_engine = DepositPatternResolver(resolver)
        for address in addresses:
            for inference in inference_engine.infer(address, asset, transfers, observed_at):
                persist_unreviewed_inference(self.store, inference)
                output.append(inference)
        return sorted({item.id: item for item in output}.values(), key=lambda item: item.id)

    @staticmethod
    def _terminal_reason(resolver: EntityResolver, transfer: CanonicalTransfer) -> TerminalReason | None:
        resolved = resolver.best(transfer.destination_address, transfer.chain.value, transfer.timestamp)
        if not resolved:
            return None
        entity_type = resolved.entity.entity_type.value
        if entity_type == "VASP":
            return TerminalReason.VERIFIED_VASP
        if entity_type == "MIXER":
            return TerminalReason.MIXER_BOUNDARY
        if entity_type == "BRIDGE":
            return TerminalReason.BRIDGE_UNRESOLVED
        if entity_type == "DEX":
            return TerminalReason.DEX_UNRESOLVED
        return None

    @staticmethod
    def _validate_mode(context: CaseContextV2, request: InvestigationTraceRequestV2) -> None:
        if context.data_mode == DataMode.LIVE and (request.recorded_transfers or request.recorded_evidence):
            raise ValueError("LIVE cases cannot mix caller-supplied transfers with provider evidence. Create a RECORDED_REAL case for replayed evidence.")
        if context.data_mode != DataMode.LIVE and not request.recorded_transfers:
            raise ValueError("RECORDED_REAL and SYNTHETIC cases require explicit canonical recorded_transfers.")

    @staticmethod
    def _limitations(case: InvestigationCaseV2, repository, transfers: list[CanonicalTransfer], seed: FlowSeed) -> list[str]:
        limitations = list(getattr(repository, "warnings", []))
        if case.context.data_mode == DataMode.LIVE:
            limitations.append("LIVE evidence is a bounded provider snapshot. Provider pagination, indexer coverage, and historical balances can limit tracing completeness.")
        if case.context.data_mode == DataMode.RECORDED_REAL:
            limitations.append("RECORDED_REAL output is limited to the supplied evidence package and its stated collection scope.")
        if case.context.data_mode == DataMode.SYNTHETIC:
            limitations.append("SYNTHETIC output is a demonstration artifact and cannot be used for operational routing.")
        limitations.append("Historical wallet balances are not reconstructed in this prototype; proportional allocations identify an evidence-bounded disputed-fund path, not ownership.")
        if not transfers:
            limitations.append("No matching transfers were available in the evidence snapshot.")
        if seed.seed_type == SeedType.WALLET_CONTEXT:
            limitations.append("Wallet-context seed amount is investigator supplied and therefore has APPROXIMATE seed precision.")
        return sorted(set(limitations))