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


def test_v2_transaction_seed_case_is_persisted_with_data_mode():
    payload = {
        "title": "Transaction seeded fraud flow",
        "external_case_ref": "FIR/V2/001",
        "trace_policy_id": "v2-proportional-haircut",
        "context": {
            "seed_type": "transaction",
            "chain": "ETHEREUM",
            "seed_tx_hash": "0x" + "a" * 64,
            "asset": {"chain": "ETHEREUM", "symbol": "USDT", "contract_address": "0x" + "b" * 40, "decimals": 6},
            "disputed_amount": "12500.50",
            "incident_time": "2026-09-25T10:30:00Z",
            "data_mode": "RECORDED_REAL",
        },
    }
    created = client.post("/v2/cases", json=payload)
    assert created.status_code == 201
    body = created.json()
    assert body["id"].startswith("CASEV2-")
    assert body["context"]["seed_type"] == "transaction"
    assert body["context"]["data_mode"] == "RECORDED_REAL"
    assert body["context"]["asset"]["symbol"] == "USDT"
    found = client.get(f"/v2/cases/{body['id']}")
    assert found.status_code == 200
    assert found.json()["external_case_ref"] == "FIR/V2/001"


def test_v2_wallet_context_case_requires_a_wallet():
    response = client.post("/v2/cases", json={
        "title": "Incomplete v2 case",
        "context": {
            "seed_type": "wallet_context",
            "chain": "TRON",
            "asset": {"chain": "TRON", "symbol": "USDT", "contract_address": "TR7", "decimals": 6},
            "disputed_amount": "1",
            "incident_time": "2026-09-25T10:30:00Z",
        },
    })
    assert response.status_code == 422

def test_v2_intelligence_registry_api_creates_and_resolves_assertion():
    source = client.post("/v2/intelligence/sources", json={
        "name": "Published VASP evidence",
        "source_type": "VASP_PUBLISHED",
        "source_uri": "https://example.org/evidence",
        "trust_tier": "A",
        "retrieved_at": "2026-09-25T10:30:00Z",
    })
    assert source.status_code == 201
    entity = client.post("/v2/intelligence/entities", json={"canonical_name": "Example VASP", "entity_type": "VASP"})
    assert entity.status_code == 201
    assertion = client.post("/v2/intelligence/assertions", json={
        "entity_id": entity.json()["id"],
        "address": "0x" + "c" * 40,
        "chain": "ETHEREUM",
        "role": "VASP_HOT_WALLET",
        "assertion_type": "VERIFIED",
        "source_id": source.json()["id"],
        "review_state": "REVIEWED",
        "last_verified_at": "2026-09-25T10:30:00Z",
    })
    assert assertion.status_code == 201
    resolved = client.get("/v2/intelligence/assertions", params={"address": "0x" + "c" * 40, "chain": "ETHEREUM"})
    assert resolved.status_code == 200
    assert resolved.json()[0]["entity"]["canonical_name"] == "Example VASP"
    assert resolved.json()[0]["assertion"]["assertion_type"] == "VERIFIED"

def test_v2_synthetic_demo_is_explicit_and_contains_flow_and_inference():
    response = client.post("/demo/scenarios/v2-deposit-inference")
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_mode"] == "SYNTHETIC"
    assert payload["flow"]["seed_amount"] == "5000"
    assert payload["attribution"]["candidates"][0]["entity_name"] == "Synthetic Demo Exchange"
    assert payload["deposit_inferences"][0]["assertion_type"] == "RULE_INFERRED"
    assert "SYNTHETIC DEMO" in payload["limitations"][0]

