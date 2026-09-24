import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.storage import Store
from backend.tracing import TraceService


client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def isolated_api_store(tmp_path, monkeypatch):
    """Keep API tests from writing synthetic cases into the development database."""
    test_store = Store(str(tmp_path / "api.db"))
    monkeypatch.setattr(app_module, "store", test_store)
    monkeypatch.setattr(app_module, "trace_service", TraceService(test_store))


def test_health_reports_tron_capability():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["supported_chains"] == ["TRON", "ETHEREUM", "BNB_CHAIN", "POLYGON"]


def test_dashboard_is_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "VASP TRACE" in response.text


def test_case_creation_and_retrieval():
    payload = {"title": "TRON USDT fraud", "suspect_wallet": "T" + "A" * 33, "token_symbol": "usdt"}
    created = client.post("/cases", json=payload)
    assert created.status_code == 201
    case = created.json()
    assert case["token_symbol"] == "USDT"
    found = client.get(f"/cases/{case['id']}")
    assert found.status_code == 200
    assert found.json()["suspect_wallet"] == payload["suspect_wallet"]


def test_ethereum_case_is_accepted():
    response = client.post("/cases", json={"title": "ERC20 fraud", "suspect_wallet": "0x" + "a" * 40, "chain": "ETHEREUM"})
    assert response.status_code == 201
    assert response.json()["chain"] == "ETHEREUM"


def test_label_requires_a_source_record():
    payload = {
        "address": "T" + "B" * 33,
        "chain": "TRON",
        "vasp_name": "Example Exchange",
        "label_type": "hot_wallet",
        "confidence": "verified",
        "reviewer": "Analyst One",
        "source": {"url": "https://example.org/label", "source_name": "Verified explorer label", "observed_at": "2026-09-24T00:00:00Z"},
    }
    response = client.post("/labels", json=payload)
    assert response.status_code == 201
    assert response.json()["source"]["source_name"] == "Verified explorer label"


def test_case_notes_and_status_are_persisted():
    created = client.post("/cases", json={"title": "Workflow case", "suspect_wallet": "T" + "D" * 33}).json()
    updated = client.patch(f"/cases/{created['id']}", json={"case_status": "UNDER_REVIEW"})
    assert updated.status_code == 200
    assert updated.json()["case_status"] == "UNDER_REVIEW"
    note = client.post(f"/cases/{created['id']}/notes", json={"note": "Initial trace reviewed."})
    assert note.status_code == 201
    assert client.get(f"/cases/{created['id']}/notes").json()[0]["note"] == "Initial trace reviewed."
