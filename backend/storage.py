import json
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .canonical import canonical_sha256
from .config import settings
from .domain import CaseCreateV2, InvestigationCaseV2, InvestigationResultV2, RequestDraftV2, FeatureSnapshotV2, TrainingDatasetV2, ModelVersionV2, ModelInferenceV2, RawEvidenceArtifact, AssertionReviewEventV2
from .domain import (
    AssertionReviewState,
    AssertionType,
    Entity,
    EntityAddressAssertion,
    EntityAddressAssertionCreate,
    EntityCreate,
    DepositInferenceResult,
    EntityRole,
    EntityType,
    IntelligenceSource,
    IntelligenceSourceCreate,
    IntelligenceSourceType,
    ResolvedEntityAssertion,
    TrustTier,
)
from .cross_chain_v2 import BridgeRouteV2, CrossChainLinkV2
from .models import CaseCreate, CaseNote, CaseSummary, CaseUpdate, LabelReview, LabelReviewEvent, VaspLabel, VaspLabelCreate


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, Decimal)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


class Store:
    def __init__(self, database_path: str | None = None) -> None:
        self.path = Path(database_path or settings.database_path)
        self._initialize()

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS labels (
                    id TEXT PRIMARY KEY, address TEXT NOT NULL, chain TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(address, chain, payload)
                );
                CREATE TABLE IF NOT EXISTS trace_runs (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL,
                    resource TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS case_notes (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, author TEXT NOT NULL,
                    note TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS label_reviews (
                    id TEXT PRIMARY KEY, label_id TEXT NOT NULL, reviewer TEXT NOT NULL,
                    status TEXT NOT NULL, rationale TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS investigation_cases_v2 (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS investigation_cases_v2_created_idx
                    ON investigation_cases_v2(created_at DESC);                CREATE TABLE IF NOT EXISTS raw_evidence_artifacts_v2 (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assertion_reviews_v2 (
                    id TEXT PRIMARY KEY, assertion_id TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS assertion_reviews_v2_assertion_idx
                    ON assertion_reviews_v2(assertion_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS intelligence_sources (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS entities_name_idx ON entities(canonical_name);
                CREATE TABLE IF NOT EXISTS entity_address_assertions (
                    id TEXT PRIMARY KEY, address TEXT NOT NULL, chain TEXT NOT NULL, entity_id TEXT NOT NULL,
                    source_id TEXT NOT NULL, role TEXT NOT NULL, assertion_type TEXT NOT NULL, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(address, chain, entity_id, source_id, role, assertion_type)
                );
                CREATE INDEX IF NOT EXISTS entity_assertions_address_chain_idx
                    ON entity_address_assertions(address, chain, created_at DESC);                CREATE TABLE IF NOT EXISTS deposit_inferences (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS deposit_inferences_address_idx
                    ON deposit_inferences(created_at DESC);
                CREATE TABLE IF NOT EXISTS investigation_results_v2 (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, version INTEGER NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(case_id, version)
                );
                CREATE INDEX IF NOT EXISTS investigation_results_v2_case_idx
                    ON investigation_results_v2(case_id, version DESC);
                CREATE TABLE IF NOT EXISTS request_drafts_v2 (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, result_id TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS request_drafts_v2_case_idx
                    ON request_drafts_v2(case_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS feature_snapshots_v2 (
                    id TEXT PRIMARY KEY, address TEXT NOT NULL, chain TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS feature_snapshots_v2_address_idx
                    ON feature_snapshots_v2(address, chain, created_at DESC);
                CREATE TABLE IF NOT EXISTS training_datasets_v2 (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_versions_v2 (
                    id TEXT PRIMARY KEY, model_name TEXT NOT NULL, version TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(model_name, version)
                );
                CREATE TABLE IF NOT EXISTS model_inferences_v2 (
                    id TEXT PRIMARY KEY, model_version_id TEXT NOT NULL, feature_snapshot_id TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS model_inferences_v2_snapshot_idx
                    ON model_inferences_v2(feature_snapshot_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS bridge_routes_v2 (
                    id TEXT PRIMARY KEY, bridge_entity_id TEXT NOT NULL, protocol TEXT NOT NULL,
                    source_chain TEXT NOT NULL, destination_chain TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS bridge_routes_v2_pair_idx
                    ON bridge_routes_v2(source_chain, destination_chain, created_at DESC);
                CREATE TABLE IF NOT EXISTS cross_chain_links_v2 (
                    id TEXT PRIMARY KEY, route_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS cross_chain_links_v2_route_idx
                    ON cross_chain_links_v2(route_id, created_at DESC);            """)

    def create_case(self, payload: CaseCreate) -> CaseSummary:
        created_at = _utcnow()
        case = CaseSummary(id=f"CASE-{uuid.uuid4().hex[:12].upper()}", created_at=created_at, **payload.model_dump())
        with self._connection() as connection:
            connection.execute("INSERT INTO cases VALUES (?, ?, ?)", (case.id, json.dumps(case.model_dump(mode="json")), created_at.isoformat()))
        return case

    def get_case(self, case_id: str) -> CaseSummary | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM cases WHERE id = ?", (case_id,)).fetchone()
        return CaseSummary.model_validate_json(row["payload"]) if row else None

    def list_cases(self) -> list[CaseSummary]:
        with self._connection() as connection:
            rows = connection.execute("SELECT payload FROM cases ORDER BY created_at DESC").fetchall()
        return [CaseSummary.model_validate_json(row["payload"]) for row in rows]

    def create_investigation_case_v2(self, payload: CaseCreateV2, created_by: str) -> InvestigationCaseV2:
        created_at = _utcnow()
        case = InvestigationCaseV2(
            id=f"CASEV2-{uuid.uuid4().hex[:12].upper()}", title=payload.title, context=payload.context,
            external_case_ref=payload.external_case_ref, trace_policy_id=payload.trace_policy_id, trace_policy=payload.trace_policy,
            created_at=created_at, created_by=created_by,
        )
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO investigation_cases_v2 VALUES (?, ?, ?)",
                (case.id, json.dumps(case.model_dump(mode="json"), default=_json_default, sort_keys=True), created_at.isoformat()),
            )
        return case

    def get_investigation_case_v2(self, case_id: str) -> InvestigationCaseV2 | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM investigation_cases_v2 WHERE id = ?", (case_id,)).fetchone()
        return InvestigationCaseV2.model_validate_json(row["payload"]) if row else None

    def list_investigation_cases_v2(self) -> list[InvestigationCaseV2]:
        with self._connection() as connection:
            rows = connection.execute("SELECT payload FROM investigation_cases_v2 ORDER BY created_at DESC").fetchall()
        return [InvestigationCaseV2.model_validate_json(row["payload"]) for row in rows]


    def save_raw_evidence_artifact_v2(self, artifact: RawEvidenceArtifact) -> RawEvidenceArtifact:
        serialized = json.dumps(artifact.model_dump(mode="json"), default=_json_default, sort_keys=True)
        with self._connection() as connection:
            existing = connection.execute("SELECT payload FROM raw_evidence_artifacts_v2 WHERE id = ?", (artifact.id,)).fetchone()
            if existing:
                return RawEvidenceArtifact.model_validate_json(existing["payload"])
            connection.execute("INSERT INTO raw_evidence_artifacts_v2 VALUES (?, ?, ?)", (artifact.id, serialized, artifact.retrieved_at.isoformat()))
        return artifact

    def get_raw_evidence_artifact_v2(self, artifact_id: str) -> RawEvidenceArtifact | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM raw_evidence_artifacts_v2 WHERE id = ?", (artifact_id,)).fetchone()
        return RawEvidenceArtifact.model_validate_json(row["payload"]) if row else None

    def list_raw_evidence_artifacts_v2(self, artifact_ids: list[str] | None = None) -> list[RawEvidenceArtifact]:
        with self._connection() as connection:
            if artifact_ids:
                placeholders = ",".join("?" for _ in artifact_ids)
                rows = connection.execute(f"SELECT payload FROM raw_evidence_artifacts_v2 WHERE id IN ({placeholders}) ORDER BY created_at ASC", artifact_ids).fetchall()
            else:
                rows = connection.execute("SELECT payload FROM raw_evidence_artifacts_v2 ORDER BY created_at DESC").fetchall()
        return [RawEvidenceArtifact.model_validate_json(row["payload"]) for row in rows]
    def save_feature_snapshot_v2(self, snapshot: FeatureSnapshotV2) -> FeatureSnapshotV2:
        with self._connection() as connection:
            existing = connection.execute("SELECT payload FROM feature_snapshots_v2 WHERE id = ?", (snapshot.id,)).fetchone()
            if existing:
                return FeatureSnapshotV2.model_validate_json(existing["payload"])
            connection.execute(
                "INSERT INTO feature_snapshots_v2 VALUES (?, ?, ?, ?, ?)",
                (snapshot.id, snapshot.address, snapshot.chain.value, json.dumps(snapshot.model_dump(mode="json"), default=_json_default, sort_keys=True), snapshot.created_at.isoformat()),
            )
        return snapshot

    def get_feature_snapshot_v2(self, snapshot_id: str) -> FeatureSnapshotV2 | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM feature_snapshots_v2 WHERE id = ?", (snapshot_id,)).fetchone()
        return FeatureSnapshotV2.model_validate_json(row["payload"]) if row else None

    def list_feature_snapshots_v2(self) -> list[FeatureSnapshotV2]:
        with self._connection() as connection:
            rows = connection.execute("SELECT payload FROM feature_snapshots_v2 ORDER BY created_at DESC").fetchall()
        return [FeatureSnapshotV2.model_validate_json(row["payload"]) for row in rows]

    def save_training_dataset_v2(self, dataset: TrainingDatasetV2) -> TrainingDatasetV2:
        with self._connection() as connection:
            existing = connection.execute("SELECT payload FROM training_datasets_v2 WHERE id = ?", (dataset.id,)).fetchone()
            if existing:
                return TrainingDatasetV2.model_validate_json(existing["payload"])
            connection.execute("INSERT INTO training_datasets_v2 VALUES (?, ?, ?)", (dataset.id, json.dumps(dataset.model_dump(mode="json"), default=_json_default, sort_keys=True), dataset.created_at.isoformat()))
        return dataset

    def get_training_dataset_v2(self, dataset_id: str) -> TrainingDatasetV2 | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM training_datasets_v2 WHERE id = ?", (dataset_id,)).fetchone()
        return TrainingDatasetV2.model_validate_json(row["payload"]) if row else None

    def save_model_version_v2(self, model: ModelVersionV2) -> ModelVersionV2:
        with self._connection() as connection:
            existing = connection.execute("SELECT payload FROM model_versions_v2 WHERE id = ?", (model.id,)).fetchone()
            if existing:
                return ModelVersionV2.model_validate_json(existing["payload"])
            connection.execute(
                "INSERT INTO model_versions_v2 VALUES (?, ?, ?, ?, ?)",
                (model.id, model.model_name, model.version, json.dumps(model.model_dump(mode="json"), default=_json_default, sort_keys=True), model.trained_at.isoformat()),
            )
        return model

    def get_model_version_v2(self, model_id: str) -> ModelVersionV2 | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM model_versions_v2 WHERE id = ?", (model_id,)).fetchone()
        return ModelVersionV2.model_validate_json(row["payload"]) if row else None

    def save_model_inference_v2(self, inference: ModelInferenceV2) -> ModelInferenceV2:
        with self._connection() as connection:
            existing = connection.execute("SELECT payload FROM model_inferences_v2 WHERE id = ?", (inference.id,)).fetchone()
            if existing:
                return ModelInferenceV2.model_validate_json(existing["payload"])
            connection.execute(
                "INSERT INTO model_inferences_v2 VALUES (?, ?, ?, ?, ?)",
                (inference.id, inference.model_version_id, inference.feature_snapshot_id, json.dumps(inference.model_dump(mode="json"), default=_json_default, sort_keys=True), inference.created_at.isoformat()),
            )
        return inference

    def get_model_inference_v2(self, inference_id: str) -> ModelInferenceV2 | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM model_inferences_v2 WHERE id = ?", (inference_id,)).fetchone()
        return ModelInferenceV2.model_validate_json(row["payload"]) if row else None

    def save_bridge_route_v2(self, route: BridgeRouteV2) -> BridgeRouteV2:
        with self._connection() as connection:
            existing = connection.execute("SELECT payload FROM bridge_routes_v2 WHERE id = ?", (route.id,)).fetchone()
            if existing:
                return BridgeRouteV2.model_validate_json(existing["payload"])
            connection.execute(
                "INSERT INTO bridge_routes_v2 VALUES (?, ?, ?, ?, ?, ?, ?)",
                (route.id, route.bridge_entity_id, route.protocol, route.source_chain.value, route.destination_chain.value,
                 json.dumps(route.model_dump(mode="json"), default=_json_default, sort_keys=True), route.created_at.isoformat()),
            )
        return route

    def get_bridge_route_v2(self, route_id: str) -> BridgeRouteV2 | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM bridge_routes_v2 WHERE id = ?", (route_id,)).fetchone()
        return BridgeRouteV2.model_validate_json(row["payload"]) if row else None

    def list_bridge_routes_v2(self) -> list[BridgeRouteV2]:
        with self._connection() as connection:
            rows = connection.execute("SELECT payload FROM bridge_routes_v2 ORDER BY created_at DESC").fetchall()
        return [BridgeRouteV2.model_validate_json(row["payload"]) for row in rows]

    def save_cross_chain_link_v2(self, link: CrossChainLinkV2) -> CrossChainLinkV2:
        with self._connection() as connection:
            existing = connection.execute("SELECT payload FROM cross_chain_links_v2 WHERE id = ?", (link.id,)).fetchone()
            if existing:
                return CrossChainLinkV2.model_validate_json(existing["payload"])
            connection.execute(
                "INSERT INTO cross_chain_links_v2 VALUES (?, ?, ?, ?, ?)",
                (link.id, link.route_id, link.status.value,
                 json.dumps(link.model_dump(mode="json"), default=_json_default, sort_keys=True), link.created_at.isoformat()),
            )
        return link

    def get_cross_chain_link_v2(self, link_id: str) -> CrossChainLinkV2 | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM cross_chain_links_v2 WHERE id = ?", (link_id,)).fetchone()
        return CrossChainLinkV2.model_validate_json(row["payload"]) if row else None

    def list_cross_chain_links_v2(self, route_id: str | None = None) -> list[CrossChainLinkV2]:
        with self._connection() as connection:
            if route_id:
                rows = connection.execute("SELECT payload FROM cross_chain_links_v2 WHERE route_id = ? ORDER BY created_at DESC", (route_id,)).fetchall()
            else:
                rows = connection.execute("SELECT payload FROM cross_chain_links_v2 ORDER BY created_at DESC").fetchall()
        return [CrossChainLinkV2.model_validate_json(row["payload"]) for row in rows]
    def list_entity_address_assertions_for_entity(self, entity_id: str, chain: str) -> list[EntityAddressAssertion]:
        with self._connection() as connection:
            rows = connection.execute("SELECT payload FROM entity_address_assertions WHERE entity_id = ? AND chain = ? ORDER BY created_at DESC", (entity_id, chain)).fetchall()
        return [EntityAddressAssertion.model_validate_json(row["payload"]) for row in rows]
    def update_investigation_case_v2_status(self, case_id: str, status: str) -> InvestigationCaseV2 | None:
        case = self.get_investigation_case_v2(case_id)
        if not case:
            return None
        updated = case.model_copy(update={"status": status})
        with self._connection() as connection:
            connection.execute("UPDATE investigation_cases_v2 SET payload = ? WHERE id = ?", (json.dumps(updated.model_dump(mode="json"), default=_json_default, sort_keys=True), case_id))
        return updated

    def next_investigation_result_version(self, case_id: str) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT COALESCE(MAX(version), 0) AS latest FROM investigation_results_v2 WHERE case_id = ?", (case_id,)).fetchone()
        return int(row["latest"]) + 1

    def get_investigation_result_by_fingerprint_v2(self, case_id: str, trace_fingerprint: str) -> InvestigationResultV2 | None:
        return next((item for item in self.list_investigation_results_v2(case_id) if item.trace_fingerprint == trace_fingerprint), None)
    def save_investigation_result_v2(self, result: InvestigationResultV2) -> InvestigationResultV2:
        serialized = json.dumps(result.model_dump(mode="json"), default=_json_default, sort_keys=True)
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO investigation_results_v2 VALUES (?, ?, ?, ?, ?)",
                (result.id, result.case_id, result.version, serialized, result.generated_at.isoformat()),
            )
        return result

    def get_investigation_result_v2(self, result_id: str) -> InvestigationResultV2 | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM investigation_results_v2 WHERE id = ?", (result_id,)).fetchone()
        return InvestigationResultV2.model_validate_json(row["payload"]) if row else None

    def list_investigation_results_v2(self, case_id: str) -> list[InvestigationResultV2]:
        with self._connection() as connection:
            rows = connection.execute("SELECT payload FROM investigation_results_v2 WHERE case_id = ? ORDER BY version DESC", (case_id,)).fetchall()
        return [InvestigationResultV2.model_validate_json(row["payload"]) for row in rows]

    def save_request_draft_v2(self, draft: RequestDraftV2) -> RequestDraftV2:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO request_drafts_v2 VALUES (?, ?, ?, ?, ?)",
                (draft.id, draft.case_id, draft.result_id, json.dumps(draft.model_dump(mode="json"), default=_json_default, sort_keys=True), draft.created_at.isoformat()),
            )
        return draft

    def get_request_draft_v2(self, draft_id: str) -> RequestDraftV2 | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM request_drafts_v2 WHERE id = ?", (draft_id,)).fetchone()
        return RequestDraftV2.model_validate_json(row["payload"]) if row else None

    def review_entity_address_assertion_v2(self, assertion_id: str, reviewer: str, review_state: AssertionReviewState, rationale: str) -> EntityAddressAssertion | None:
        review_state = AssertionReviewState(review_state)
        if review_state not in {AssertionReviewState.REVIEWED, AssertionReviewState.REJECTED}:
            raise ValueError("Only REVIEWED or REJECTED are valid human review decisions.")
        original = self.get_entity_address_assertion(assertion_id)
        if original is None:
            return None
        updated = original.model_copy(update={"review_state": review_state})
        event = AssertionReviewEventV2(id=f"ASSERTREV-{uuid.uuid4().hex[:12].upper()}", assertion_id=assertion_id, reviewer=reviewer, review_state=review_state, rationale=rationale, created_at=_utcnow())
        with self._connection() as connection:
            connection.execute("UPDATE entity_address_assertions SET payload = ? WHERE id = ?", (json.dumps(updated.model_dump(mode="json"), default=_json_default, sort_keys=True), assertion_id))
            connection.execute("INSERT INTO assertion_reviews_v2 VALUES (?, ?, ?, ?)", (event.id, assertion_id, json.dumps(event.model_dump(mode="json"), default=_json_default, sort_keys=True), event.created_at.isoformat()))
        return updated

    def list_entity_address_assertion_reviews_v2(self, assertion_id: str) -> list[AssertionReviewEventV2]:
        with self._connection() as connection:
            rows = connection.execute("SELECT payload FROM assertion_reviews_v2 WHERE assertion_id = ? ORDER BY created_at ASC", (assertion_id,)).fetchall()
        return [AssertionReviewEventV2.model_validate_json(row["payload"]) for row in rows]
    def get_entity_address_assertion(self, assertion_id: str) -> EntityAddressAssertion | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM entity_address_assertions WHERE id = ?", (assertion_id,)).fetchone()
        return EntityAddressAssertion.model_validate_json(row["payload"]) if row else None
    def create_intelligence_source(self, payload: IntelligenceSourceCreate) -> IntelligenceSource:
        created_at = _utcnow()
        source = IntelligenceSource(id=f"SOURCE-{uuid.uuid4().hex[:12].upper()}", created_at=created_at, **payload.model_dump())
        with self._connection() as connection:
            connection.execute("INSERT INTO intelligence_sources VALUES (?, ?, ?)", (source.id, json.dumps(source.model_dump(mode="json"), default=_json_default, sort_keys=True), created_at.isoformat()))
        return source

    def get_intelligence_source(self, source_id: str) -> IntelligenceSource | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM intelligence_sources WHERE id = ?", (source_id,)).fetchone()
        return IntelligenceSource.model_validate_json(row["payload"]) if row else None

    def list_intelligence_sources(self) -> list[IntelligenceSource]:
        with self._connection() as connection:
            rows = connection.execute("SELECT payload FROM intelligence_sources ORDER BY created_at DESC").fetchall()
        return [IntelligenceSource.model_validate_json(row["payload"]) for row in rows]

    def create_entity(self, payload: EntityCreate) -> Entity:
        created_at = _utcnow()
        entity = Entity(id=f"ENTITY-{uuid.uuid4().hex[:12].upper()}", created_at=created_at, **payload.model_dump())
        with self._connection() as connection:
            connection.execute("INSERT INTO entities VALUES (?, ?, ?, ?)", (entity.id, entity.canonical_name, json.dumps(entity.model_dump(mode="json"), default=_json_default, sort_keys=True), created_at.isoformat()))
        return entity

    def get_entity(self, entity_id: str) -> Entity | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM entities WHERE id = ?", (entity_id,)).fetchone()
        return Entity.model_validate_json(row["payload"]) if row else None

    def find_entity(self, canonical_name: str, entity_type: EntityType) -> Entity | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM entities WHERE canonical_name = ? ORDER BY created_at ASC", (canonical_name,)).fetchone()
        if not row:
            return None
        entity = Entity.model_validate_json(row["payload"])
        return entity if entity.entity_type == entity_type else None

    def create_entity_address_assertion(self, payload: EntityAddressAssertionCreate) -> EntityAddressAssertion:
        if not self.get_entity(payload.entity_id):
            raise ValueError("Referenced entity does not exist.")
        if not self.get_intelligence_source(payload.source_id):
            raise ValueError("Referenced intelligence source does not exist.")
        created_at = _utcnow()
        evidence_hash = canonical_sha256({"entity_id": payload.entity_id, "address": payload.address, "chain": payload.chain.value, "role": payload.role.value, "assertion_type": payload.assertion_type.value, "source_id": payload.source_id, "first_verified_at": payload.first_verified_at, "last_verified_at": payload.last_verified_at, "stale_after": payload.stale_after, "evidence_score": payload.evidence_score, "evidence_components": payload.evidence_components, "notes": payload.notes, "risk_tags": sorted(payload.risk_tags)})
        with self._connection() as connection:
            duplicate = connection.execute("SELECT payload FROM entity_address_assertions WHERE address = ? AND chain = ? AND entity_id = ? AND source_id = ? AND role = ? AND assertion_type = ?", (payload.address, payload.chain.value, payload.entity_id, payload.source_id, payload.role.value, payload.assertion_type.value)).fetchone()
            if duplicate:
                return EntityAddressAssertion.model_validate_json(duplicate["payload"])
            assertion = EntityAddressAssertion(id=f"ASSERT-{uuid.uuid4().hex[:12].upper()}", evidence_hash_sha256=evidence_hash, created_at=created_at, **payload.model_dump())
            connection.execute("INSERT INTO entity_address_assertions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (assertion.id, assertion.address, assertion.chain.value, assertion.entity_id, assertion.source_id, assertion.role.value, assertion.assertion_type.value, json.dumps(assertion.model_dump(mode="json"), default=_json_default, sort_keys=True), created_at.isoformat()))
        return assertion

    def list_entity_address_assertions(self, address: str, chain: str) -> list[EntityAddressAssertion]:
        normalized = self._normalized_address(address, chain)
        with self._connection() as connection:
            rows = connection.execute("SELECT payload FROM entity_address_assertions WHERE address = ? AND chain = ? ORDER BY created_at DESC", (normalized, chain)).fetchall()
        return [EntityAddressAssertion.model_validate_json(row["payload"]) for row in rows]

    def resolve_entity_assertions(self, address: str, chain: str, at: datetime | None = None) -> list[ResolvedEntityAssertion]:
        observed_at = at or _utcnow()
        resolved: list[ResolvedEntityAssertion] = []
        for assertion in self.list_entity_address_assertions(address, chain):
            entity = self.get_entity(assertion.entity_id)
            source = self.get_intelligence_source(assertion.source_id)
            if not entity or not source or assertion.review_state == AssertionReviewState.REJECTED:
                continue
            effective_state = assertion.review_state
            warnings: list[str] = []
            if assertion.stale_after and assertion.stale_after <= observed_at:
                effective_state = AssertionReviewState.STALE
                warnings.append("STALE_ENTITY_LABEL")
            resolved.append(ResolvedEntityAssertion(assertion=assertion, entity=entity, source=source, effective_review_state=effective_state, warnings=warnings))
        return resolved

    def migrate_legacy_labels_to_assertions(self) -> dict[str, int]:
        """Create v2 records from v1 labels without mutating their original evidence."""
        migrated = 0
        skipped = 0
        for label in self.list_labels():
            existing = [item for item in self.list_entity_address_assertions(label.address, label.chain.value) if item.notes and f"legacy_label_id={label.id}" in item.notes]
            if existing:
                skipped += 1
                continue
            entity_type = {"vasp": EntityType.VASP, "bridge": EntityType.BRIDGE, "mixer": EntityType.MIXER, "swap": EntityType.DEX}[label.entity_kind]
            role = {"hot_wallet": EntityRole.VASP_HOT_WALLET, "deposit_address": EntityRole.VASP_DEPOSIT, "cluster": EntityRole.VASP_COLLECTOR, "bridge_contract": EntityRole.BRIDGE_CONTRACT, "mixer": EntityRole.MIXER, "swap_service": EntityRole.DEX_ROUTER}[label.label_type]
            source = self.create_intelligence_source(IntelligenceSourceCreate(name=label.source.source_name, source_type=IntelligenceSourceType.REVIEWED_PUBLIC_DATASET, source_uri=label.source.url, trust_tier=TrustTier.B, retrieved_at=label.source.observed_at, notes=f"Migrated from legacy label {label.id}."))
            entity = self.find_entity(label.vasp_name, entity_type) or self.create_entity(EntityCreate(canonical_name=label.vasp_name, entity_type=entity_type))
            state = AssertionReviewState.REVIEWED if label.review_status == "APPROVED" else AssertionReviewState.REJECTED
            assertion_type = AssertionType.VERIFIED if label.confidence == "verified" else AssertionType.RULE_INFERRED
            self.create_entity_address_assertion(EntityAddressAssertionCreate(entity_id=entity.id, address=label.address, chain=label.chain, role=role, assertion_type=assertion_type, source_id=source.id, review_state=state, last_verified_at=label.source.observed_at, stale_after=label.expires_at, notes=f"legacy_label_id={label.id}; reviewer={label.reviewer}", risk_tags=[]))
            migrated += 1
        return {"migrated": migrated, "skipped": skipped}
    def save_deposit_inference(self, inference: DepositInferenceResult) -> DepositInferenceResult:
        with self._connection() as connection:
            existing = connection.execute("SELECT payload FROM deposit_inferences WHERE id = ?", (inference.id,)).fetchone()
            if existing:
                return DepositInferenceResult.model_validate_json(existing["payload"])
            connection.execute("INSERT INTO deposit_inferences VALUES (?, ?, ?)", (inference.id, json.dumps(inference.model_dump(mode="json"), default=_json_default, sort_keys=True), inference.created_at.isoformat()))
        return inference

    def get_deposit_inference(self, inference_id: str) -> DepositInferenceResult | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM deposit_inferences WHERE id = ?", (inference_id,)).fetchone()
        return DepositInferenceResult.model_validate_json(row["payload"]) if row else None
    def update_case(self, case_id: str, update: CaseUpdate) -> CaseSummary | None:
        case = self.get_case(case_id)
        if not case:
            return None
        changes = update.model_dump(exclude_unset=True)
        # A blank notes value is permitted only when explicitly supplied.
        updated = case.model_copy(update=changes)
        with self._connection() as connection:
            connection.execute("UPDATE cases SET payload = ? WHERE id = ?", (json.dumps(updated.model_dump(mode="json")), case_id))
        return updated

    def add_case_note(self, case_id: str, author: str, note: str) -> CaseNote:
        event = CaseNote(id=f"NOTE-{uuid.uuid4().hex[:12].upper()}", case_id=case_id, author=author, note=note, created_at=_utcnow())
        with self._connection() as connection:
            connection.execute("INSERT INTO case_notes VALUES (?, ?, ?, ?, ?)", (event.id, event.case_id, event.author, event.note, event.created_at.isoformat()))
        return event

    def list_case_notes(self, case_id: str) -> list[CaseNote]:
        with self._connection() as connection:
            rows = connection.execute("SELECT id, case_id, author, note, created_at FROM case_notes WHERE case_id = ? ORDER BY created_at ASC", (case_id,)).fetchall()
        return [CaseNote.model_validate(dict(row)) for row in rows]

    def add_label(self, payload: VaspLabelCreate) -> VaspLabel:
        created_at = _utcnow()
        normalized = self._normalized_address(payload.address, payload.chain.value)
        existing = self.labels_for_address(normalized, payload.chain.value)
        conflicting = any(item.review_status == "APPROVED" and item.vasp_name != payload.vasp_name for item in existing)
        label = VaspLabel(id=f"LABEL-{uuid.uuid4().hex[:12].upper()}", created_at=created_at, review_status="CONFLICT" if conflicting else "APPROVED", **{**payload.model_dump(), "address": normalized})
        serialized = json.dumps(label.model_dump(mode="json"), default=_json_default, sort_keys=True)
        with self._connection() as connection:
            connection.execute("INSERT INTO labels VALUES (?, ?, ?, ?, ?)", (label.id, label.address, label.chain.value, serialized, created_at.isoformat()))
        return label

    def find_label(self, address: str, chain: str) -> VaspLabel | None:
        labels = self.labels_for_address(address, chain)
        if any(item.review_status == "CONFLICT" for item in labels):
            return None
        now = _utcnow()
        return next((item for item in labels if item.review_status == "APPROVED" and (item.expires_at is None or item.expires_at > now)), None)

    def labels_for_address(self, address: str, chain: str) -> list[VaspLabel]:
        address = self._normalized_address(address, chain)
        with self._connection() as connection:
            rows = connection.execute("SELECT payload FROM labels WHERE address = ? AND chain = ? ORDER BY created_at DESC", (address, chain)).fetchall()
        return [VaspLabel.model_validate_json(row["payload"]) for row in rows]

    def list_labels(self, chain: str | None = None) -> list[VaspLabel]:
        with self._connection() as connection:
            if chain:
                rows = connection.execute("SELECT payload FROM labels WHERE chain = ? ORDER BY created_at DESC", (chain,)).fetchall()
            else:
                rows = connection.execute("SELECT payload FROM labels ORDER BY created_at DESC").fetchall()
        return [VaspLabel.model_validate_json(row["payload"]) for row in rows]

    def review_label(self, label_id: str, reviewer: str, review: LabelReview) -> VaspLabel | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM labels WHERE id = ?", (label_id,)).fetchone()
            if not row:
                return None
            original = VaspLabel.model_validate_json(row["payload"])
            updated = original.model_copy(update={"review_status": review.status})
            connection.execute("UPDATE labels SET payload = ? WHERE id = ?", (json.dumps(updated.model_dump(mode="json"), default=_json_default, sort_keys=True), label_id))
            event = LabelReviewEvent(label_id=label_id, reviewer=reviewer, status=review.status, rationale=review.rationale, created_at=_utcnow())
            connection.execute("INSERT INTO label_reviews VALUES (?, ?, ?, ?, ?, ?)", (f"REVIEW-{uuid.uuid4().hex[:12].upper()}", event.label_id, event.reviewer, event.status, event.rationale, event.created_at.isoformat()))
        return updated

    def label_review_history(self, label_id: str) -> list[LabelReviewEvent]:
        with self._connection() as connection:
            rows = connection.execute("SELECT label_id, reviewer, status, rationale, created_at FROM label_reviews WHERE label_id = ? ORDER BY created_at ASC", (label_id,)).fetchall()
        return [LabelReviewEvent.model_validate(dict(row)) for row in rows]

    def save_run(self, run_id: str, case_id: str, payload: dict[str, Any], created_at: datetime) -> None:
        serialized = json.dumps(payload, default=_json_default, sort_keys=True, separators=(",", ":"))
        with self._connection() as connection:
            connection.execute("INSERT INTO trace_runs VALUES (?, ?, ?, ?)", (run_id, case_id, serialized, created_at.isoformat()))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM trace_runs WHERE id = ?", (run_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_runs(self, exclude_case_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT payload FROM trace_runs"
        params: tuple[Any, ...] = ()
        if exclude_case_id:
            query += " WHERE case_id != ?"
            params = (exclude_case_id,)
        query += " ORDER BY created_at DESC"
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def record_audit(self, actor: str, action: str, resource: str, detail: dict[str, Any] | None = None) -> None:
        created_at = _utcnow()
        with self._connection() as connection:
            connection.execute("INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?)", (
                f"AUDIT-{uuid.uuid4().hex[:12].upper()}", actor, action, resource,
                json.dumps(detail or {}, default=_json_default, sort_keys=True), created_at.isoformat(),
            ))

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute("SELECT id, actor, action, resource, detail, created_at FROM audit_events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(row), "detail": json.loads(row["detail"])} for row in rows]

    @staticmethod
    def _normalized_address(address: str, chain: str) -> str:
        return address.lower() if chain in {"ETHEREUM", "BNB_CHAIN", "POLYGON"} else address