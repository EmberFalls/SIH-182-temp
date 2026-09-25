from datetime import datetime, timedelta, timezone

from backend.domain import (
    AssertionReviewState,
    AssertionType,
    EntityAddressAssertionCreate,
    EntityCreate,
    EntityRole,
    EntityType,
    IntelligenceSourceCreate,
    IntelligenceSourceType,
    TrustTier,
)
from backend.entity_resolution import EntityResolver
from backend.models import Chain, VaspLabelCreate
from backend.storage import Store


NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)
ADDRESS = "0x" + "a" * 40


def source(store, name="Primary source", tier=TrustTier.A):
    return store.create_intelligence_source(IntelligenceSourceCreate(
        name=name,
        source_type=IntelligenceSourceType.VASP_PUBLISHED,
        source_uri="https://example.org/proof",
        trust_tier=tier,
        retrieved_at=NOW,
    ))


def test_entity_assertion_retains_role_provenance_and_evidence_hash(tmp_path):
    store = Store(str(tmp_path / "registry.db"))
    evidence_source = source(store)
    entity = store.create_entity(EntityCreate(canonical_name="Example VASP", entity_type=EntityType.VASP))
    assertion = store.create_entity_address_assertion(EntityAddressAssertionCreate(
        entity_id=entity.id,
        address=ADDRESS.upper(),
        chain=Chain.ETHEREUM,
        role=EntityRole.VASP_HOT_WALLET,
        assertion_type=AssertionType.VERIFIED,
        source_id=evidence_source.id,
        review_state=AssertionReviewState.REVIEWED,
        first_verified_at=NOW,
        last_verified_at=NOW,
        stale_after=NOW + timedelta(days=30),
        notes="Direct published address evidence.",
    ))
    assert assertion.address == ADDRESS
    assert len(assertion.evidence_hash_sha256) == 64
    resolved = store.resolve_entity_assertions(ADDRESS, Chain.ETHEREUM.value, NOW)
    assert resolved[0].entity.canonical_name == "Example VASP"
    assert resolved[0].assertion.role == EntityRole.VASP_HOT_WALLET
    assert resolved[0].effective_review_state == AssertionReviewState.REVIEWED


def test_stale_and_rejected_assertions_are_not_presented_as_current_support(tmp_path):
    store = Store(str(tmp_path / "stale.db"))
    stale_source = source(store, "Old source", TrustTier.B)
    stale_entity = store.create_entity(EntityCreate(canonical_name="Old VASP", entity_type=EntityType.VASP))
    store.create_entity_address_assertion(EntityAddressAssertionCreate(
        entity_id=stale_entity.id, address=ADDRESS, chain=Chain.ETHEREUM, role=EntityRole.VASP_DEPOSIT,
        assertion_type=AssertionType.VERIFIED, source_id=stale_source.id, review_state=AssertionReviewState.REVIEWED,
        stale_after=NOW - timedelta(days=1),
    ))
    rejected_source = source(store, "Rejected source", TrustTier.C)
    rejected_entity = store.create_entity(EntityCreate(canonical_name="Rejected VASP", entity_type=EntityType.VASP))
    store.create_entity_address_assertion(EntityAddressAssertionCreate(
        entity_id=rejected_entity.id, address=ADDRESS, chain=Chain.ETHEREUM, role=EntityRole.VASP_DEPOSIT,
        assertion_type=AssertionType.RULE_INFERRED, source_id=rejected_source.id, review_state=AssertionReviewState.REJECTED,
    ))
    resolved = EntityResolver(store).resolve(ADDRESS, Chain.ETHEREUM.value, NOW)
    assert len(resolved) == 1
    assert resolved[0].effective_review_state == AssertionReviewState.STALE
    assert resolved[0].warnings == ["STALE_ENTITY_LABEL"]


def test_legacy_label_migration_is_idempotent_and_preserves_source(tmp_path):
    store = Store(str(tmp_path / "legacy.db"))
    label = store.add_label(VaspLabelCreate(
        address=ADDRESS,
        chain=Chain.ETHEREUM,
        vasp_name="Reviewed Exchange",
        label_type="hot_wallet",
        confidence="verified",
        reviewer="Reviewer",
        source={"url": "https://example.org/label", "source_name": "Reviewed explorer label", "observed_at": NOW.isoformat()},
    ))
    first = store.migrate_legacy_labels_to_assertions()
    second = store.migrate_legacy_labels_to_assertions()
    resolved = store.resolve_entity_assertions(ADDRESS, Chain.ETHEREUM.value, NOW)
    assert first == {"migrated": 1, "skipped": 0}
    assert second == {"migrated": 0, "skipped": 1}
    assert resolved[0].assertion.assertion_type == AssertionType.VERIFIED
    assert resolved[0].source.name == "Reviewed explorer label"
    assert f"legacy_label_id={label.id}" in resolved[0].assertion.notes