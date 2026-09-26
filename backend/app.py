from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import settings
from .capabilities import ChainCapabilityV2, capability_matrix
from .adapters import LegacyExplorerAdapter
from .investigation_v2 import InvestigationRunnerV2
from .imports_v2 import parse_recorded_transfers_csv
from .intelligence_imports import import_entity_assertions_csv
from .demo import DemoScenarioService
from .entity_resolution import EntityResolver
from .cross_chain_v2 import (
    BridgeRouteCreateV2,
    BridgeRouteV2,
    CrossChainContinuationRequestV2,
    CrossChainContinuationV2,
    CrossChainLinkV2,
    CrossChainResolveRequestV2,
    CrossChainResolverV2,
    new_bridge_route,
)
from .v2_demo import V2DemoScenarioService
from .bridge_events import (
    BridgeEventExtractionRequestV2,
    BridgeEventResolveRequestV2,
    BridgeEventV2,
    NormalizedBridgeEventExtractorV2,
)
from .domain import (
    CaseCreateV2,
    CaseStatusUpdateV2,
    InvestigationTraceRequestV2,
    RecordedTraceImportV2,
    RecordedTraceCsvImportV2,
    EntityRelationship,
    EntityRelationshipCreate,
    EntityAssertionCsvImportV2,
    AssertionReviewV2,
    AssertionReviewEventV2,
    RawEvidenceArtifact,
    Entity,
    EntityAddressAssertion,
    EntityAddressAssertionCreate,
    EntityCreate,
    IntelligenceSource,
    IntelligenceSourceCreate,
    FeatureSnapshotV2,
    MLDatasetBuildRequest,
    MLFeatureSnapshotRequest,
    MLInferenceRequest,
    MLPairAssociationRequest,
    ModelInferenceV2,
    ModelVersionV2,
    MLRoleTrainingRequest,
    TrainingDatasetV2,
    InvestigationCaseV2,
    InvestigationResultV2,
    RequestDraftV2,
    ResolvedEntityAssertion,
)
from .ml_v2 import (
    MLInferenceAdapter,
    ModelEvaluation,
    SoftmaxLogisticRoleBaseline,
    TrainingDatasetBuilder,
    VaspPairAssociationBaseline,
    WalletFeatureExtractor,
    register_pair_association_baseline,
    register_trained_role_model,
)
from .jobs import TraceJobs
from .jobs_v2 import PersistentTraceJobsV2
from .models import CaseCreate, CaseNote, CaseNoteCreate, CaseSummary, CaseUpdate, ChallengeRequest, ChallengeResult, LabelImportResult, LabelReview, LabelReviewEvent, SahyogDraft, TraceRequest, TraceResult, VaspCandidate, VaspLabel, VaspLabelCreate
from .reports import InvestigationReport
from .reports_v2 import InvestigationResultReportV2
from .request_export_v2 import GenericSahyogDraftExporter
from .sahyog import SahyogDraftService
from .security import require_role, security_middleware
from .storage import Store
from .tracing import TraceService
from .tron import ProviderUnavailable


store = Store()
trace_service = TraceService(store)
trace_jobs = TraceJobs()
v2_trace_jobs = PersistentTraceJobsV2(store)
report_renderer = InvestigationReport()
v2_report_renderer = InvestigationResultReportV2()
v2_request_exporter = GenericSahyogDraftExporter()
sahyog_drafts = SahyogDraftService()


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.migrate_legacy_labels_to_assertions()
    yield


app = FastAPI(
    title="VASP Trace API",
    version="0.1.0",
    lifespan=lifespan,
    description="Evidence-first tracing service. A VASP is reported only when a receiving address has sourced registry evidence.",
)
app.middleware("http")(security_middleware)


def audit(request: Request, action: str, resource: str, detail: dict | None = None) -> None:
    store.record_audit(getattr(request.state, "actor", "system"), action, resource, detail)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "vasp-trace-api",
        "live_sources": {"trongrid": bool(settings.trongrid_api_key), "etherscan": bool(settings.etherscan_api_key)},
        "supported_chains": [chain for chain in ("TRON", "ETHEREUM", "BNB_CHAIN", "POLYGON") if any(item.chain.value == chain and item.transfers == "FULL" for item in capability_matrix())],
        "planned_chain_adapters": [item.chain.value for item in capability_matrix() if item.transfers == "NOT_IMPLEMENTED"],
    }


@app.get("/v2/capabilities", response_model=list[ChainCapabilityV2])
def get_capability_matrix_v2() -> list[ChainCapabilityV2]:
    """Declare actual adapter maturity; no unsupported chain is advertised as traceable."""
    return capability_matrix()


@app.post("/demo/scenarios/multihop-deposit-sweep")
def load_multihop_demo(request: Request) -> dict:
    """Load an explicitly simulated multi-hop scenario for presentation and training."""
    case, result = DemoScenarioService(store).create_multihop_deposit_sweep()
    audit(request, "SIMULATED_DEMO_LOADED", result.run_id, {"case_id": case.id, "scenario": "multihop_deposit_sweep"})
    return {"case": case, "trace": result}