def test_v2_ml_feature_snapshot_api_is_time_bounded_and_retrievable():
    asset = {"chain": "ETHEREUM", "symbol": "USDT", "contract_address": "0x" + "c" * 40, "decimals": 6}
    payload = {
        "address": "0x" + "d" * 40,
        "asset": asset,
        "snapshot_time": "2026-09-25T10:00:00Z",
        "transfers": [
            {
                "id": "ML-TRANSFER-1", "transaction_id": "ML-TX-1", "chain": "ETHEREUM",
                "source_address": "0x" + "e" * 40, "destination_address": "0x" + "d" * 40,
                "asset": asset, "raw_amount": "100", "normalized_amount": "100",
                "timestamp": "2026-09-25T09:59:00Z", "raw_evidence_id": "ML-EVID-1",
            },
            {
                "id": "ML-TRANSFER-FUTURE", "transaction_id": "ML-TX-FUTURE", "chain": "ETHEREUM",
                "source_address": "0x" + "e" * 40, "destination_address": "0x" + "d" * 40,
                "asset": asset, "raw_amount": "999", "normalized_amount": "999",
                "timestamp": "2026-09-25T10:01:00Z", "raw_evidence_id": "ML-EVID-FUTURE",
            },
        ],
    }
    response = client.post("/v2/ml/feature-snapshots", json=payload)
    assert response.status_code == 201
    snapshot = response.json()
    assert snapshot["features"]["incoming_tx_count"] == 1.0
    assert "ML-EVID-1" in snapshot["evidence_ids"]
    assert "ML-EVID-FUTURE" not in snapshot["evidence_ids"]
    retrieved = client.get(f"/v2/ml/feature-snapshots/{snapshot['id']}")
    assert retrieved.status_code == 200
    assert retrieved.json()["feature_hash_sha256"] == snapshot["feature_hash_sha256"]

def test_v2_recorded_trace_runs_end_to_end_and_persists_raw_evidence():
    asset = {"chain": "ETHEREUM", "symbol": "USDT", "contract_address": "0x" + "b" * 40, "decimals": 6}
    root = "0x" + "a" * 40
    victim = "0x" + "c" * 40
    collector = "0x" + "d" * 40
    source = client.post("/v2/intelligence/sources", json={
        "name": "Recorded test source", "source_type": "VASP_PUBLISHED", "trust_tier": "A", "retrieved_at": "2026-09-25T10:00:00Z",
    }).json()
    entity = client.post("/v2/intelligence/entities", json={"canonical_name": "Recorded Exchange", "entity_type": "VASP"}).json()
    assertion = client.post("/v2/intelligence/assertions", json={
        "entity_id": entity["id"], "address": collector, "chain": "ETHEREUM", "role": "VASP_COLLECTOR",
        "assertion_type": "VERIFIED", "source_id": source["id"], "review_state": "REVIEWED", "last_verified_at": "2026-09-25T10:00:00Z",
    })
    assert assertion.status_code == 201
    tx_hash = "0x" + "1" * 64
    case = client.post("/v2/cases", json={
        "title": "Recorded transaction trace", "context": {
            "seed_type": "transaction", "chain": "ETHEREUM", "seed_tx_hash": tx_hash, "asset": asset,
            "disputed_amount": "100", "incident_time": "2026-09-25T10:00:00Z", "data_mode": "RECORDED_REAL",
        },
    }).json()
    transfers = [
        {"id": "SEED-IN", "transaction_id": "TX-ETHEREUM-" + tx_hash, "chain": "ETHEREUM", "source_address": victim, "destination_address": root, "asset": asset, "raw_amount": "100", "normalized_amount": "100", "timestamp": "2026-09-25T10:00:00Z", "raw_evidence_id": "EVID-REC-1"},
        {"id": "OUT-COLLECTOR", "transaction_id": "TX-ETHEREUM-0x" + "2" * 64, "chain": "ETHEREUM", "source_address": root, "destination_address": collector, "asset": asset, "raw_amount": "100", "normalized_amount": "100", "timestamp": "2026-09-25T10:05:00Z", "raw_evidence_id": "EVID-REC-2"},
    ]
    trace = client.post(f"/v2/cases/{case['id']}/trace", json={"recorded_transfers": transfers})
    assert trace.status_code == 201, trace.text
    result = trace.json()
    assert result["data_mode"] == "RECORDED_REAL"
    assert result["attribution"]["candidates"][0]["entity_name"] == "Recorded Exchange"
    repeat = client.post(f"/v2/cases/{case['id']}/trace", json={"recorded_transfers": transfers})
    assert repeat.status_code == 201
    assert repeat.json()["id"] == result["id"]
    assert len(client.get(f"/v2/cases/{case['id']}/results").json()) == 1
    artifact = client.get("/v2/evidence/EVID-REC-1")
    assert artifact.status_code == 200
    assert artifact.json()["provider"] == "recorded_import"
    manifest = result["evidence_manifest"]["evidence"]
    assert any(item["id"] == "raw_evidence:EVID-REC-1" and item["provider"] == "recorded_import" for item in manifest)


