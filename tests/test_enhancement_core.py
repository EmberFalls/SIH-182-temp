"""Integration coverage for the evidence-integrity and case-network additions."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

import backend.app as app_module
from backend.domain import AssetRef, CaseAnnotationCreateV2, CaseContextV2, CaseCreateV2, DataMode, SeedType
from backend.models import Chain
from backend.results_v2 import InvestigationResultService
from backend.jobs_v2 import PersistentTraceJobsV2
from backend.storage import Store
from backend.tracing import TraceService
from backend.v2_demo import V2DemoScenarioService


def test_annotation_and_audit_chain_are_append_only_and_verifiable(tmp_path):
    store = Store(str(tmp_path / "evidence.db"))
    case = store.create_investigation_case_v2(CaseCreateV2(
        title="Annotation case",
        context=CaseContextV2(seed_type=SeedType.WALLET_CONTEXT, chain=Chain.ETHEREUM,
                              asset=AssetRef(chain=Chain.ETHEREUM, symbol="USDT", contract_address="0x" + "a" * 40, decimals=6),
                              disputed_amount="1", incident_time=datetime(2026, 9, 28, tzinfo=timezone.utc),
                              seed_wallet="0x" + "b" * 40, data_mode=DataMode.RECORDED_REAL),
    ), "investigator-a")
    annotation = store.create_case_annotation_v2(case.id, "investigator-a", CaseAnnotationCreateV2(target_type="WALLET", target_id="0x" + "b" * 40, note_type="FOLLOW_UP", body="Request the next provider page."))
    assert store.list_case_annotations_v2(case.id)[0].id == annotation.id
    store.record_audit("investigator-a", "CASE_ANNOTATION_CREATED", annotation.id, {"case_id": case.id})
    store.record_audit("investigator-a", "TRACE_POLICY_VIEWED", case.id, {})
    valid, warnings = store.verify_audit_chain_v2()
    assert valid is True
    assert warnings == []


def test_saved_results_create_exact_cross_case_connections(tmp_path):
    store = Store(str(tmp_path / "connections.db"))
    first = __import__("asyncio").run(V2DemoScenarioService(store).create_deposit_inference())
    source = first["result"]
    case = store.create_investigation_case_v2(CaseCreateV2(
        title="Recorded overlap",
        context=CaseContextV2(seed_type=SeedType.TRANSACTION, chain=Chain.ETHEREUM,
                              asset=source.transfers[0].asset, disputed_amount=source.flow.seed_amount,
                              incident_time=source.flow.seed_timestamp, seed_tx_hash="0x" + "9" * 64,
                              data_mode=DataMode.RECORDED_REAL),
    ), "investigator-b")
    second = InvestigationResultService(store).create(case, source.flow, source.attribution, source.transfers, source.deposit_inferences, ["Recorded fixture overlap."], generated_at=datetime(2026, 9, 28, tzinfo=timezone.utc))
    links = store.list_case_connections_v2(second.case_id)
    assert links
    assert any(link.connection_type.value == "SAME_ADDRESS" for link in links)
    assert all(link.related_case_id == source.case_id or link.source_case_id == source.case_id for link in links)


def test_integrity_endpoint_and_evidence_bundle(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "api-evidence.db"))
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "trace_service", TraceService(store))
    client = TestClient(app_module.app)
    loaded = client.post("/demo/scenarios/v2-deposit-inference")
    assert loaded.status_code == 200
    result_id = loaded.json()["result"]["id"]
    integrity = client.get(f"/v2/results/{result_id}/integrity")
    assert integrity.status_code == 200
    assert integrity.json()["result_snapshot_valid"] is True
    assert integrity.json()["manifest_valid"] is True
    assert integrity.json()["audit_chain_valid"] is True
    bundle = client.get(f"/v2/results/{result_id}/evidence-bundle.zip")
    assert bundle.status_code == 200
    assert bundle.headers["content-type"].startswith("application/zip")
    assert bundle.content[:2] == b"PK"


def test_queued_trace_job_can_be_cancelled_without_claiming_completion(tmp_path):
    store = Store(str(tmp_path / "jobs.db"))
    job = {"job_id": "V2JOB-CANCEL", "status": "QUEUED", "created_at": datetime.now(timezone.utc).isoformat(), "case_id": "CASEV2-TEST", "trace_request": {}, "result_id": None, "attempt": 1, "progress_events": [], "cancellation_requested": False}
    store.save_v2_trace_job(job)
    cancelled = PersistentTraceJobsV2(store).cancel(job["job_id"])
    assert cancelled is not None
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["result_id"] is None
    assert cancelled["cancellation_requested"] is True
