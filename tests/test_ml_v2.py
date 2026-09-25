from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.canonical import canonical_sha256
from backend.domain import (
    AssertionReviewState,
    AssertionType,
    AssetRef,
    CanonicalTransfer,
    EntityAddressAssertionCreate,
    EntityCreate,
    EntityRole,
    EntityType,
    FeatureSnapshotV2,
    IntelligenceSourceCreate,
    IntelligenceSourceType,
    MLInferenceStatus,
    MLLabelTier,
    TrustTier,
)
from backend.entity_resolution import EntityResolver
from backend.ml_v2 import (
    FEATURE_SCHEMA_VERSION,
    LeakageSafeSplits,
    MLInferenceAdapter,
    ModelEvaluation,
    SoftmaxLogisticRoleBaseline,
    TrainingDatasetBuilder,
    VaspPairAssociationBaseline,
    WalletFeatureExtractor,
    register_pair_association_baseline,
    register_trained_role_model,
)
from backend.models import Chain
from backend.storage import Store


NOW = datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc)
ASSET = AssetRef(chain=Chain.ETHEREUM, symbol="USDT", contract_address="0x" + "c" * 40, decimals=6)
ROOT = "0x" + "1" * 40
COLLECTOR = "0x" + "2" * 40


def address(number: int) -> str:
    return "0x" + f"{number:040x}"


def snapshot(identifier: int, role_signal: float, time: datetime) -> FeatureSnapshotV2:
    features = {
        "incoming_tx_count": role_signal * 10,
        "outgoing_tx_count": role_signal * 8,
        "max_destination_concentration": role_signal,
        "pct_outflow_to_known_vasp_clusters": role_signal,
        "missing_is_contract": 1.0,
    }
    body = {"address": address(identifier), "time": time, "features": features}
    return FeatureSnapshotV2(
        id=f"FEATURE-TEST-{identifier}", address=address(identifier), chain=Chain.ETHEREUM, asset=ASSET,
        snapshot_time=time, feature_schema_version=FEATURE_SCHEMA_VERSION, features=features,
        evidence_ids=[f"EVID-{identifier}"], feature_hash_sha256=canonical_sha256(body), created_at=time,
    )


def labelled_store(tmp_path):
    store = Store(str(tmp_path / "ml.db"))
    source = store.create_intelligence_source(IntelligenceSourceCreate(
        name="Reviewed ML fixture source", source_type=IntelligenceSourceType.INTERNAL_REVIEW,
        trust_tier=TrustTier.A, retrieved_at=NOW,
    ))
    labels = [
        (1, EntityRole.VASP_DEPOSIT, "Deposit A"),
        (2, EntityRole.VASP_DEPOSIT, "Deposit B"),
        (3, EntityRole.VASP_DEPOSIT, "Deposit C"),
        (4, EntityRole.VASP_HOT_WALLET, "Service A"),
        (5, EntityRole.VASP_HOT_WALLET, "Service B"),
        (6, EntityRole.VASP_HOT_WALLET, "Service C"),
        (7, EntityRole.PERSONAL_WALLET, "Ordinary A"),
        (8, EntityRole.PERSONAL_WALLET, "Ordinary B"),
        (9, EntityRole.PERSONAL_WALLET, "Ordinary C"),
    ]
    for index, role, name in labels:
        entity = store.create_entity(EntityCreate(canonical_name=name, entity_type=EntityType.VASP if role != EntityRole.PERSONAL_WALLET else EntityType.UNKNOWN))
        store.create_entity_address_assertion(EntityAddressAssertionCreate(
            entity_id=entity.id, address=address(index), chain=Chain.ETHEREUM, role=role,
            assertion_type=AssertionType.VERIFIED, source_id=source.id,
            review_state=AssertionReviewState.REVIEWED, last_verified_at=NOW,
        ))
    return store, source


def test_feature_snapshot_excludes_transfers_after_snapshot_time(tmp_path):
    store, _ = labelled_store(tmp_path)
    before = CanonicalTransfer(id="BEFORE", transaction_id="TX-BEFORE", chain=Chain.ETHEREUM, source_address=ROOT, destination_address=address(1), asset=ASSET, raw_amount=Decimal("50"), normalized_amount=Decimal("50"), timestamp=NOW, raw_evidence_id="EVID-BEFORE")
    after = CanonicalTransfer(id="AFTER", transaction_id="TX-AFTER", chain=Chain.ETHEREUM, source_address=ROOT, destination_address=address(1), asset=ASSET, raw_amount=Decimal("500"), normalized_amount=Decimal("500"), timestamp=NOW + timedelta(minutes=1), raw_evidence_id="EVID-AFTER")
    feature = WalletFeatureExtractor(EntityResolver(store)).build(address(1), ASSET, [before, after], NOW)
    assert feature.features["incoming_tx_count"] == 1.0
    assert feature.features["total_inflow"] == 50.0
    assert "EVID-BEFORE" in feature.evidence_ids
    assert "EVID-AFTER" not in feature.evidence_ids
    assert store.save_feature_snapshot_v2(feature).id == feature.id


