import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.attribution_v2 import AttributionEngineV2
from backend.domain import (
    AssertionReviewState,
    AssertionType,
    AssetRef,
    CanonicalTransfer,
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
from backend.entity_resolution import EntityResolver
from backend.flow_v2 import FundFlowEngineV2
from backend.models import Chain
from backend.storage import Store


NOW = datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc)
ASSET = AssetRef(chain=Chain.ETHEREUM, symbol="USDT", contract_address="0x" + "c" * 40, decimals=6)
ROOT = "0x" + "a" * 40
MID = "0x" + "b" * 40
NEAR = "0x" + "d" * 40
LARGE = "0x" + "e" * 40


def tx(identifier, source, destination, amount, minute):
    return CanonicalTransfer(
        id=identifier, transaction_id=f"TX-{identifier}", chain=Chain.ETHEREUM,
        source_address=source, destination_address=destination, asset=ASSET,
        raw_amount=Decimal(amount), normalized_amount=Decimal(amount),
        timestamp=NOW + timedelta(minutes=minute), raw_evidence_id="EVID-CHAIN",
    )


class Repository:
    def __init__(self, transfers):
        self.transfers = transfers

    async def outgoing_transfers(self, address, asset, start_time, end_time):
        return [item for item in self.transfers if item.source_address == address.lower()]


class Balances:
    async def state_at(self, address, asset, timestamp):
        return WalletAssetStateSnapshot(address=address, asset=asset, historical_balance_quality=HistoricalBalanceQuality.EXACT)


def build_flow(transfers, terminal_addresses):
    seed = FlowSeed(id="SEED-ATTR", address=ROOT, asset=ASSET, amount=Decimal("10000"), timestamp=NOW, seed_type=SeedType.TRANSACTION, source_transaction_id="TX-SEED")
    engine = FundFlowEngineV2(Repository(transfers), Balances(), terminal_classifier=lambda item: TerminalReason.VERIFIED_VASP if item.destination_address in terminal_addresses else None)
    return asyncio.run(engine.trace(seed, TracePolicyV2(max_hops=4)))


def add_verified_assertion(store, address, name):
    source = store.create_intelligence_source(IntelligenceSourceCreate(name=f"{name} source", source_type=IntelligenceSourceType.VASP_PUBLISHED, source_uri=f"https://example.org/{name}", trust_tier=TrustTier.A, retrieved_at=NOW))
    entity = store.create_entity(EntityCreate(canonical_name=name, entity_type=EntityType.VASP))
    store.create_entity_address_assertion(EntityAddressAssertionCreate(entity_id=entity.id, address=address, chain=Chain.ETHEREUM, role=EntityRole.VASP_DEPOSIT, assertion_type=AssertionType.VERIFIED, source_id=source.id, review_state=AssertionReviewState.REVIEWED, last_verified_at=NOW, stale_after=NOW + timedelta(days=30)))


def test_multiple_candidates_keep_nearest_and_largest_material_endpoints_separate(tmp_path):
    store = Store(str(tmp_path / "attribution.db"))
    add_verified_assertion(store, NEAR, "Near Exchange")
    add_verified_assertion(store, LARGE, "Large Exchange")
    flow = build_flow([
        tx("ROOT-NEAR", ROOT, NEAR, "10", 1),
        tx("ROOT-MID", ROOT, MID, "7000", 2),
        tx("MID-LARGE", MID, LARGE, "7000", 3),
    ], {NEAR.lower(), LARGE.lower()})
    summary = AttributionEngineV2(EntityResolver(store)).build(flow, Chain.ETHEREUM.value, NOW + timedelta(minutes=4))
    assert len(summary.candidates) == 2
    nearest = next(item for item in summary.candidates if item.id == summary.nearest_actionable_candidate_id)
    largest = next(item for item in summary.candidates if item.id == summary.largest_material_candidate_id)
    assert nearest.entity_name == "Near Exchange"
    assert nearest.min_hops == 1
    assert nearest.attributed_amount == Decimal("10")
    assert largest.entity_name == "Large Exchange"
    assert largest.min_hops == 2
    assert largest.attributed_amount == Decimal("7000")
    assert largest.disputed_share == Decimal("0.7")
    assert largest.path_ids
    assert largest.evidence_ids
    assert largest.attribution_evidence_score == 45
    assert largest.materiality["path_count"] == 1
    assert largest.materiality["time_to_endpoint_seconds"] == 180


def test_weak_inferred_assertion_is_not_presented_as_actionable_vasp(tmp_path):
    store = Store(str(tmp_path / "weak.db"))
    source = store.create_intelligence_source(IntelligenceSourceCreate(name="Single inferred source", source_type=IntelligenceSourceType.RULE_ENGINE, trust_tier=TrustTier.D, retrieved_at=NOW))
    entity = store.create_entity(EntityCreate(canonical_name="Possible Exchange", entity_type=EntityType.VASP))
    store.create_entity_address_assertion(EntityAddressAssertionCreate(entity_id=entity.id, address=NEAR, chain=Chain.ETHEREUM, role=EntityRole.VASP_DEPOSIT, assertion_type=AssertionType.RULE_INFERRED, source_id=source.id, review_state=AssertionReviewState.REVIEWED))
    flow = build_flow([tx("ROOT-NEAR", ROOT, NEAR, "10000", 1)], {NEAR.lower()})
    summary = AttributionEngineV2(EntityResolver(store)).build(flow, Chain.ETHEREUM.value, NOW + timedelta(minutes=2))
    assert summary.candidates == []
    assert summary.warnings == ["NO_ACTIONABLE_VASP_ENDPOINT"]