def test_v2_assertion_review_keeps_decision_history():
    source = client.post("/v2/intelligence/sources", json={"name": "Review source", "source_type": "INTERNAL_REVIEW", "trust_tier": "A", "retrieved_at": "2026-09-25T10:00:00Z"}).json()
    entity = client.post("/v2/intelligence/entities", json={"canonical_name": "Review target", "entity_type": "VASP"}).json()
    assertion = client.post("/v2/intelligence/assertions", json={
        "entity_id": entity["id"], "address": "0x" + "e" * 40, "chain": "ETHEREUM", "role": "VASP_DEPOSIT",
        "assertion_type": "RULE_INFERRED", "source_id": source["id"], "review_state": "UNREVIEWED",
    }).json()
    response = client.post(f"/v2/intelligence/assertions/{assertion['id']}/reviews", json={"review_state": "REJECTED", "rationale": "Insufficient independent corroboration."})
    assert response.status_code == 200
    assert response.json()["review_state"] == "REJECTED"
    history = client.get(f"/v2/intelligence/assertions/{assertion['id']}/reviews")
    assert history.status_code == 200
    assert history.json()[0]["rationale"] == "Insufficient independent corroboration."


def test_v2_recorded_import_endpoint_creates_case_and_replays_without_provider():
    asset = {"chain": "ETHEREUM", "symbol": "USDT", "contract_address": "0x" + "a" * 40, "decimals": 6}
    seed_hash = "0x" + "4" * 64
    payload = {
        "case": {"title": "Imported recorded package", "context": {"seed_type": "transaction", "chain": "ETHEREUM", "seed_tx_hash": seed_hash, "asset": asset, "disputed_amount": "15", "incident_time": "2026-09-26T09:00:00Z", "data_mode": "RECORDED_REAL"}},
        "trace": {"recorded_transfers": [{"id": "IMPORTED-SEED", "transaction_id": "TX-ETHEREUM-" + seed_hash, "chain": "ETHEREUM", "source_address": "0x" + "b" * 40, "destination_address": "0x" + "c" * 40, "asset": asset, "raw_amount": "15", "normalized_amount": "15", "timestamp": "2026-09-26T09:00:00Z", "raw_evidence_id": "EVID-IMPORTED"}]},
    }
    response = client.post("/v2/imports/recorded-trace", json=payload)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["data_mode"] == "RECORDED_REAL"
    assert client.get(f"/v2/cases/{result['case_id']}").status_code == 200
    assert client.get("/v2/evidence/EVID-IMPORTED").json()["provider"] == "recorded_import"


def test_v2_entity_relationship_requires_source_and_lists_by_entity():
    source = client.post("/v2/intelligence/sources", json={"name": "Relationship source", "source_type": "INTERNAL_REVIEW", "trust_tier": "A", "retrieved_at": "2026-09-26T09:00:00Z"}).json()
    cluster = client.post("/v2/intelligence/entities", json={"canonical_name": "Exchange cluster", "entity_type": "VASP"}).json()
    wallet = client.post("/v2/intelligence/entities", json={"canonical_name": "Exchange wallet group", "entity_type": "SERVICE"}).json()
    created = client.post("/v2/intelligence/relationships", json={"source_entity_id": wallet["id"], "target_entity_id": cluster["id"], "relationship_type": "CLUSTER_MEMBER_OF", "source_id": source["id"], "review_state": "REVIEWED"})
    assert created.status_code == 201
    listed = client.get("/v2/intelligence/relationships", params={"entity_id": cluster["id"]})
    assert listed.status_code == 200
    assert listed.json()[0]["relationship_type"] == "CLUSTER_MEMBER_OF"


