"""Deterministic, provenance-aware ML baseline. It is disabled by default."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import exp, log
from statistics import median
from typing import Iterable
import uuid

from .canonical import canonical_sha256
from .domain import (
    AssertionReviewState,
    AssertionType,
    AssetRef,
    CanonicalTransfer,
    EntityRole,
    EntityType,
    FeatureSnapshotV2,
    MLInferenceStatus,
    MLLabelTier,
    ModelInferenceV2,
    ModelVersionV2,
    PairAssociationFeatureV2,
    TrainingDatasetV2,
    TrainingRowV2,
    WalletRoleClass,
    normalize_address,
)
from .entity_resolution import EntityResolver
from .storage import Store


FEATURE_SCHEMA_VERSION = "wallet-behavior-v1"
ROLE_MODEL_NAME = "wallet-role-softmax-logistic"
ROLE_MODEL_VERSION = "1.0.0"
PAIR_MODEL_NAME = "vasp-pair-association-weighted-baseline"


ROLE_MAP = {
    EntityRole.VASP_DEPOSIT: WalletRoleClass.DEPOSIT_LIKE,
    EntityRole.VASP_HOT_WALLET: WalletRoleClass.SERVICE_LIKE,
    EntityRole.VASP_COLD_WALLET: WalletRoleClass.SERVICE_LIKE,
    EntityRole.VASP_COLLECTOR: WalletRoleClass.SERVICE_LIKE,
    EntityRole.CUSTODIAL_SERVICE: WalletRoleClass.SERVICE_LIKE,
    EntityRole.PERSONAL_WALLET: WalletRoleClass.ORDINARY,
}


class WalletFeatureExtractor:
    """Computes features solely from transfers at or before the snapshot timestamp."""

    def __init__(self, resolver: EntityResolver) -> None:
        self.resolver = resolver

    def build(
        self,
        address: str,
        asset: AssetRef,
        transfers: Iterable[CanonicalTransfer],
        snapshot_time: datetime,
        *,
        lookback_hours: int | None = None,
        source_block_start: int | None = None,
        source_block_end: int | None = None,
        created_at: datetime | None = None,
    ) -> FeatureSnapshotV2:
        if snapshot_time.tzinfo is None:
            raise ValueError("snapshot_time must include a timezone.")
        normalized = normalize_address(asset.chain, address)
        window_start = snapshot_time - timedelta(hours=lookback_hours) if lookback_hours else None
        relevant = sorted(
            (item for item in transfers if item.asset == asset and item.timestamp <= snapshot_time and (window_start is None or item.timestamp >= window_start)),
            key=lambda item: (item.timestamp, item.id),
        )
        incoming = [item for item in relevant if item.destination_address == normalized]
        outgoing = [item for item in relevant if item.source_address == normalized]
        known_vasp_outgoing, evidence_ids = self._known_vasp_outgoing(outgoing, asset, snapshot_time)
        features = self._features(incoming, outgoing, known_vasp_outgoing, snapshot_time)
        evidence_ids.update(item.raw_evidence_id for item in incoming + outgoing)
        identity = {
            "address": normalized,
            "asset": asset,
            "snapshot_time": snapshot_time,
            "lookback_hours": lookback_hours,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "features": features,
            "evidence_ids": sorted(evidence_ids),
            "source_block_start": source_block_start,
            "source_block_end": source_block_end,
        }
        return FeatureSnapshotV2(
            id=f"FEATURE-{canonical_sha256(identity)[:24].upper()}",
            address=normalized,
            chain=asset.chain,
            asset=asset,
            snapshot_time=snapshot_time,
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            features=features,
            evidence_ids=sorted(evidence_ids),
            source_block_start=source_block_start,
            source_block_end=source_block_end,
            feature_hash_sha256=canonical_sha256(identity),
            created_at=created_at or datetime.now(timezone.utc),
        )

    def _known_vasp_outgoing(self, outgoing: list[CanonicalTransfer], asset: AssetRef, observed_at: datetime) -> tuple[list[CanonicalTransfer], set[str]]:
        recognized: list[CanonicalTransfer] = []
        evidence_ids: set[str] = set()
        for transfer in outgoing:
            resolved = self.resolver.resolve(transfer.destination_address, asset.chain.value, observed_at)
            trusted = [
                item for item in resolved
                if item.entity.entity_type == EntityType.VASP
                and item.effective_review_state == AssertionReviewState.REVIEWED
                and item.assertion.assertion_type == AssertionType.VERIFIED
            ]
            if trusted:
                recognized.append(transfer)
                for item in trusted:
                    evidence_ids.update((item.assertion.id, item.source.id, item.assertion.evidence_hash_sha256))
        return recognized, evidence_ids

    @staticmethod
    def _features(incoming: list[CanonicalTransfer], outgoing: list[CanonicalTransfer], known_vasp_outgoing: list[CanonicalTransfer], snapshot_time: datetime) -> dict[str, float | None]:
        incoming_amounts = [float(item.normalized_amount) for item in incoming]
        outgoing_amounts = [float(item.normalized_amount) for item in outgoing]
        total_in = sum(incoming_amounts)
        total_out = sum(outgoing_amounts)
        by_destination: dict[str, float] = {}
        for item in outgoing:
            by_destination[item.destination_address] = by_destination.get(item.destination_address, 0.0) + float(item.normalized_amount)
        concentration = max(by_destination.values()) / total_out if total_out else None
        entropy = -sum((amount / total_out) * log(amount / total_out) for amount in by_destination.values() if amount and total_out) if total_out else None
        delays = WalletFeatureExtractor._receipt_to_outflow_delays(incoming, outgoing)
        sweep_ratios = [min(float(item.normalized_amount) / total_in, 1.0) for item in outgoing] if total_in else []
        active_days = len({item.timestamp.date() for item in incoming + outgoing})
        known_total = sum(float(item.normalized_amount) for item in known_vasp_outgoing)
        base: dict[str, float | None] = {
            "incoming_tx_count": float(len(incoming)),
            "outgoing_tx_count": float(len(outgoing)),
            "unique_senders": float(len({item.source_address for item in incoming})),
            "unique_receivers": float(len({item.destination_address for item in outgoing})),
            "total_inflow": total_in,
            "total_outflow": total_out,
            "median_incoming_amount": float(median(incoming_amounts)) if incoming_amounts else None,
            "median_outgoing_amount": float(median(outgoing_amounts)) if outgoing_amounts else None,
            "inflow_outflow_ratio": (total_in / total_out) if total_out else None,
            "destination_entropy": entropy,
            "max_destination_concentration": concentration,
            "pct_outflow_to_known_vasp_clusters": (known_total / total_out) if total_out else None,
            "nearest_verified_vasp_hops": 1.0 if known_vasp_outgoing else None,
            "median_receipt_to_outflow_seconds": float(median(delays)) if delays else None,
            "p90_receipt_to_outflow_seconds": WalletFeatureExtractor._percentile(delays, 0.9) if delays else None,
            "sweep_frequency": float(len(delays) / active_days) if active_days else None,
            "median_sweep_ratio": float(median(sweep_ratios)) if sweep_ratios else None,
            "zero_or_low_balance_after_sweep_rate": None,
            "stablecoin_transfer_ratio": 1.0,
            "active_days": float(active_days),
            "transactions_per_active_day": float((len(incoming) + len(outgoing)) / active_days) if active_days else None,
            "is_contract": None,
        }
        for key, value in list(base.items()):
            if value is None:
                base[f"missing_{key}"] = 1.0
            else:
                base[f"missing_{key}"] = 0.0
        return base

    @staticmethod
    def _receipt_to_outflow_delays(incoming: list[CanonicalTransfer], outgoing: list[CanonicalTransfer]) -> list[float]:
        delays: list[float] = []
        available = list(outgoing)
        for receipt in incoming:
            match = next((item for item in available if item.timestamp >= receipt.timestamp), None)
            if match is None:
                continue
            available.remove(match)
            delays.append((match.timestamp - receipt.timestamp).total_seconds())
        return delays

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float:
        ordered = sorted(values)
        index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile)))
        return float(ordered[index])


class TrainingDatasetBuilder:
    """Builds rows from reviewed assertions and keeps weak/unlabeled data distinct."""

    def __init__(self, store: Store, resolver: EntityResolver) -> None:
        self.store = store
        self.resolver = resolver

    def build(self, snapshots: Iterable[FeatureSnapshotV2]) -> TrainingDatasetV2:
        rows: list[TrainingRowV2] = []
        weak_count = 0
        reviewed_count = 0
        unlabeled = 0
        for snapshot in sorted(snapshots, key=lambda item: item.id):
            resolved = self.resolver.resolve(snapshot.address, snapshot.chain.value, snapshot.snapshot_time)
            candidates = []
            for item in resolved:
                label = ROLE_MAP.get(item.assertion.role)
                if label is None or item.effective_review_state != AssertionReviewState.REVIEWED:
                    continue
                if item.assertion.assertion_type == AssertionType.VERIFIED:
                    tier = MLLabelTier.REVIEWED_GROUND_TRUTH
                elif item.assertion.assertion_type in {AssertionType.RULE_INFERRED, AssertionType.ML_INFERRED}:
                    tier = MLLabelTier.WEAK
                else:
                    continue
                candidates.append((tier, item, label))
            if not candidates:
                unlabeled += 1
                continue
            candidates.sort(key=lambda item: (0 if item[0] == MLLabelTier.REVIEWED_GROUND_TRUTH else 1, item[1].assertion.id))
            tier, resolved_item, label = candidates[0]
            if tier == MLLabelTier.REVIEWED_GROUND_TRUTH:
                reviewed_count += 1
            else:
                weak_count += 1
            rows.append(TrainingRowV2(
                feature_snapshot_id=snapshot.id,
                snapshot_time=snapshot.snapshot_time,
                label=label,
                label_tier=tier,
                entity_id=resolved_item.entity.id,
                cluster_id=resolved_item.entity.id,
                label_assertion_id=resolved_item.assertion.id,
                label_source_id=resolved_item.source.id,
                feature_hash_sha256=snapshot.feature_hash_sha256,
            ))
        body = {"task": "wallet_role_classifier", "rows": rows}
        dataset_hash = canonical_sha256(body)
        return TrainingDatasetV2(
            id=f"DATASET-{dataset_hash[:20].upper()}",
            version=f"dataset-{dataset_hash[:12]}",
            task="wallet_role_classifier",
            rows=rows,
            reviewed_row_count=reviewed_count,
            weak_row_count=weak_count,
            excluded_unlabeled_count=unlabeled,
            created_at=datetime.now(timezone.utc),
            dataset_hash_sha256=dataset_hash,
        )


class LeakageSafeSplits:
    @staticmethod
    def temporal(rows: Iterable[TrainingRowV2], cutoff: datetime) -> tuple[list[TrainingRowV2], list[TrainingRowV2]]:
        train = [item for item in rows if item.snapshot_time <= cutoff]
        test = [item for item in rows if item.snapshot_time > cutoff]
        if not train or not test:
            raise ValueError("Temporal evaluation requires rows on both sides of the cutoff.")
        if any(item.snapshot_time > cutoff for item in train) or any(item.snapshot_time <= cutoff for item in test):
            raise AssertionError("Temporal split leakage detected.")
        return train, test

    @staticmethod
    def entity_holdout(rows: Iterable[TrainingRowV2], held_out_entity_ids: set[str]) -> tuple[list[TrainingRowV2], list[TrainingRowV2]]:
        train = [item for item in rows if item.entity_id not in held_out_entity_ids]
        test = [item for item in rows if item.entity_id in held_out_entity_ids]
        if not train or not test:
            raise ValueError("Entity-holdout evaluation requires rows in both train and held-out groups.")
        train_entities = {item.entity_id for item in train}
        test_entities = {item.entity_id for item in test}
        if train_entities & test_entities:
            raise AssertionError("Entity-holdout leakage detected.")
        return train, test


@dataclass(frozen=True)
class TrainedRoleClassifier:
    artifact: dict

    def predict(self, snapshot: FeatureSnapshotV2) -> tuple[WalletRoleClass, float, dict[WalletRoleClass, float], list[str]]:
        names: list[str] = self.artifact["feature_names"]
        means: dict[str, float] = self.artifact["means"]
        scales: dict[str, float] = self.artifact["scales"]
        classes = [WalletRoleClass(item) for item in self.artifact["classes"]]
        vector = [((snapshot.features.get(name) or 0.0) - means[name]) / scales[name] for name in names]
        logits = [self.artifact["biases"][index] + sum(weight * value for weight, value in zip(self.artifact["weights"][index], vector)) for index in range(len(classes))]
        scores = _softmax(logits)
        best = max(range(len(classes)), key=lambda index: scores[index])
        contributions = sorted(((abs(self.artifact["weights"][best][index] * vector[index]), names[index]) for index in range(len(names))), reverse=True)
        return classes[best], scores[best], dict(zip(classes, scores)), [name for _, name in contributions[:5]]


class SoftmaxLogisticRoleBaseline:
    """Dependency-free deterministic logistic baseline for auditable SIH deployment."""

    def train(self, rows: list[TrainingRowV2], snapshots: dict[str, FeatureSnapshotV2], *, iterations: int = 350, learning_rate: float = 0.18, l2: float = 0.001) -> TrainedRoleClassifier:
        reviewed = [item for item in rows if item.label_tier == MLLabelTier.REVIEWED_GROUND_TRUTH]
        if len(reviewed) < 4:
            raise ValueError("At least four reviewed rows are required to train the role baseline.")
        labels = sorted({item.label for item in reviewed}, key=lambda item: item.value)
        if len(labels) < 2:
            raise ValueError("Reviewed training data must contain at least two role classes.")
        snapshots_for_rows = [snapshots[item.feature_snapshot_id] for item in reviewed]
        names = sorted({key for snapshot in snapshots_for_rows for key in snapshot.features})
        means = {name: sum((snapshot.features.get(name) or 0.0) for snapshot in snapshots_for_rows) / len(snapshots_for_rows) for name in names}
        scales = {name: max((sum((((snapshot.features.get(name) or 0.0) - means[name]) ** 2) for snapshot in snapshots_for_rows) / len(snapshots_for_rows)) ** 0.5, 1e-9) for name in names}
        matrix = [[((snapshot.features.get(name) or 0.0) - means[name]) / scales[name] for name in names] for snapshot in snapshots_for_rows]
        weights = [[0.0 for _ in names] for _ in labels]
        biases = [0.0 for _ in labels]
        index_for_label = {label: index for index, label in enumerate(labels)}
        for _ in range(iterations):
            grad_weights = [[0.0 for _ in names] for _ in labels]
            grad_biases = [0.0 for _ in labels]
            for vector, row in zip(matrix, reviewed):
                probabilities = _softmax([biases[index] + sum(weight * value for weight, value in zip(weights[index], vector)) for index in range(len(labels))])
                for class_index in range(len(labels)):
                    error = probabilities[class_index] - (1.0 if index_for_label[row.label] == class_index else 0.0)
                    grad_biases[class_index] += error
                    for feature_index, value in enumerate(vector):
                        grad_weights[class_index][feature_index] += error * value
            scale = 1.0 / len(reviewed)
            for class_index in range(len(labels)):
                biases[class_index] -= learning_rate * grad_biases[class_index] * scale
                for feature_index in range(len(names)):
                    weights[class_index][feature_index] -= learning_rate * ((grad_weights[class_index][feature_index] * scale) + l2 * weights[class_index][feature_index])
        return TrainedRoleClassifier({
            "model_type": "softmax_logistic_regression",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "feature_names": names,
            "means": means,
            "scales": scales,
            "classes": [item.value for item in labels],
            "weights": weights,
            "biases": biases,
            "iterations": iterations,
            "learning_rate": learning_rate,
            "l2": l2,
        })


class ModelEvaluation:
    @staticmethod
    def evaluate(model: TrainedRoleClassifier, rows: list[TrainingRowV2], snapshots: dict[str, FeatureSnapshotV2], threshold: float = 0.90) -> dict:
        if not rows:
            raise ValueError("Evaluation requires at least one row.")
        truth = [item.label for item in rows]
        predicted: list[WalletRoleClass] = []
        deposit_scores: list[float] = []
        for row in rows:
            label, _, scores, _ = model.predict(snapshots[row.feature_snapshot_id])
            predicted.append(label)
            deposit_scores.append(scores.get(WalletRoleClass.DEPOSIT_LIKE, 0.0))
        labels = sorted(set(truth) | set(predicted), key=lambda item: item.value)
        per_class = {label.value: ModelEvaluation._binary_metrics(truth, predicted, label) for label in labels}
        macro_f1 = sum(item["f1"] for item in per_class.values()) / len(per_class)
        majority = Counter(truth).most_common(1)[0][0]
        majority_predictions = [majority for _ in truth]
        baseline_f1 = sum(ModelEvaluation._binary_metrics(truth, majority_predictions, label)["f1"] for label in labels) / len(labels)
        deposit_true = [item == WalletRoleClass.DEPOSIT_LIKE for item in truth]
        high = [index for index, score in enumerate(deposit_scores) if score >= threshold]
        high_precision = sum(1 for index in high if deposit_true[index]) / len(high) if high else None
        return {
            "row_count": len(rows),
            "macro_f1": macro_f1,
            "majority_baseline_macro_f1": baseline_f1,
            "beats_majority_baseline": macro_f1 > baseline_f1,
            "per_class": per_class,
            "deposit_pr_auc": ModelEvaluation._average_precision(deposit_true, deposit_scores),
            "deposit_roc_auc": ModelEvaluation._roc_auc(deposit_true, deposit_scores),
            "deposit_precision_at_threshold": high_precision,
            "operational_threshold": threshold,
        }

    @staticmethod
    def _binary_metrics(truth: list[WalletRoleClass], predicted: list[WalletRoleClass], positive: WalletRoleClass) -> dict[str, float | int]:
        tp = sum(1 for actual, estimated in zip(truth, predicted) if actual == positive and estimated == positive)
        fp = sum(1 for actual, estimated in zip(truth, predicted) if actual != positive and estimated == positive)
        fn = sum(1 for actual, estimated in zip(truth, predicted) if actual == positive and estimated != positive)
        tn = len(truth) - tp - fp - fn
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall, "f1": (2 * precision * recall / (precision + recall)) if precision + recall else 0.0}

    @staticmethod
    def _average_precision(truth: list[bool], scores: list[float]) -> float | None:
        positives = sum(truth)
        if not positives:
            return None
        ranked = sorted(zip(scores, truth), reverse=True)
        hits = 0
        total = 0.0
        for index, (_, actual) in enumerate(ranked, 1):
            if actual:
                hits += 1
                total += hits / index
        return total / positives

    @staticmethod
    def _roc_auc(truth: list[bool], scores: list[float]) -> float | None:
        positive = [score for score, actual in zip(scores, truth) if actual]
        negative = [score for score, actual in zip(scores, truth) if not actual]
        if not positive or not negative:
            return None
        wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in positive for n in negative)
        return wins / (len(positive) * len(negative))


class MLInferenceAdapter:
    def __init__(self, model: ModelVersionV2, *, enabled: bool, strong_threshold: float = 0.90, weak_threshold: float = 0.70) -> None:
        if model.task != "wallet_role_classifier":
            raise ValueError("This adapter accepts only wallet-role classifier models.")
        if weak_threshold > strong_threshold:
            raise ValueError("weak_threshold cannot exceed strong_threshold.")
        self.model = model
        self.enabled = enabled and model.enabled
        self.strong_threshold = strong_threshold
        self.weak_threshold = weak_threshold
        if canonical_sha256(model.artifact) != model.artifact_sha256:
            raise ValueError("Model artifact hash does not match the registered artifact.")
        self.classifier = TrainedRoleClassifier(model.artifact)

    def infer(self, snapshot: FeatureSnapshotV2) -> ModelInferenceV2:
        if snapshot.feature_schema_version != self.model.feature_schema_version:
            raise ValueError("Feature schema version does not match the model registry entry.")
        role, score, _, contributors = self.classifier.predict(snapshot)
        if not self.enabled:
            status = MLInferenceStatus.WITHHELD
            explanation = "ML inference is disabled by configuration. No ML assertion was emitted."
        elif score >= self.strong_threshold:
            status = MLInferenceStatus.STRONG
            explanation = "ML role inference is strong under the configured validation threshold; it remains ML_INFERRED and requires review."
        elif score >= self.weak_threshold:
            status = MLInferenceStatus.WEAK
            explanation = "ML role inference is below the strong operational threshold; it remains non-actionable ML_INFERRED evidence."
        else:
            status = MLInferenceStatus.WITHHELD
            explanation = "ML score is below the configured threshold; no role claim is emitted."
        return ModelInferenceV2(
            id=f"MLINF-{canonical_sha256({'model': self.model.id, 'snapshot': snapshot.id, 'enabled': self.enabled})[:24].upper()}",
            model_version_id=self.model.id,
            feature_snapshot_id=snapshot.id,
            task="wallet_role_classifier",
            status=status,
            predicted_role=role if status != MLInferenceStatus.WITHHELD else WalletRoleClass.UNKNOWN,
            raw_score=score,
            threshold_applied=self.strong_threshold,
            top_contributing_features=contributors,
            explanation=explanation,
            created_at=datetime.now(timezone.utc),
        )


class VaspPairAssociationBaseline:
    """Conservative pairwise baseline: scores address-to-candidate-VASP behavior, never ownership."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def features(self, address: str, candidate_entity_id: str, asset: AssetRef, transfers: Iterable[CanonicalTransfer], snapshot_time: datetime) -> PairAssociationFeatureV2:
        normalized = normalize_address(asset.chain, address)
        target_addresses = {
            item.address for item in self.store.list_entity_address_assertions_for_entity(candidate_entity_id, asset.chain.value)
            if item.review_state == AssertionReviewState.REVIEWED and item.assertion_type == AssertionType.VERIFIED
        }
        relevant = [item for item in transfers if item.asset == asset and item.timestamp <= snapshot_time]
        incoming = sorted((item for item in relevant if item.destination_address == normalized), key=lambda item: item.timestamp)
        outgoing = sorted((item for item in relevant if item.source_address == normalized), key=lambda item: item.timestamp)
        directed = [item for item in outgoing if item.destination_address in target_addresses]
        total = sum((item.normalized_amount for item in outgoing), Decimal("0"))
        directed_total = sum((item.normalized_amount for item in directed), Decimal("0"))
        delays = WalletFeatureExtractor._receipt_to_outflow_delays(incoming, directed)
        latest = max((item.timestamp for item in directed), default=None)
        features = {
            "minimum_path_distance_to_verified_cluster": 1.0 if directed else None,
            "value_share_to_cluster": float(directed_total / total) if total else None,
            "outgoing_destination_concentration_to_cluster": float(directed_total / total) if total else None,
            "distinct_verified_cluster_nodes_reached": float(len({item.destination_address for item in directed})),
            "median_receipt_to_cluster_seconds": float(median(delays)) if delays else None,
            "repeat_sweep_count_toward_cluster": float(len(directed)),
            "fee_funder_relationship": None,
            "cluster_interaction_recency_seconds": float((snapshot_time - latest).total_seconds()) if latest else None,
            "rule_evidence_components": 0.0,
        }
        evidence = sorted({item.id for item in directed} | {item.raw_evidence_id for item in directed})
        return PairAssociationFeatureV2(address=normalized, candidate_entity_id=candidate_entity_id, snapshot_time=snapshot_time, features=features, evidence_ids=evidence)

    def infer(self, pair: PairAssociationFeatureV2, model_version_id: str = "PAIR-BASELINE-V1") -> ModelInferenceV2:
        share = pair.features.get("value_share_to_cluster") or 0.0
        repeat = min((pair.features.get("repeat_sweep_count_toward_cluster") or 0.0) / 3.0, 1.0)
        direct = 1.0 if pair.features.get("minimum_path_distance_to_verified_cluster") == 1.0 else 0.0
        score = min(1.0, 0.55 * share + 0.25 * repeat + 0.20 * direct)
        status = MLInferenceStatus.STRONG if score >= 0.90 else MLInferenceStatus.WEAK if score >= 0.75 else MLInferenceStatus.WITHHELD
        return ModelInferenceV2(
            id=f"MLINF-{canonical_sha256({'pair': pair, 'model': model_version_id})[:24].upper()}",
            model_version_id=model_version_id,
            feature_snapshot_id=f"PAIR-{canonical_sha256(pair)[:20].upper()}",
            task="vasp_pair_association",
            status=status,
            candidate_entity_id=pair.candidate_entity_id,
            raw_score=score,
            threshold_applied=0.90,
            top_contributing_features=["value_share_to_cluster", "repeat_sweep_count_toward_cluster", "minimum_path_distance_to_verified_cluster"],
            explanation="Pairwise behavioral association score. It is ML_INFERRED evidence only and does not establish VASP ownership or beneficial ownership.",
            created_at=datetime.now(timezone.utc),
        )