def test_dataset_builder_separates_reviewed_weak_and_unlabelled_rows(tmp_path):
    store, source = labelled_store(tmp_path)
    weak_entity = store.create_entity(EntityCreate(canonical_name="Weak deposit", entity_type=EntityType.VASP))
    store.create_entity_address_assertion(EntityAddressAssertionCreate(
        entity_id=weak_entity.id, address=address(10), chain=Chain.ETHEREUM, role=EntityRole.VASP_DEPOSIT,
        assertion_type=AssertionType.RULE_INFERRED, source_id=source.id, review_state=AssertionReviewState.REVIEWED,
    ))
    snapshots = [snapshot(1, 0.95, NOW), snapshot(10, 0.8, NOW), snapshot(11, 0.1, NOW)]
    for item in snapshots:
        store.save_feature_snapshot_v2(item)
    dataset = TrainingDatasetBuilder(store, EntityResolver(store)).build(snapshots)
    assert dataset.reviewed_row_count == 1
    assert dataset.weak_row_count == 1
    assert dataset.excluded_unlabeled_count == 1
    assert {row.label_tier for row in dataset.rows} == {MLLabelTier.REVIEWED_GROUND_TRUTH, MLLabelTier.WEAK}
    assert store.save_training_dataset_v2(dataset).dataset_hash_sha256 == dataset.dataset_hash_sha256


def test_role_baseline_evaluation_and_leakage_safe_splits(tmp_path):
    store, _ = labelled_store(tmp_path)
    signals = {1: 0.95, 2: 0.90, 3: 0.88, 4: 0.55, 5: 0.50, 6: 0.48, 7: 0.05, 8: 0.10, 9: 0.12}
    times = {index: NOW + timedelta(days=0 if index in {1, 4, 7} else 1 if index in {2, 5, 8} else 2) for index in signals}
    snapshots = [snapshot(index, signal, times[index]) for index, signal in signals.items()]
    for item in snapshots:
        store.save_feature_snapshot_v2(item)
    dataset = TrainingDatasetBuilder(store, EntityResolver(store)).build(snapshots)
    snapshot_map = {item.id: item for item in snapshots}
    train, test = LeakageSafeSplits.temporal(dataset.rows, NOW + timedelta(days=1, hours=12))
    assert {row.snapshot_time for row in train}.isdisjoint({row.snapshot_time for row in test})
    classifier = SoftmaxLogisticRoleBaseline().train(train, snapshot_map)
    metrics = ModelEvaluation.evaluate(classifier, test, snapshot_map, threshold=0.70)
    assert metrics["beats_majority_baseline"]
    assert metrics["macro_f1"] > metrics["majority_baseline_macro_f1"]
    deposit_entities = {row.entity_id for row in dataset.rows if row.label.value == "DEPOSIT_LIKE"}
    held_train, held_test = LeakageSafeSplits.entity_holdout(dataset.rows, {next(iter(deposit_entities))})
    assert {row.entity_id for row in held_train}.isdisjoint({row.entity_id for row in held_test})


def test_model_registry_hash_and_disabled_inference_never_emits_verified(tmp_path):
    store, _ = labelled_store(tmp_path)
    snapshots = [snapshot(1, 0.95, NOW), snapshot(2, 0.90, NOW), snapshot(4, 0.55, NOW), snapshot(5, 0.50, NOW), snapshot(7, 0.05, NOW), snapshot(8, 0.10, NOW)]
    for item in snapshots:
        store.save_feature_snapshot_v2(item)
    dataset = TrainingDatasetBuilder(store, EntityResolver(store)).build(snapshots)
    model = register_trained_role_model(store, dataset, SoftmaxLogisticRoleBaseline().train(dataset.rows, {item.id: item for item in snapshots}), enabled=False)
    assert model.artifact_sha256 == canonical_sha256(model.artifact)
    inference = MLInferenceAdapter(model, enabled=False).infer(snapshots[0])
    assert inference.status == MLInferenceStatus.WITHHELD
    assert inference.assertion_type == "ML_INFERRED"
    assert inference.predicted_role.value == "UNKNOWN"
    assert store.save_model_inference_v2(inference).id == inference.id


def test_pair_association_baseline_uses_verified_cluster_interaction_only(tmp_path):
    store, source = labelled_store(tmp_path)
    vasp = store.create_entity(EntityCreate(canonical_name="Target VASP", entity_type=EntityType.VASP))
    store.create_entity_address_assertion(EntityAddressAssertionCreate(
        entity_id=vasp.id, address=COLLECTOR, chain=Chain.ETHEREUM, role=EntityRole.VASP_COLLECTOR,
        assertion_type=AssertionType.VERIFIED, source_id=source.id, review_state=AssertionReviewState.REVIEWED,
    ))
    transfers = [
        CanonicalTransfer(id=f"IN-{i}", transaction_id=f"TX-IN-{i}", chain=Chain.ETHEREUM, source_address=address(20 + i), destination_address=address(12), asset=ASSET, raw_amount=Decimal("100"), normalized_amount=Decimal("100"), timestamp=NOW + timedelta(minutes=i * 5), raw_evidence_id=f"EVID-IN-{i}")
        for i in range(3)
    ] + [
        CanonicalTransfer(id=f"OUT-{i}", transaction_id=f"TX-OUT-{i}", chain=Chain.ETHEREUM, source_address=address(12), destination_address=COLLECTOR, asset=ASSET, raw_amount=Decimal("98"), normalized_amount=Decimal("98"), timestamp=NOW + timedelta(minutes=i * 5 + 1), raw_evidence_id=f"EVID-OUT-{i}")
        for i in range(3)
    ]
    pair = VaspPairAssociationBaseline(store).features(address(12), vasp.id, ASSET, transfers, NOW + timedelta(minutes=20))
    inference = VaspPairAssociationBaseline(store).infer(pair, register_pair_association_baseline(store).id)
    assert pair.features["value_share_to_cluster"] == 1.0
    assert inference.status == MLInferenceStatus.STRONG
    assert inference.assertion_type == "ML_INFERRED"