@app.post("/demo/scenarios/v2-deposit-inference")
async def load_v2_deposit_inference_demo(request: Request) -> dict:
    """Load the v2 synthetic evidence fixture for offline demonstration only."""
    result = await V2DemoScenarioService(store).create_deposit_inference()
    audit(request, "SYNTHETIC_V2_DEMO_LOADED", result["case"].id, {"scenario": "v2_deposit_inference"})
    return result

@app.post("/cases", response_model=CaseSummary, status_code=status.HTTP_201_CREATED)
def create_case(payload: CaseCreate, request: Request) -> CaseSummary:
    if payload.incident_start and payload.incident_end and payload.incident_end < payload.incident_start:
        raise HTTPException(status_code=422, detail="incident_end must be later than incident_start")
    case = store.create_case(payload)
    audit(request, "CASE_CREATED", case.id)
    return case


@app.get("/cases", response_model=list[CaseSummary])
def list_cases() -> list[CaseSummary]:
    return store.list_cases()


@app.post("/v2/cases", response_model=InvestigationCaseV2, status_code=status.HTTP_201_CREATED)
def create_investigation_case_v2(payload: CaseCreateV2, request: Request) -> InvestigationCaseV2:
    """Create a v2 case without changing the legacy wallet-case contract."""
    case = store.create_investigation_case_v2(payload, getattr(request.state, "actor", "local-development"))
    audit(request, "CASE_V2_CREATED", case.id, {"seed_type": case.context.seed_type.value, "data_mode": case.context.data_mode.value})
    return case


@app.post("/v2/imports/recorded-trace", response_model=InvestigationResultV2, status_code=status.HTTP_201_CREATED)
async def import_recorded_trace_v2(payload: RecordedTraceImportV2, request: Request) -> InvestigationResultV2:
    """Create and replay an evidence package without making a provider request."""
    require_role(request, "investigator", "supervisor", "admin")
    case = store.create_investigation_case_v2(payload.case, getattr(request.state, "actor", "local-development"))
    try:
        result = await InvestigationRunnerV2(store, _v2_explorer_adapter).run(case, payload.trace)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit(request, "RECORDED_TRACE_IMPORTED", result.id, {"case_id": case.id, "transfer_count": len(payload.trace.recorded_transfers), "data_mode": result.data_mode.value})
    return result

@app.post("/v2/imports/recorded-trace/csv", response_model=InvestigationResultV2, status_code=status.HTTP_201_CREATED)
async def import_recorded_trace_csv_v2(payload: RecordedTraceCsvImportV2, request: Request) -> InvestigationResultV2:
    require_role(request, "investigator", "supervisor", "admin")
    try:
        transfers = parse_recorded_transfers_csv(payload.transfers_csv, payload.case)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    case = store.create_investigation_case_v2(payload.case, getattr(request.state, "actor", "local-development"))
    trace_payload = InvestigationTraceRequestV2(recorded_transfers=transfers, recorded_evidence=payload.recorded_evidence)
    result = await InvestigationRunnerV2(store, _v2_explorer_adapter).run(case, trace_payload)
    audit(request, "RECORDED_TRACE_CSV_IMPORTED", result.id, {"case_id": case.id, "transfer_count": len(transfers), "data_mode": result.data_mode.value})
    return result

@app.get("/v2/cases", response_model=list[InvestigationCaseV2])
def list_investigation_cases_v2() -> list[InvestigationCaseV2]:
    return store.list_investigation_cases_v2()


@app.get("/v2/cases/{case_id}", response_model=InvestigationCaseV2)
def get_investigation_case_v2(case_id: str) -> InvestigationCaseV2:
    case = store.get_investigation_case_v2(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="V2 investigation case not found")
    return case
@app.patch("/v2/cases/{case_id}/status", response_model=InvestigationCaseV2)
def update_investigation_case_v2_status(case_id: str, payload: CaseStatusUpdateV2, request: Request) -> InvestigationCaseV2:
    case = store.update_investigation_case_v2_status(case_id, payload.status)
    if not case:
        raise HTTPException(status_code=404, detail="V2 investigation case not found")
    audit(request, "CASE_V2_STATUS_UPDATED", case_id, {"status": case.status})
    return case


def _v2_explorer_adapter(chain):
    clients = {
        "TRON": trace_service.tron,
        "ETHEREUM": trace_service.ethereum,
        "BNB_CHAIN": trace_service.bnb,
        "POLYGON": trace_service.polygon,
    }
    client = clients.get(chain.value)
    if client is None:
        raise ValueError(f"No v2 explorer adapter is implemented for {chain.value}.")
    return LegacyExplorerAdapter(chain, client)


@app.post("/v2/cases/{case_id}/trace", response_model=InvestigationResultV2, status_code=status.HTTP_201_CREATED)
async def trace_investigation_case_v2(case_id: str, payload: InvestigationTraceRequestV2, request: Request) -> InvestigationResultV2:
    require_role(request, "investigator", "supervisor", "admin")
    case = store.get_investigation_case_v2(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="V2 investigation case not found")
    try:
        result = await InvestigationRunnerV2(store, _v2_explorer_adapter).run(case, payload)
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit(request, "V2_TRACE_COMPLETED", result.id, {"case_id": case_id, "version": result.version, "data_mode": result.data_mode.value, "manifest_sha256": result.evidence_manifest.sha256})
    return result