def register_trained_role_model(store: Store, dataset: TrainingDatasetV2, classifier: TrainedRoleClassifier, evaluation_metrics: dict | None = None, *, enabled: bool = False) -> ModelVersionV2:
    artifact = classifier.artifact
    artifact_hash = canonical_sha256(artifact)
    model = ModelVersionV2(
        id=f"MODEL-{artifact_hash[:20].upper()}",
        model_name=ROLE_MODEL_NAME,
        version=f"{ROLE_MODEL_VERSION}+{artifact_hash[:12]}",
        task="wallet_role_classifier",
        artifact_uri=f"sqlite://model_versions/{artifact_hash}",
        artifact_sha256=artifact_hash,
        artifact=artifact,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        training_dataset_version=dataset.version,
        trained_at=datetime.now(timezone.utc),
        evaluation_metrics=evaluation_metrics or {},
        threshold_config={"strong": 0.90, "weak": 0.70},
        enabled=enabled,
        notes="Pure-Python deterministic logistic baseline. Scores are not calibrated probabilities. Enable only after reviewed validation metrics are registered.",
    )
    return store.save_model_version_v2(model)


def _softmax(values: list[float]) -> list[float]:
    maximum = max(values)
    exponentials = [exp(value - maximum) for value in values]
    total = sum(exponentials)
    return [value / total for value in exponentials]

def register_pair_association_baseline(store: Store) -> ModelVersionV2:
    artifact = {
        "model_type": "weighted_pair_association_baseline",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "weights": {
            "value_share_to_cluster": 0.55,
            "repeat_sweep_count_toward_cluster": 0.25,
            "minimum_path_distance_to_verified_cluster": 0.20,
        },
        "strong_threshold": 0.90,
        "weak_threshold": 0.75,
    }
    artifact_hash = canonical_sha256(artifact)
    return store.save_model_version_v2(ModelVersionV2(
        id=f"MODEL-{artifact_hash[:20].upper()}",
        model_name=PAIR_MODEL_NAME,
        version=f"1.0.0+{artifact_hash[:12]}",
        task="vasp_pair_association",
        artifact_uri=f"sqlite://model_versions/{artifact_hash}",
        artifact_sha256=artifact_hash,
        artifact=artifact,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        training_dataset_version="not-applicable-weighted-baseline",
        trained_at=datetime.now(timezone.utc),
        evaluation_metrics={},
        threshold_config={"strong": 0.90, "weak": 0.75},
        enabled=False,
        notes="Conservative pairwise baseline. It is not a calibrated probability and never creates a verified assertion.",
    ))