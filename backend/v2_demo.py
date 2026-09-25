"""Synthetic, explicitly marked v2 scenario for the evidence-first frontend."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from .attribution_v2 import AttributionEngineV2
from .deposit_inference import DepositPatternResolver, persist_unreviewed_inference
from .domain import (
    AssertionReviewState,
    AssertionType,
    AssetRef,
    CanonicalTransfer,
    CaseContextV2,
    CaseCreateV2,
    EntityAddressAssertionCreate,
    EntityCreate,
    EntityRole,
    EntityType,
    FlowSeed,
    HistoricalBalanceQuality,
    IntelligenceSourceCreate,
    IntelligenceSourceType,
    SeedType,
    TerminalReason,
    TracePolicyV2,
    TrustTier,
    WalletAssetStateSnapshot,
)
from .entity_resolution import EntityResolver
from .flow_v2 import FundFlowEngineV2
from .models import Chain
from .results_v2 import InvestigationResultService
from .storage import Store


DEMO_REF = "DEMO/V2/001"
ROOT = "0x1f2e3d4c5b6a79808192a3b4c5d6e7f8091a2b3c"
DEPOSIT = "0x3f4e5d6c7b8a9901a2b3c4d5e6f708192a3b4c5d"
COLLECTOR = "0x4f5e6d7c8b9a00112233445566778899aabbccdd"
SENDER_ONE = "0x5f6e7d8c9b0a112233445566778899aabbccddee"
SENDER_TWO = "0x6f7e8d9c0b1a2233445566778899aabbccddeeff"


class _Repository:
    def __init__(self, transfers: list[CanonicalTransfer]) -> None:
        self.transfers = transfers

    async def outgoing_transfers(self, address, asset, start_time, end_time):
        return [item for item in self.transfers if item.source_address == address.lower()]


class _Balances:
    async def state_at(self, address, asset, timestamp):
        return WalletAssetStateSnapshot(address=address, asset=asset, historical_balance_quality=HistoricalBalanceQuality.EXACT)


class V2DemoScenarioService:
    """Creates a reproducible synthetic fixture; it is never a live attribution."""

    def __init__(self, store: Store) -> None:
        self.store = store

    async def create_deposit_inference(self) -> dict:
        asset = AssetRef(chain=Chain.ETHEREUM, symbol="USDT", contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7", decimals=6, canonical_asset_id="USD_STABLE/USDT")
        case = next((item for item in self.store.list_investigation_cases_v2() if item.external_case_ref == DEMO_REF), None)
        if case is None:
            case = self.store.create_investigation_case_v2(CaseCreateV2(
                title="SYNTHETIC DEMO — Deposit sweep attribution",
                external_case_ref=DEMO_REF,
                trace_policy_id="v2-proportional-haircut",
                context=CaseContextV2(seed_type=SeedType.TRANSACTION, chain=Chain.ETHEREUM, asset=asset, disputed_amount=Decimal("5000"), incident_time=datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc), seed_tx_hash="0x" + "a" * 64, seed_wallet=ROOT, data_mode="SYNTHETIC"),
            ), "synthetic-demo")
        existing_results = self.store.list_investigation_results_v2(case.id)
        if existing_results:
            snapshot = existing_results[0]
            return {
                "case": case, "data_mode": "SYNTHETIC", "result": snapshot,
                "flow": snapshot.flow, "attribution": snapshot.attribution,
                "deposit_inferences": snapshot.deposit_inferences, "inferred_assertion_ids": [],
                "transfers": snapshot.transfers, "limitations": snapshot.limitations,
            }
        entity = self.store.find_entity("Synthetic Demo Exchange", EntityType.VASP) or self.store.create_entity(EntityCreate(canonical_name="Synthetic Demo Exchange", entity_type=EntityType.VASP, metadata={"scenario": DEMO_REF}))
        assertions = [item for item in self.store.list_entity_address_assertions(COLLECTOR, Chain.ETHEREUM.value) if item.entity_id == entity.id]
        if not assertions:
            source = self.store.create_intelligence_source(IntelligenceSourceCreate(name="Synthetic fixture reviewed collector", source_type=IntelligenceSourceType.INTERNAL_REVIEW, trust_tier=TrustTier.A, retrieved_at=datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc), notes="Synthetic demo fixture only; not a real-world VASP assertion."))
            self.store.create_entity_address_assertion(EntityAddressAssertionCreate(entity_id=entity.id, address=COLLECTOR, chain=Chain.ETHEREUM, role=EntityRole.VASP_COLLECTOR, assertion_type=AssertionType.VERIFIED, source_id=source.id, review_state=AssertionReviewState.REVIEWED, last_verified_at=datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc), stale_after=datetime(2026, 12, 31, tzinfo=timezone.utc), notes="Synthetic demo fixture only."))
        started = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)
        transfers = [
            self._transfer("IN-1", SENDER_ONE, DEPOSIT, "2500", started + timedelta(minutes=1), asset),
            self._transfer("ROOT-1", ROOT, DEPOSIT, "2500", started + timedelta(minutes=1), asset),
            self._transfer("OUT-1", DEPOSIT, COLLECTOR, "2450", started + timedelta(minutes=10), asset),
            self._transfer("IN-2", SENDER_TWO, DEPOSIT, "2500", started + timedelta(minutes=20), asset),
            self._transfer("ROOT-2", ROOT, DEPOSIT, "2500", started + timedelta(minutes=20), asset),
            self._transfer("OUT-2", DEPOSIT, COLLECTOR, "2450", started + timedelta(minutes=28), asset),
        ]
        seed = FlowSeed(id="SEED-SYNTHETIC-V2", address=ROOT, asset=asset, amount=Decimal("5000"), timestamp=started, seed_type=SeedType.TRANSACTION, source_transaction_id="TX-SYNTHETIC-SEED", source_evidence_id="EVID-SYNTHETIC-SEED")
        resolver = EntityResolver(self.store)
        engine = FundFlowEngineV2(_Repository(transfers), _Balances(), terminal_classifier=lambda item: TerminalReason.VERIFIED_VASP if item.destination_address == COLLECTOR else None)
        flow = await engine.trace(seed, TracePolicyV2(max_hops=4))
        inference = DepositPatternResolver(resolver).infer(DEPOSIT, asset, transfers, started + timedelta(minutes=30))
        inferred_assertions = [persist_unreviewed_inference(self.store, item) for item in inference]
        attribution = AttributionEngineV2(resolver).build(flow, Chain.ETHEREUM.value, started + timedelta(minutes=30))
        limitations = ["SYNTHETIC DEMO: all transfers, wallet addresses, and entity evidence in this scenario are generated locally. It is not live blockchain intelligence and cannot be used for operational routing."]
        snapshot = InvestigationResultService(self.store).create(case, flow, attribution, transfers, inference, limitations, started + timedelta(minutes=30))
        return {
            "case": case,
            "data_mode": "SYNTHETIC",
            "result": snapshot,
            "flow": flow,
            "attribution": attribution,
            "deposit_inferences": inference,
            "inferred_assertion_ids": [item.id for item in inferred_assertions],
            "transfers": transfers,
            "limitations": limitations,
        }

    @staticmethod
    def _transfer(identifier: str, source: str, destination: str, amount: str, timestamp: datetime, asset: AssetRef) -> CanonicalTransfer:
        return CanonicalTransfer(id=identifier, transaction_id=f"TX-{identifier}", chain=Chain.ETHEREUM, source_address=source, destination_address=destination, asset=asset, raw_amount=Decimal(amount), normalized_amount=Decimal(amount), timestamp=timestamp, raw_evidence_id="EVID-SYNTHETIC")