@app.post("/v2/cases/{case_id}/trace-jobs", status_code=status.HTTP_202_ACCEPTED)
async def start_v2_trace_job(case_id: str, payload: InvestigationTraceRequestV2, request: Request) -> dict:
    require_role(request, "investigator", "supervisor", "admin")
    case = store.get_investigation_case_v2(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="V2 investigation case not found")
    job = PersistentTraceJobsV2(store).submit(case.id, payload.model_dump(mode="json"), lambda: InvestigationRunnerV2(store, _v2_explorer_adapter).run(case, payload))
    audit(request, "V2_TRACE_JOB_CREATED", job["job_id"], {"case_id": case_id})
    return job


@app.post("/v2/trace-jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_v2_trace_job(job_id: str, request: Request) -> dict:
    require_role(request, "investigator", "supervisor", "admin")
    existing = store.get_v2_trace_job(job_id)
    if not existing:
        raise HTTPException(status_code=404, detail="V2 trace job not found")
    case = store.get_investigation_case_v2(existing.get("case_id", ""))
    if not case:
        raise HTTPException(status_code=422, detail="The trace job's source case is no longer available.")
    try:
        payload = InvestigationTraceRequestV2.model_validate(existing.get("trace_request"))
        job = PersistentTraceJobsV2(store).retry(job_id, lambda: InvestigationRunnerV2(store, _v2_explorer_adapter).run(case, payload))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not job:
        raise HTTPException(status_code=404, detail="V2 trace job not found")
    audit(request, "V2_TRACE_JOB_RETRIED", job_id, {"case_id": case.id, "attempt": job["attempt"]})
    return job

@app.get("/v2/trace-jobs/{job_id}")
def get_v2_trace_job(job_id: str) -> dict:
    job = store.get_v2_trace_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="V2 trace job not found")
    return job

@app.get("/v2/cases/{case_id}/results", response_model=list[InvestigationResultV2])
def list_investigation_results_v2(case_id: str) -> list[InvestigationResultV2]:
    if not store.get_investigation_case_v2(case_id):
        raise HTTPException(status_code=404, detail="V2 investigation case not found")
    return store.list_investigation_results_v2(case_id)


@app.post("/v2/bridges/routes", response_model=BridgeRouteV2, status_code=status.HTTP_201_CREATED)
def create_bridge_route_v2(payload: BridgeRouteCreateV2, request: Request) -> BridgeRouteV2:
    require_role(request, "label_reviewer", "supervisor", "admin")
    entity = store.get_entity(payload.bridge_entity_id)
    if entity is None or entity.entity_type.value != "BRIDGE":
        raise HTTPException(status_code=422, detail="bridge_entity_id must reference a registered BRIDGE entity.")
    route = store.save_bridge_route_v2(new_bridge_route(payload, datetime.now(timezone.utc)))
    audit(request, "BRIDGE_ROUTE_REGISTERED", route.id, {"protocol": route.protocol, "source_chain": route.source_chain.value, "destination_chain": route.destination_chain.value, "review_state": route.review_state.value})
    return route


@app.get("/v2/bridges/routes", response_model=list[BridgeRouteV2])
def list_bridge_routes_v2() -> list[BridgeRouteV2]:
    return store.list_bridge_routes_v2()