def test_ml_feature_snapshot_honors_optional_lookback_window():
    asset = {"chain": "ETHEREUM", "symbol": "USDT", "contract_address": "0x" + "d" * 40, "decimals": 6}
    address = "0x" + "e" * 40
    payload = {"address": address, "asset": asset, "snapshot_time": "2026-09-26T10:00:00Z", "lookback_hours": 1, "transfers": [
        {"id": "OLD", "transaction_id": "TX-OLD", "chain": "ETHEREUM", "source_address": "0x" + "f" * 40, "destination_address": address, "asset": asset, "raw_amount": "10", "normalized_amount": "10", "timestamp": "2026-09-26T08:00:00Z", "raw_evidence_id": "EVID-OLD"},
        {"id": "RECENT", "transaction_id": "TX-RECENT", "chain": "ETHEREUM", "source_address": "0x" + "f" * 40, "destination_address": address, "asset": asset, "raw_amount": "20", "normalized_amount": "20", "timestamp": "2026-09-26T09:30:00Z", "raw_evidence_id": "EVID-RECENT"},
    ]}
    response = client.post("/v2/ml/feature-snapshots", json=payload)
    assert response.status_code == 201
    assert response.json()["features"]["incoming_tx_count"] == 1.0
    assert "EVID-OLD" not in response.json()["evidence_ids"]


def test_tron_transaction_seed_adapter_normalizes_confirmed_transfer():
    import asyncio
    from datetime import datetime, timezone
    from decimal import Decimal
    from backend.adapters import LegacyExplorerAdapter
    from backend.domain import AssetRef
    from backend.models import Chain, TransferEvidence

    class FakeTronClient:
        async def transaction_trc20_transfers(self, tx_hash, symbol, contract, decimals):
            return [TransferEvidence(transaction_hash=tx_hash, source_address="T" + "A" * 33, destination_address="T" + "B" * 33, token_symbol=symbol, token_contract=contract or "TR7", amount=Decimal("12.5"), timestamp=datetime(2026, 9, 26, tzinfo=timezone.utc), block_number=123, confirmed=True, provider="TronGrid", retrieved_at=datetime(2026, 9, 26, tzinfo=timezone.utc))], {"provider": "TronGrid", "endpoint": "https://api.trongrid.io/v1/transactions/test/events", "retrieved_at": "2026-09-26T00:00:00Z"}

    asset = AssetRef(chain=Chain.TRON, symbol="USDT", contract_address="TR7", decimals=6)
    result = asyncio.run(LegacyExplorerAdapter(Chain.TRON, FakeTronClient()).transaction_transfers("a" * 64, asset))
    assert result.complete is True
    assert result.transfers[0].source_address.startswith("T")
    assert result.transfers[0].transaction_id.endswith("a" * 64)


def test_v2_recorded_csv_import_replays_canonical_transfer():
    asset = {"chain": "ETHEREUM", "symbol": "USDT", "contract_address": "0x" + "1" * 40, "decimals": 6}
    seed_hash = "0x" + "2" * 64
    csv_text = "id,transaction_id,source_address,destination_address,raw_amount,normalized_amount,timestamp,raw_evidence_id\nCSV-SEED,TX-ETHEREUM-" + seed_hash + ",0x" + "3" * 40 + ",0x" + "4" * 40 + ",25,25,2026-09-26T09:00:00Z,EVID-CSV\n"
    response = client.post("/v2/imports/recorded-trace/csv", json={"case": {"title": "CSV recorded package", "context": {"seed_type": "transaction", "chain": "ETHEREUM", "seed_tx_hash": seed_hash, "asset": asset, "disputed_amount": "25", "incident_time": "2026-09-26T09:00:00Z", "data_mode": "RECORDED_REAL"}}, "transfers_csv": csv_text})
    assert response.status_code == 201, response.text
    assert response.json()["transfers"][0]["id"] == "CSV-SEED"


