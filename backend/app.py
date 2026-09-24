from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import settings
from .demo import DemoScenarioService
from .jobs import TraceJobs
from .models import CaseCreate, CaseNote, CaseNoteCreate, CaseSummary, CaseUpdate, ChallengeRequest, ChallengeResult, LabelImportResult, LabelReview, LabelReviewEvent, SahyogDraft, TraceRequest, TraceResult, VaspCandidate, VaspLabel, VaspLabelCreate
from .reports import InvestigationReport
from .sahyog import SahyogDraftService
from .security import require_role, security_middleware
from .storage import Store
from .tracing import TraceService
from .tron import ProviderUnavailable


store = Store()
trace_service = TraceService(store)
trace_jobs = TraceJobs()
report_renderer = InvestigationReport()
sahyog_drafts = SahyogDraftService()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="VASP Trace API", version="0.1.0", lifespan=lifespan,
              description="Evidence-first tracing service. A VASP is reported only when a receiving address has sourced registry evidence.")
app.middleware("http")(security_middleware)


def audit(request: Request, action: str, resource: str, detail: dict | None = None) -> None:
    store.record_audit(getattr(request.state, "actor", "system"), action, resource, detail)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "vasp-trace-api", "live_sources": {"trongrid": bool(settings.trongrid_api_key), "etherscan": bool(settings.etherscan_api_key)}, "supported_chains": ["TRON", "ETHEREUM", "BNB_CHAIN", "POLYGON"], "planned_chain_adapters": ["BITCOIN", "SOLANA"]}


@app.post("/demo/scenarios/multihop-deposit-sweep")
def load_multihop_demo(request: Request) -> dict:
    """Load an explicitly simulated multi-hop scenario for presentation and training."""
    case, result = DemoScenarioService(store).create_multihop_deposit_sweep()
    audit(request, "SIMULATED_DEMO_LOADED", result.run_id, {"case_id": case.id, "scenario": "multihop_deposit_sweep"})
    return {"case": case, "trace": result}


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