@app.post("/v2/bridges/events/extract", response_model=BridgeEventV2, status_code=status.HTTP_201_CREATED)
def extract_bridge_event_v2(payload: BridgeEventExtractionRequestV2, request: Request) -> BridgeEventV2:
    """Persist an exact bridge-message event decoded by an evidence collector."""
    require_role(request, "investigator", "supervisor", "admin")
    artifact = store.get_raw_evidence_artifact_v2(payload.raw_evidence_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Raw evidence artifact not found")
    try:
        event = NormalizedBridgeEventExtractorV2().extract(artifact, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    saved = store.save_bridge_event_v2(event)
    audit(request, "BRIDGE_EVENT_EXTRACTED", saved.id, {
        "protocol": saved.protocol, "direction": saved.direction.value,
        "raw_evidence_id": saved.raw_evidence_id,
    })
    return saved


@app.get("/v2/bridges/events", response_model=list[BridgeEventV2])
def list_bridge_events_v2(protocol: str | None = None, message_id: str | None = None) -> list[BridgeEventV2]:
    return store.list_bridge_events_v2(protocol=protocol, message_id=message_id)


@app.get("/v2/bridges/events/{event_id}", response_model=BridgeEventV2)
def get_bridge_event_v2(event_id: str) -> BridgeEventV2:
    event = store.get_bridge_event_v2(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Bridge event not found")
    return event


@app.post("/v2/cross-chain/links/resolve-events", response_model=CrossChainLinkV2, status_code=status.HTTP_201_CREATED)
def resolve_cross_chain_events_v2(payload: BridgeEventResolveRequestV2, request: Request) -> CrossChainLinkV2:
    """Resolve persisted source and destination protocol events with one exact message ID."""
    require_role(request, "investigator", "supervisor", "admin")
    source = store.get_bridge_event_v2(payload.source_event_id)
    destination = store.get_bridge_event_v2(payload.destination_event_id)
    if not source or not destination:
        raise HTTPException(status_code=404, detail="Source or destination bridge event not found")
    if source.direction.value != "SOURCE" or destination.direction.value != "DESTINATION":
        raise HTTPException(status_code=422, detail="Events must be SOURCE then DESTINATION.")
    if source.protocol.casefold() != destination.protocol.casefold():
        raise HTTPException(status_code=422, detail="Bridge event protocols do not match.")
    if source.message_id != destination.message_id:
        raise HTTPException(status_code=422, detail="Bridge event message identifiers do not match.")
    try:
        link = CrossChainResolverV2(store).resolve(CrossChainResolveRequestV2(
            route_id=payload.route_id,
            source_transfer=source.transfer,
            destination_transfer=destination.transfer,
            message_id=source.message_id,
            source_event_evidence_id=source.raw_evidence_id,
            destination_event_evidence_id=destination.raw_evidence_id,
        ), datetime.now(timezone.utc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    saved = store.save_cross_chain_link_v2(link)
    audit(request, "CROSS_CHAIN_EVENTS_VERIFIED", saved.id, {
        "route_id": saved.route_id, "source_event_id": source.id,
        "destination_event_id": destination.id, "message_id": saved.message_id,
    })
    return saved

@app.post("/v2/cross-chain/links/resolve", response_model=CrossChainLinkV2, status_code=status.HTTP_201_CREATED)
def resolve_cross_chain_link_v2(payload: CrossChainResolveRequestV2, request: Request) -> CrossChainLinkV2:
    require_role(request, "investigator", "supervisor", "admin")
    try:
        link = CrossChainResolverV2(store).resolve(payload, datetime.now(timezone.utc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    saved = store.save_cross_chain_link_v2(link)
    audit(request, "CROSS_CHAIN_LINK_VERIFIED", saved.id, {"route_id": saved.route_id, "protocol": saved.protocol, "message_id": saved.message_id})
    return saved


@app.get("/v2/cross-chain/links", response_model=list[CrossChainLinkV2])
def list_cross_chain_links_v2(route_id: str | None = None) -> list[CrossChainLinkV2]:
    return store.list_cross_chain_links_v2(route_id)


@app.get("/v2/cross-chain/links/{link_id}", response_model=CrossChainLinkV2)
def get_cross_chain_link_v2(link_id: str) -> CrossChainLinkV2:
    link = store.get_cross_chain_link_v2(link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Cross-chain link not found")
    return link


@app.post("/v2/cross-chain/links/{link_id}/continuations", response_model=CrossChainContinuationV2)
def create_cross_chain_continuation_v2(link_id: str, payload: CrossChainContinuationRequestV2, request: Request) -> CrossChainContinuationV2:
    require_role(request, "investigator", "supervisor", "admin")
    link = store.get_cross_chain_link_v2(link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Cross-chain link not found")
    try:
        continuation = CrossChainResolverV2(store).continuation(link, payload.source_allocation_id, payload.source_attributed_amount)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit(request, "CROSS_CHAIN_CONTINUATION_CREATED", link_id, {"source_allocation_id": payload.source_allocation_id, "destination_amount": str(continuation.destination_attributed_amount)})
    return continuation


@app.post("/v2/ml/feature-snapshots", response_model=FeatureSnapshotV2, status_code=status.HTTP_201_CREATED)
def create_ml_feature_snapshot(payload: MLFeatureSnapshotRequest, request: Request) -> FeatureSnapshotV2:
    require_role(request, "investigator", "supervisor", "admin")
    snapshot = WalletFeatureExtractor(EntityResolver(store)).build(payload.address, payload.asset, payload.transfers, payload.snapshot_time, lookback_hours=payload.lookback_hours)
    saved = store.save_feature_snapshot_v2(snapshot)
    audit(request, "ML_FEATURE_SNAPSHOT_CREATED", saved.id, {"feature_schema_version": saved.feature_schema_version, "evidence_count": len(saved.evidence_ids)})
    return saved


@app.get("/v2/ml/feature-snapshots/{snapshot_id}", response_model=FeatureSnapshotV2)
def get_ml_feature_snapshot(snapshot_id: str) -> FeatureSnapshotV2:
    snapshot = store.get_feature_snapshot_v2(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="ML feature snapshot not found")
    return snapshot


@app.post("/v2/ml/datasets/build", response_model=TrainingDatasetV2, status_code=status.HTTP_201_CREATED)
def build_ml_training_dataset(payload: MLDatasetBuildRequest, request: Request) -> TrainingDatasetV2:
    require_role(request, "label_reviewer", "supervisor", "admin")
    snapshots: list[FeatureSnapshotV2] = []
    missing: list[str] = []
    for snapshot_id in payload.feature_snapshot_ids:
        snapshot = store.get_feature_snapshot_v2(snapshot_id)
        if snapshot:
            snapshots.append(snapshot)
        else:
            missing.append(snapshot_id)
    if missing:
        raise HTTPException(status_code=404, detail={"message": "Feature snapshots not found", "ids": missing})
    dataset = TrainingDatasetBuilder(store, EntityResolver(store)).build(snapshots)
    saved = store.save_training_dataset_v2(dataset)
    audit(request, "ML_DATASET_BUILT", saved.id, {"reviewed_rows": saved.reviewed_row_count, "weak_rows": saved.weak_row_count, "excluded_unlabeled": saved.excluded_unlabeled_count})
    return saved


@app.get("/v2/ml/datasets/{dataset_id}", response_model=TrainingDatasetV2)
def get_ml_training_dataset(dataset_id: str) -> TrainingDatasetV2:
    dataset = store.get_training_dataset_v2(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="ML training dataset not found")
    return dataset


@app.post("/v2/ml/models/role-classifier/train", response_model=ModelVersionV2, status_code=status.HTTP_201_CREATED)
def train_ml_role_classifier(payload: MLRoleTrainingRequest, request: Request) -> ModelVersionV2:
    require_role(request, "supervisor", "admin")
    dataset = store.get_training_dataset_v2(payload.dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="ML training dataset not found")
    snapshots = {row.feature_snapshot_id: store.get_feature_snapshot_v2(row.feature_snapshot_id) for row in dataset.rows}
    if any(item is None for item in snapshots.values()):
        raise HTTPException(status_code=409, detail="The dataset references a missing feature snapshot.")
    classifier = SoftmaxLogisticRoleBaseline().train(dataset.rows, snapshots)
    reviewed_rows = [row for row in dataset.rows if row.label_tier.value == "REVIEWED_GROUND_TRUTH"]
    metrics = ModelEvaluation.evaluate(classifier, reviewed_rows, snapshots)
    metrics["evaluation_scope"] = "training-only diagnostic; temporal and entity-holdout metrics must be recorded before operational activation"
    model = register_trained_role_model(store, dataset, classifier, metrics, enabled=False)
    audit(request, "ML_ROLE_MODEL_REGISTERED", model.id, {"dataset": dataset.id, "artifact_sha256": model.artifact_sha256, "enabled": False})
    return model


@app.get("/v2/ml/models/{model_id}", response_model=ModelVersionV2)
def get_ml_model_version(model_id: str) -> ModelVersionV2:
    model = store.get_model_version_v2(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="ML model version not found")
    return model


@app.post("/v2/ml/models/{model_id}/inferences", response_model=ModelInferenceV2, status_code=status.HTTP_201_CREATED)
def infer_ml_role(model_id: str, payload: MLInferenceRequest, request: Request) -> ModelInferenceV2:
    require_role(request, "investigator", "supervisor", "admin")
    model = store.get_model_version_v2(model_id)
    snapshot = store.get_feature_snapshot_v2(payload.feature_snapshot_id)
    if not model:
        raise HTTPException(status_code=404, detail="ML model version not found")
    if not snapshot:
        raise HTTPException(status_code=404, detail="ML feature snapshot not found")
    try:
        inference = MLInferenceAdapter(model, enabled=settings.ml_enabled, strong_threshold=settings.ml_role_strong_threshold, weak_threshold=settings.ml_role_weak_threshold).infer(snapshot)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    saved = store.save_model_inference_v2(inference)
    audit(request, "ML_INFERENCE_RECORDED", saved.id, {"model_version_id": model.id, "status": saved.status.value, "assertion_type": "ML_INFERRED"})
    return saved


@app.post("/v2/ml/pair-associations", response_model=ModelInferenceV2, status_code=status.HTTP_201_CREATED)
def infer_vasp_pair_association(payload: MLPairAssociationRequest, request: Request) -> ModelInferenceV2:
    require_role(request, "investigator", "supervisor", "admin")
    model = register_pair_association_baseline(store)
    if not settings.ml_enabled:
        raise HTTPException(status_code=409, detail="ML inference is disabled by configuration. Set ML_ENABLED only after validation and authorized review.")
    baseline = VaspPairAssociationBaseline(store)
    pair = baseline.features(payload.address, payload.candidate_entity_id, payload.asset, payload.transfers, payload.snapshot_time)
    inference = baseline.infer(pair, model.id)
    saved = store.save_model_inference_v2(inference)
    audit(request, "ML_PAIR_ASSOCIATION_RECORDED", saved.id, {"model_version_id": model.id, "status": saved.status.value, "assertion_type": "ML_INFERRED"})
    return saved

@app.get("/v2/results/{result_id}", response_model=InvestigationResultV2)
def get_investigation_result_v2(result_id: str) -> InvestigationResultV2:
    result = store.get_investigation_result_v2(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="V2 investigation result not found")
    return result


@app.get("/v2/results/{result_id}/evidence-manifest")
def get_investigation_result_manifest_v2(result_id: str) -> dict:
    result = store.get_investigation_result_v2(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="V2 investigation result not found")
    return result.evidence_manifest.model_dump(mode="json")


@app.get("/v2/results/{result_id}/report.pdf")
def investigation_result_report_v2(result_id: str, request: Request) -> Response:
    result = store.get_investigation_result_v2(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="V2 investigation result not found")
    case = store.get_investigation_case_v2(result.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="V2 investigation case not found")
    report = v2_report_renderer.render(case, result)
    audit(request, "V2_REPORT_EXPORTED", result.id, {"manifest_sha256": result.evidence_manifest.sha256})
    return Response(content=report, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{result.id}-investigation-report.pdf"'})


@app.post("/v2/results/{result_id}/request-drafts", response_model=RequestDraftV2, status_code=status.HTTP_201_CREATED)
def create_request_draft_v2(result_id: str, request: Request, candidate_id: str | None = None, request_purpose: str = "Request preservation, KYC, and relevant transaction records under authorized process.", investigator_notes: str = "") -> RequestDraftV2:
    require_role(request, "investigator", "supervisor", "admin")
    result = store.get_investigation_result_v2(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="V2 investigation result not found")
    case = store.get_investigation_case_v2(result.case_id)
    if not case:
        raise HTTPException(status_code=404, detail="V2 investigation case not found")
    try:
        draft = v2_request_exporter.build_draft(case, result, candidate_id, request_purpose, investigator_notes)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    store.save_request_draft_v2(draft)
    audit(request, "LOCAL_REQUEST_DRAFT_V2_CREATED", draft.id, {"result_id": result.id, "manifest_sha256": result.evidence_manifest.sha256})
    return draft


@app.get("/v2/request-drafts/{draft_id}", response_model=RequestDraftV2)
def get_request_draft_v2(draft_id: str) -> RequestDraftV2:
    draft = store.get_request_draft_v2(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Local request draft not found")
    return draft

@app.get("/cases/{case_id}", response_model=CaseSummary)
def get_case(case_id: str) -> CaseSummary:
    case = store.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@app.patch("/cases/{case_id}", response_model=CaseSummary)
def update_case(case_id: str, payload: CaseUpdate, request: Request) -> CaseSummary:
    case = store.update_case(case_id, payload)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    audit(request, "CASE_UPDATED", case_id, payload.model_dump(exclude_unset=True))
    return case


@app.post("/cases/{case_id}/notes", response_model=CaseNote, status_code=status.HTTP_201_CREATED)
def add_case_note(case_id: str, payload: CaseNoteCreate, request: Request) -> CaseNote:
    if not store.get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    note = store.add_case_note(case_id, getattr(request.state, "actor", "local-development"), payload.note)
    audit(request, "CASE_NOTE_ADDED", note.id, {"case_id": case_id})
    return note


@app.get("/cases/{case_id}/notes", response_model=list[CaseNote])
def list_case_notes(case_id: str) -> list[CaseNote]:
    if not store.get_case(case_id):
        raise HTTPException(status_code=404, detail="Case not found")
    return store.list_case_notes(case_id)


@app.post("/labels", response_model=VaspLabel, status_code=status.HTTP_201_CREATED)
def create_vasp_label(payload: VaspLabelCreate, request: Request) -> VaspLabel:
    require_role(request, "label_reviewer", "supervisor", "admin")
    if payload.chain.value == "TRON" and not (payload.address.startswith("T") and len(payload.address) == 34):
        raise HTTPException(status_code=422, detail="TRON label address must be a 34-character Base58 address beginning with T")
    if payload.chain.value in {"ETHEREUM", "BNB_CHAIN", "POLYGON"} and not (payload.address.startswith("0x") and len(payload.address) == 42):
        raise HTTPException(status_code=422, detail="EVM label address must be a 42-character address beginning with 0x")
    label = store.add_label(payload)
    audit(request, "LABEL_CREATED", label.id, {"entity_kind": label.entity_kind, "chain": label.chain.value})
    return label


@app.get("/labels", response_model=list[VaspLabel])
def list_vasp_labels(chain: str | None = None) -> list[VaspLabel]:
    return store.list_labels(chain)


@app.post("/labels/import", response_model=LabelImportResult, status_code=status.HTTP_201_CREATED)
def import_vasp_labels(payload: list[VaspLabelCreate], request: Request) -> LabelImportResult:
    require_role(request, "label_reviewer", "supervisor", "admin")
    imported: list[VaspLabel] = []
    rejected: list[str] = []
    for index, candidate in enumerate(payload):
        if candidate.chain.value == "TRON" and not (candidate.address.startswith("T") and len(candidate.address) == 34):
            rejected.append(f"Item {index}: invalid TRON address")
            continue
        if candidate.chain.value in {"ETHEREUM", "BNB_CHAIN", "POLYGON"} and not (candidate.address.startswith("0x") and len(candidate.address) == 42):
            rejected.append(f"Item {index}: invalid EVM address")
            continue
        imported.append(store.add_label(candidate))
    audit(request, "LABELS_IMPORTED", "labels", {"imported": len(imported), "rejected": len(rejected)})
    return LabelImportResult(imported=imported, rejected=rejected)


@app.post("/v2/intelligence/sources", response_model=IntelligenceSource, status_code=status.HTTP_201_CREATED)
def create_intelligence_source(payload: IntelligenceSourceCreate, request: Request) -> IntelligenceSource:
    require_role(request, "label_reviewer", "supervisor", "admin")
    source = store.create_intelligence_source(payload)
    audit(request, "INTELLIGENCE_SOURCE_CREATED", source.id, {"source_type": source.source_type.value, "trust_tier": source.trust_tier.value})
    return source


@app.post("/v2/intelligence/entities", response_model=Entity, status_code=status.HTTP_201_CREATED)
def create_entity(payload: EntityCreate, request: Request) -> Entity:
    require_role(request, "label_reviewer", "supervisor", "admin")
    entity = store.create_entity(payload)
    audit(request, "ENTITY_CREATED", entity.id, {"entity_type": entity.entity_type.value})
    return entity


@app.post("/v2/intelligence/import/assertions/csv")
def import_entity_assertions_csv_v2(payload: EntityAssertionCsvImportV2, request: Request) -> dict:
    require_role(request, "label_reviewer", "supervisor", "admin")
    try:
        outcome = import_entity_assertions_csv(store, payload.csv_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit(request, "ENTITY_ASSERTIONS_CSV_IMPORTED", "entity_address_assertions", {"imported": outcome["imported"], "rejected": len(outcome["rejected"])})
    return outcome

@app.post("/v2/intelligence/relationships", response_model=EntityRelationship, status_code=status.HTTP_201_CREATED)
def create_entity_relationship_v2(payload: EntityRelationshipCreate, request: Request) -> EntityRelationship:
    require_role(request, "label_reviewer", "supervisor", "admin")
    try:
        relationship = store.create_entity_relationship_v2(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit(request, "ENTITY_RELATIONSHIP_CREATED", relationship.id, {"relationship_type": relationship.relationship_type.value})
    return relationship


@app.get("/v2/intelligence/relationships", response_model=list[EntityRelationship])
def list_entity_relationships_v2(entity_id: str | None = None) -> list[EntityRelationship]:
    return store.list_entity_relationships_v2(entity_id)

@app.post("/v2/intelligence/assertions", response_model=EntityAddressAssertion, status_code=status.HTTP_201_CREATED)
def create_entity_address_assertion(payload: EntityAddressAssertionCreate, request: Request) -> EntityAddressAssertion:
    require_role(request, "label_reviewer", "supervisor", "admin")
    try:
        assertion = store.create_entity_address_assertion(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit(request, "ENTITY_ASSERTION_CREATED", assertion.id, {"entity_id": assertion.entity_id, "assertion_type": assertion.assertion_type.value})
    return assertion


@app.post("/v2/intelligence/assertions/{assertion_id}/reviews", response_model=EntityAddressAssertion)
def review_entity_address_assertion_v2(assertion_id: str, payload: AssertionReviewV2, request: Request) -> EntityAddressAssertion:
    require_role(request, "label_reviewer", "supervisor", "admin")
    try:
        assertion = store.review_entity_address_assertion_v2(assertion_id, getattr(request.state, "actor", "local-development"), payload.review_state, payload.rationale)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not assertion:
        raise HTTPException(status_code=404, detail="Entity assertion not found")
    audit(request, "ENTITY_ASSERTION_REVIEWED", assertion_id, {"review_state": payload.review_state})
    return assertion


@app.get("/v2/intelligence/assertions/{assertion_id}/reviews", response_model=list[AssertionReviewEventV2])
def list_entity_address_assertion_reviews_v2(assertion_id: str) -> list[AssertionReviewEventV2]:
    if not store.get_entity_address_assertion(assertion_id):
        raise HTTPException(status_code=404, detail="Entity assertion not found")
    return store.list_entity_address_assertion_reviews_v2(assertion_id)


@app.get("/v2/evidence/{artifact_id}", response_model=RawEvidenceArtifact)
def get_raw_evidence_artifact_v2(artifact_id: str) -> RawEvidenceArtifact:
    artifact = store.get_raw_evidence_artifact_v2(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Raw evidence artifact not found")
    return artifact

@app.get("/v2/intelligence/assertions", response_model=list[ResolvedEntityAssertion])
def resolve_entity_assertions(address: str, chain: str) -> list[ResolvedEntityAssertion]:
    return store.resolve_entity_assertions(address, chain)


@app.post("/v2/intelligence/migrations/legacy-labels")
def migrate_legacy_labels(request: Request) -> dict[str, int]:
    require_role(request, "label_reviewer", "supervisor", "admin")
    outcome = store.migrate_legacy_labels_to_assertions()
    audit(request, "LEGACY_LABELS_MIGRATED", "entity_address_assertions", outcome)
    return outcome
@app.get("/labels/{label_id}/reviews", response_model=list[LabelReviewEvent])
def label_reviews(label_id: str) -> list[LabelReviewEvent]:
    return store.label_review_history(label_id)


@app.post("/labels/{label_id}/review", response_model=VaspLabel)
def review_label(label_id: str, payload: LabelReview, request: Request) -> VaspLabel:
    require_role(request, "label_reviewer", "supervisor", "admin")
    label = store.review_label(label_id, getattr(request.state, "actor", "local-development"), payload)
    if not label:
        raise HTTPException(status_code=404, detail="Label not found")
    audit(request, "LABEL_REVIEWED", label_id, {"status": payload.status})
    return label


@app.post("/cases/{case_id}/trace", response_model=TraceResult)
async def trace_case(case_id: str, request: TraceRequest, http_request: Request) -> TraceResult:
    case = store.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        result = await trace_service.trace_case(case, request)
        audit(http_request, "TRACE_COMPLETED", result.run_id, {"case_id": case_id, "status": result.status})
        return result
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/trace-runs/{run_id}")
def get_trace_run(run_id: str) -> dict:
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Trace run not found")
    return run


@app.post("/cases/{case_id}/trace-jobs", status_code=status.HTTP_202_ACCEPTED)
async def start_trace_job(case_id: str, request: TraceRequest, http_request: Request) -> dict:
    case = store.get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    job = trace_jobs.submit(lambda: trace_service.trace_case(case, request))
    audit(http_request, "TRACE_JOB_CREATED", job["job_id"], {"case_id": case_id})
    return job


@app.get("/trace-jobs/{job_id}")
def get_trace_job(job_id: str) -> dict:
    job = trace_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trace job not found")
    return job


@app.get("/trace-runs/{run_id}/evidence-package")
def evidence_package(run_id: str) -> dict:
    """Return the original trace record with its limitations and manifest hash intact."""
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Trace run not found")
    case = store.get_case(run["case_id"])
    return {
        "package_type": "VASP_TRACE_EVIDENCE_PACKAGE",
        "version": "0.1.0",
        "case": case.model_dump(mode="json") if case else None,
        "trace": run,
        "handling_note": "This technical package records public-chain observations and sourced labels. It requires investigator review and lawful process before any external request.",
    }


@app.get("/trace-runs/{run_id}/verify")
def verify_trace_manifest(run_id: str) -> dict:
    """Verify integrity of the original saved manifest; this does not validate upstream data truth."""
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Trace run not found")
    payload = run.get("manifest_payload")
    if not payload:
        return {"run_id": run_id, "verified": False, "reason": "This older run does not contain a saved manifest payload."}
    computed = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "run_id": run_id,
        "verified": computed == run.get("manifest_sha256"),
        "expected_hash": run.get("manifest_sha256"),
        "computed_hash": computed,
        "scope": "Integrity of the saved trace manifest only; it does not independently validate provider or label accuracy.",
    }


@app.get("/trace-runs/{run_id}/report.pdf")
def investigation_report(run_id: str, request: Request) -> Response:
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Trace run not found")
    case = store.get_case(run["case_id"])
    if not case:
        raise HTTPException(status_code=404, detail="Case record not found")
    report = report_renderer.render(case, TraceResult.model_validate(run))
    audit(request, "REPORT_EXPORTED", run_id)
    return Response(content=report, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{run_id}-investigation-report.pdf"'})


@app.post("/trace-runs/{run_id}/sahyog-drafts", response_model=SahyogDraft, status_code=status.HTTP_201_CREATED)
def create_sahyog_draft(run_id: str, request: Request, candidate_rank: int = 1) -> SahyogDraft:
    require_role(request, "investigator", "supervisor", "admin")
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Trace run not found")
    case = store.get_case(run["case_id"])
    if not case:
        raise HTTPException(status_code=404, detail="Case record not found")
    try:
        draft = sahyog_drafts.create(case, TraceResult.model_validate(run), candidate_rank)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(request, "SAHYOG_DRAFT_CREATED", draft.draft_id, {"run_id": run_id, "target": draft.vasp_name})
    return draft


@app.get("/audit-events")
def audit_events(limit: int = 100) -> list[dict]:
    return store.list_audit(max(1, min(limit, 500)))


frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=frontend_dir / "static"), name="static")


@app.get("/", include_in_schema=False)
def investigator_dashboard() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")


@app.post("/trace-runs/{run_id}/challenge", response_model=ChallengeResult)
def challenge_attribution(run_id: str, payload: ChallengeRequest) -> ChallengeResult:
    """Recalculate the attribution after excluding one asserted piece of evidence.

    This intentionally makes no new ownership claim: it tells an investigator how
    dependent the current conclusion is on a particular label or transaction.
    """
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Trace run not found")
    baseline = [VaspCandidate.model_validate(candidate) for candidate in run.get("candidates", [])]
    if payload.evidence_type == "label":
        remaining = [candidate for candidate in baseline if candidate.label_id != payload.evidence_id]
        affected = len(remaining) != len(baseline)
        explanation = ("The challenged VASP label was excluded. Remaining candidates retain their separate sourced labels."
                       if affected else "The supplied label identifier did not support a candidate in this trace.")
    else:
        remaining = [candidate for candidate in baseline if candidate.supporting_transaction.lower() != payload.evidence_id.lower()]
        affected = len(remaining) != len(baseline)
        explanation = ("Candidates whose observed receipt depends on the challenged transaction were excluded."
                       if affected else "The supplied transaction hash did not support a candidate in this trace.")
    conclusion = "STILL_SUPPORTED" if remaining else "NOW_UNRESOLVED"
    if not remaining and affected:
        explanation += " Without that evidence, no supported VASP candidate remains within the examined trace scope."
    return ChallengeResult(run_id=run_id, evidence_type=payload.evidence_type, evidence_id=payload.evidence_id,
                           baseline_candidates=baseline, remaining_candidates=remaining, conclusion=conclusion, explanation=explanation)
