from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.deposit_inference import DepositPatternResolver, persist_unreviewed_inference
from backend.domain import (
    AssertionReviewState,
    AssertionType,
    AssetRef,
    CanonicalTransfer,
    EntityAddressAssertionCreate,
    EntityCreate,
    EntityRole,
    EntityType,
    IntelligenceSourceCreate,
    IntelligenceSourceType,
    TrustTier,
)
from backend.entity_resolution import EntityResolver
from backend.models import Chain
from backend.storage import Store


NOW = datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc)
ASSET = AssetRef(chain=Chain.ETHEREUM, symbol="USDT", contract_address="0x" + "c" * 40, decimals=6)
DEPOSIT = "0x" + "a" * 40
COLLECTOR = "0x" + "b" * 40
SENDER_ONE = "0x" + "d" * 40
SENDER_TWO = "0x" + "e" * 40


def transfer(identifier, source, destination, amount, minute):
    return CanonicalTransfer(
        id=identifier, transaction_id=f"TX-{identifier}", chain=Chain.ETHEREUM,
        source_address=source, destination_address=destination, asset=ASSET,
        raw_amount=Decimal(amount), normalized_amount=Decimal(amount),
        timestamp=NOW + timedelta(minutes=minute), raw_evidence_id="EVID-CHAIN",
    )


def add_target_assertion(store, assertion_type=AssertionType.VERIFIED):
    source = store.create_intelligence_source(IntelligenceSourceCreate(name="Reviewed VASP source", source_type=IntelligenceSourceType.VASP_PUBLISHED, source_uri="https://example.org/vasp", trust_tier=TrustTier.A, retrieved_at=NOW))
    entity = store.create_entity(EntityCreate(canonical_name="Target VASP", entity_type=EntityType.VASP))
    store.create_entity_address_assertion(EntityAddressAssertionCreate(
        entity_id=entity.id, address=COLLECTOR, chain=Chain.ETHEREUM, role=EntityRole.VASP_COLLECTOR,
        assertion_type=assertion_type, source_id=source.id, review_state=AssertionReviewState.REVIEWED,
        last_verified_at=NOW, stale_after=NOW + timedelta(days=30),
    ))
    return entity


def observed_deposit_pattern():
    return [
        transfer("IN-1", SENDER_ONE, DEPOSIT, "100", 1),
        transfer("OUT-1", DEPOSIT, COLLECTOR, "98", 4),
        transfer("IN-2", SENDER_TWO, DEPOSIT, "200", 10),
        transfer("OUT-2", DEPOSIT, COLLECTOR, "196", 14),
    ]


def test_deposit_pattern_inference_uses_only_verified_target_evidence(tmp_path):
    store = Store(str(tmp_path / "inference.db"))
    entity = add_target_assertion(store)
    results = DepositPatternResolver(EntityResolver(store)).infer(DEPOSIT, ASSET, observed_deposit_pattern(), NOW + timedelta(minutes=20))
    assert len(results) == 1
    inference = results[0]
    assert inference.candidate_entity_id == entity.id
    assert inference.inferred_role == EntityRole.VASP_DEPOSIT
    assert inference.assertion_type == AssertionType.RULE_INFERRED
    assert inference.evidence_score == 75
    assert inference.evidence_components["direct_verified_collector"] == 30
    assert inference.evidence_components["outflow_concentration"] == 20
    assert inference.evidence_components["repeated_short_delay_sweep"] == 15
    assert inference.evidence_components["low_destination_diversity"] == 10
    assert inference.feature_snapshot["outflow_concentration"] == "1"
    assert inference.evidence_lineage_ids
    assert all("verified" in reason.lower() or "concentrates" in reason.lower() or "receipt-to-sweep" in reason.lower() or "diversity" in reason.lower() for reason in inference.reasons)


def test_rule_engine_does_not_use_an_inferred_target_as_its_own_proof(tmp_path):
    store = Store(str(tmp_path / "circular.db"))
    add_target_assertion(store, AssertionType.RULE_INFERRED)
    results = DepositPatternResolver(EntityResolver(store)).infer(DEPOSIT, ASSET, observed_deposit_pattern(), NOW + timedelta(minutes=20))
    assert results == []


def test_persisted_inference_remains_unreviewed_until_human_review(tmp_path):
    store = Store(str(tmp_path / "persist.db"))
    add_target_assertion(store)
    inference = DepositPatternResolver(EntityResolver(store)).infer(DEPOSIT, ASSET, observed_deposit_pattern(), NOW + timedelta(minutes=20))[0]
    assertion = persist_unreviewed_inference(store, inference)
    repeat = persist_unreviewed_inference(store, inference)
    assert assertion.id == repeat.id
    assert assertion.review_state == AssertionReviewState.UNREVIEWED
    assert assertion.evidence_score == 75
    assert store.get_deposit_inference(inference.id).evidence_lineage_ids == inference.evidence_lineage_ids