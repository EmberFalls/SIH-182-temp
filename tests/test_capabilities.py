from fastapi.testclient import TestClient

import backend.app as app_module
from backend.capabilities import capability_for, capability_matrix
from backend.models import Chain
from backend.storage import Store
from backend.tracing import TraceService


client = TestClient(app_module.app)


def test_capability_matrix_does_not_overstate_unimplemented_chains():
    matrix = {item.chain: item for item in capability_matrix()}
    assert matrix[Chain.ETHEREUM].transfers == "FULL"
    assert matrix[Chain.BNB_CHAIN].transfers == "FULL"
    assert matrix[Chain.POLYGON].transfers == "FULL"
    assert matrix[Chain.BITCOIN].transfers == "NOT_IMPLEMENTED"
    assert matrix[Chain.SOLANA].fund_allocation == "NOT_IMPLEMENTED"
    assert capability_for(Chain.TRON).live_provider == "TronGrid"


def test_trace_service_uses_reusable_evm_adapter_chain_ids(tmp_path):
    service = TraceService(Store(str(tmp_path / "capabilities.db")))
    assert service.ethereum.chain_id == 1
    assert service.bnb.chain_id == 56
    assert service.polygon.chain_id == 137
    assert service.bnb.chain_name == "BNB Chain"
    assert service.polygon.chain_name == "Polygon"


def test_capability_endpoint_matches_health_support_claim():
    response = client.get("/v2/capabilities")
    assert response.status_code == 200
    items = {item["chain"]: item for item in response.json()}
    assert items["POLYGON"]["transfers"] == "FULL"
    assert items["BITCOIN"]["transfers"] == "NOT_IMPLEMENTED"
    health = client.get("/health").json()
    assert set(health["supported_chains"]) == {"ETHEREUM", "TRON", "BNB_CHAIN", "POLYGON"}
    assert set(health["planned_chain_adapters"]) == {"BITCOIN", "SOLANA"}