def test_evm_transaction_seed_decodes_matching_erc20_transfer_log():
    import asyncio
    from backend.ethereum import EvmScanClient

    class FakeEvmClient(EvmScanClient):
        async def _get_page(self, client, params):
            if params["action"] == "eth_getTransactionReceipt":
                return {"result": {"blockNumber": "0x10", "logs": [{"address": "0x" + "a" * 40, "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef", "0x" + "0" * 24 + "b" * 40, "0x" + "0" * 24 + "c" * 40], "data": "0x0f4240"}]}}, 1
            return {"result": {"timestamp": "0x69c60000"}}, 1

    client = FakeEvmClient(api_key="test")
    transfers, provenance = asyncio.run(client.transaction_erc20_transfers("0x" + "d" * 64, "USDT", "0x" + "a" * 40, 6))
    assert len(transfers) == 1
    assert str(transfers[0].amount) == "1"
    assert transfers[0].source_address == "0x" + "b" * 40
    assert provenance["receipt_block"] == 16


def test_actionability_envelope_blocks_then_enables_local_request_with_reviewed_profile():
    asset = {"chain": "ETHEREUM", "symbol": "USDT", "contract_address": "0x" + "8" * 40, "decimals": 6}
    root, victim, collector = "0x" + "1" * 40, "0x" + "2" * 40, "0x" + "3" * 40
    source = client.post("/v2/intelligence/sources", json={"name": "Actionability source", "source_type": "VASP_PUBLISHED", "trust_tier": "A", "retrieved_at": "2026-09-26T10:00:00Z"}).json()
    entity = client.post("/v2/intelligence/entities", json={"canonical_name": "Actionability Exchange", "entity_type": "VASP"}).json()
    client.post("/v2/intelligence/assertions", json={
        "entity_id": entity["id"], "address": collector, "chain": "ETHEREUM", "role": "VASP_COLLECTOR",
        "assertion_type": "VERIFIED", "source_id": source["id"], "review_state": "REVIEWED", "last_verified_at": "2026-09-26T10:00:00Z",
    })
    case = client.post("/v2/cases", json={"title": "Actionability case", "context": {
        "seed_type": "transaction", "chain": "ETHEREUM", "seed_tx_hash": "0x" + "4" * 64, "asset": asset,
        "disputed_amount": "100", "incident_time": "2026-09-26T10:00:00Z", "data_mode": "RECORDED_REAL",
    }}).json()
    transfers = [
        {"id": "ACTION-SEED", "transaction_id": "TX-ETHEREUM-0x" + "4" * 64, "chain": "ETHEREUM", "source_address": victim, "destination_address": root, "asset": asset, "raw_amount": "100", "normalized_amount": "100", "timestamp": "2026-09-26T10:00:00Z", "raw_evidence_id": "EVID-ACTION-1"},
        {"id": "ACTION-ENDPOINT", "transaction_id": "TX-ACTION-ENDPOINT", "chain": "ETHEREUM", "source_address": root, "destination_address": collector, "asset": asset, "raw_amount": "100", "normalized_amount": "100", "timestamp": "2026-09-26T10:05:00Z", "raw_evidence_id": "EVID-ACTION-2"},
    ]
    trace_response = client.post(f"/v2/cases/{case['id']}/trace", json={"recorded_transfers": transfers})
    assert trace_response.status_code == 201, trace_response.text
    result = trace_response.json()
    before = client.get(f"/v2/results/{result['id']}/actionability")
    assert before.status_code == 200
    assert before.json()["candidates"][0]["recommendation"] == "COLLECT_MORE_EVIDENCE"
    assert before.json()["candidates"][0]["envelope"]["maximum_request_amount"] == "0"
    profile = client.post("/v2/vasp-readiness-profiles", json={
        "entity_id": entity["id"], "supported_chains": ["ETHEREUM"], "local_contact_route": "LOCAL_DEMO_ROUTE",
        "template_version": "demo-v1", "review_state": "REVIEWED",
    })
    assert profile.status_code == 201
    after = client.get(f"/v2/results/{result['id']}/actionability")
    assert after.status_code == 200
    candidate = after.json()["candidates"][0]
    assert candidate["recommendation"] == "READY_FOR_LOCAL_DRAFT"
    assert candidate["envelope"]["maximum_request_amount"] == "100"
