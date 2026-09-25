from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.canonical import canonical_sha256
from backend.results_v2 import InvestigationResultService
from backend.storage import Store
from backend.tracing import TraceService


client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def isolated_phase8_store(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "phase8.db"))
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "trace_service", TraceService(store))


def _demo_snapshot():
    response = client.post("/demo/scenarios/v2-deposit-inference")
    assert response.status_code == 200
    return response.json()


def test_v2_result_snapshot_manifest_and_pdf_agree():
    payload = _demo_snapshot()
    result = payload["result"]
    result_id = result["id"]
    manifest_response = client.get(f"/v2/results/{result_id}/evidence-manifest")
    assert manifest_response.status_code == 200
    manifest = manifest_response.json()
    body = {key: manifest[key] for key in ("case_id", "result_version", "generated_at", "algorithm_versions", "evidence")}
    assert manifest["sha256"] == canonical_sha256(body)
    assert result["attribution"]["candidates"][0]["evidence_ids"]
    assert any(item["id"].startswith("transfer:") for item in manifest["evidence"])
    pdf_response = client.get(f"/v2/results/{result_id}/report.pdf")
    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"].startswith("application/pdf")
    assert pdf_response.content.startswith(b"%PDF")


def test_synthetic_result_cannot_create_operational_request_draft():
    result_id = _demo_snapshot()["result"]["id"]
    response = client.post(f"/v2/results/{result_id}/request-drafts")
    assert response.status_code == 409
    assert "Synthetic results" in response.json()["detail"]


def test_reviewed_recorded_result_creates_local_draft_from_same_snapshot():
    demo = _demo_snapshot()
    source = app_module.store.get_investigation_result_v2(demo["result"]["id"])
    assert source is not None
    created = client.post("/v2/cases", json={
        "title": "Recorded evidence export test",
        "context": {
            "seed_type": "transaction",
            "chain": "ETHEREUM",
            "seed_tx_hash": "0x" + "9" * 64,
            "asset": {"chain": "ETHEREUM", "symbol": "USDT", "contract_address": "0x" + "8" * 40, "decimals": 6},
            "disputed_amount": "5000",
            "incident_time": "2026-09-20T09:00:00Z",
            "data_mode": "RECORDED_REAL",
        },
    })
    assert created.status_code == 201
    case_id = created.json()["id"]
    status_response = client.patch(f"/v2/cases/{case_id}/status", json={"status": "UNDER_REVIEW"})
    assert status_response.status_code == 200
    case = app_module.store.get_investigation_case_v2(case_id)
    snapshot = InvestigationResultService(app_module.store).create(
        case, source.flow, source.attribution, source.transfers, source.deposit_inferences,
        ["Recorded fixture for export-route testing only."], datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc),
    )
    draft_response = client.post(f"/v2/results/{snapshot.id}/request-drafts", params={"investigator_notes": "Check statutory basis before submission."})
    assert draft_response.status_code == 201
    draft = draft_response.json()
    candidate = snapshot.attribution.candidates[0]
    assert draft["result_id"] == snapshot.id
    assert draft["attributed_amount"] == str(candidate.attributed_amount)
    assert draft["evidence_manifest_sha256"] == snapshot.evidence_manifest.sha256
    assert draft["evidence_ids"] == candidate.evidence_ids
    assert draft["relevant_transfer_ids"]
    assert "LOCAL EXPORT ONLY" in draft["boundary_notice"]
    retrieved = client.get(f"/v2/request-drafts/{draft['id']}")
    assert retrieved.status_code == 200
    assert retrieved.json()["id"] == draft["id"]