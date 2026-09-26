import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.cross_chain_v2 import (
    BridgeRouteCreateV2,
    CrossChainResolveRequestV2,
    CrossChainResolverV2,
    new_bridge_route,
)
from backend.domain import (
    AssertionReviewState,
    AssetRef,
    CanonicalTransfer,
    EntityCreate,
    EntityType,
    HistoricalBalanceQuality,
    TerminalReason,
    TracePolicyV2,
    WalletAssetStateSnapshot,
)
from backend.flow_v2 import FundFlowEngineV2
from backend.models import Chain
from backend.storage import Store


NOW = datetime(2026, 9, 25, 9, 0, tzinfo=timezone.utc)
SOURCE_USER = "0x" + "1" * 40
SOURCE_BRIDGE = "0x" + "2" * 40
DEST_BRIDGE = "0x" + "3" * 40
DEST_USER = "0x" + "4" * 40
DEST_VASP = "0x" + "5" * 40
SOURCE_ASSET = AssetRef(chain=Chain.ETHEREUM, symbol="USDC", contract_address="0x" + "a" * 40, decimals=6, canonical_asset_id="USD_STABLE/USDC")
DEST_ASSET = AssetRef(chain=Chain.POLYGON, symbol="USDC", contract_address="0x" + "b" * 40, decimals=6, canonical_asset_id="USD_STABLE/USDC")


def transfer(identifier, chain, source, destination, asset, amount, minute):
    return CanonicalTransfer(
        id=identifier,
        transaction_id=f"TX-{identifier}",
        chain=chain,
        source_address=source,
        destination_address=destination,
        asset=asset,
        raw_amount=Decimal(amount),
        normalized_amount=Decimal(amount),
        timestamp=NOW + timedelta(minutes=minute),
        raw_evidence_id=f"EVID-{identifier}",
    )


def registered_route(store: Store):
    bridge = store.create_entity(EntityCreate(canonical_name="Fixture Bridge", entity_type=EntityType.BRIDGE))
    return store.save_bridge_route_v2(new_bridge_route(BridgeRouteCreateV2(
        bridge_entity_id=bridge.id,
        protocol="FixtureBridge",
        source_chain=Chain.ETHEREUM,
        source_bridge_address=SOURCE_BRIDGE,
        destination_chain=Chain.POLYGON,
        destination_bridge_address=DEST_BRIDGE,
        source_asset_contract=SOURCE_ASSET.contract_address,
        destination_asset_contract=DEST_ASSET.contract_address,
        route_evidence_id="EVID-ROUTE-REVIEWED",
        review_state=AssertionReviewState.REVIEWED,
    ), NOW))


class Repository:
    def __init__(self, transfers):
        self.transfers = transfers

    async def outgoing_transfers(self, address, asset, start_time, end_time):
        return [
            item for item in self.transfers
            if item.source_address == address.lower() and item.asset == asset
            and item.timestamp >= start_time and (end_time is None or item.timestamp <= end_time)
        ]


class Balances:
    async def state_at(self, address, asset, timestamp):
        return WalletAssetStateSnapshot(
            address=address, asset=asset,
            historical_balance_quality=HistoricalBalanceQuality.EXACT,
        )


def test_exact_message_link_scales_value_and_continues_destination_trace(tmp_path):
    store = Store(str(tmp_path / "cross-chain.db"))
    route = registered_route(store)
    source = transfer("SOURCE", Chain.ETHEREUM, SOURCE_USER, SOURCE_BRIDGE, SOURCE_ASSET, "100", 1)
    destination = transfer("DESTINATION", Chain.POLYGON, DEST_BRIDGE, DEST_USER, DEST_ASSET, "99", 5)
    resolver = CrossChainResolverV2(store)
    link = resolver.resolve(CrossChainResolveRequestV2(
        route_id=route.id,
        source_transfer=source,
        destination_transfer=destination,
        message_id="fixture-message-0001",
        source_event_evidence_id="EVID-SOURCE-EVENT",
        destination_event_evidence_id="EVID-DESTINATION-EVENT",
    ), NOW + timedelta(minutes=6))
    store.save_cross_chain_link_v2(link)
    continuation = resolver.continuation(link, "ALLOC-SOURCE", Decimal("70"))
    assert continuation.destination_attributed_amount == Decimal("69.3")
    assert continuation.destination_seed.timestamp == destination.timestamp
    assert continuation.destination_seed.source_evidence_id == link.id

    downstream = transfer("DEST-TO-VASP", Chain.POLYGON, DEST_USER, DEST_VASP, DEST_ASSET, "99", 8)
    result = asyncio.run(resolver.trace_destination(
        FundFlowEngineV2(Repository([downstream]), Balances(), terminal_classifier=lambda _: TerminalReason.VERIFIED_VASP),
        continuation,
        TracePolicyV2(max_hops=2),
    ))
    assert result.allocations[0].attributed_disputed_amount == Decimal("69.3")
    assert result.terminals[0].reason == TerminalReason.VERIFIED_VASP
    assert store.get_cross_chain_link_v2(link.id).message_id == "fixture-message-0001"


def test_recorded_real_source_fixture_is_explicitly_non_continuable():
    import json
    from pathlib import Path

    fixture = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "recorded_real" / "wormhole_avalanche_fuji_to_base_sepolia_message.json").read_text(encoding="utf-8-sig"))
    assert fixture["data_mode"] == "RECORDED_REAL"
    assert fixture["continuation_eligibility"] == "NOT_ELIGIBLE"
    assert fixture["source_transaction_hash"].startswith("0x")


def test_missing_or_unreviewed_bridge_evidence_cannot_continue(tmp_path):
    store = Store(str(tmp_path / "cross-chain.db"))
    route = registered_route(store)
    source = transfer("SOURCE", Chain.ETHEREUM, SOURCE_USER, SOURCE_BRIDGE, SOURCE_ASSET, "100", 1)
    destination = transfer("DESTINATION", Chain.POLYGON, DEST_BRIDGE, DEST_USER, DEST_ASSET, "99", 5)
    resolver = CrossChainResolverV2(store)
    with pytest.raises(ValueError, match="message"):
        resolver.resolve(CrossChainResolveRequestV2(
            route_id=route.id,
            source_transfer=source,
            destination_transfer=destination,
            message_id=" ",
            source_event_evidence_id="EVID-SOURCE-EVENT",
            destination_event_evidence_id="EVID-DESTINATION-EVENT",
        ), NOW)
    terminal = resolver.unresolved_terminal(source, Decimal("70"), "Bridge event observed but no exact destination message proof was available.", ["ALLOC-SOURCE"], 2)
    assert terminal.reason == TerminalReason.BRIDGE_UNRESOLVED
    assert terminal.amount == Decimal("70")


client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "cross-chain-api.db"))
    monkeypatch.setattr(app_module, "store", store)


def test_cross_chain_api_persists_reviewed_route_link_and_continuation():
    bridge = app_module.store.create_entity(EntityCreate(canonical_name="API Fixture Bridge", entity_type=EntityType.BRIDGE))
    route_response = client.post("/v2/bridges/routes", json={
        "bridge_entity_id": bridge.id,
        "protocol": "FixtureBridge",
        "source_chain": "ETHEREUM",
        "source_bridge_address": SOURCE_BRIDGE,
        "destination_chain": "POLYGON",
        "destination_bridge_address": DEST_BRIDGE,
        "source_asset_contract": SOURCE_ASSET.contract_address,
        "destination_asset_contract": DEST_ASSET.contract_address,
        "route_evidence_id": "EVID-ROUTE-REVIEWED",
        "review_state": "REVIEWED",
    })
    assert route_response.status_code == 201
    route = route_response.json()
    source = transfer("API-SOURCE", Chain.ETHEREUM, SOURCE_USER, SOURCE_BRIDGE, SOURCE_ASSET, "100", 1).model_dump(mode="json")
    destination = transfer("API-DEST", Chain.POLYGON, DEST_BRIDGE, DEST_USER, DEST_ASSET, "99", 5).model_dump(mode="json")
    link_response = client.post("/v2/cross-chain/links/resolve", json={
        "route_id": route["id"],
        "source_transfer": source,
        "destination_transfer": destination,
        "message_id": "fixture-message-api-0001",
        "source_event_evidence_id": "EVID-SOURCE-EVENT",
        "destination_event_evidence_id": "EVID-DESTINATION-EVENT",
    })
    assert link_response.status_code == 201
    link = link_response.json()
    assert link["assertion_type"] == "VERIFIED"
    assert "EVID-ROUTE-REVIEWED" in link["evidence_ids"]
    continuation = client.post(f"/v2/cross-chain/links/{link['id']}/continuations", json={
        "source_allocation_id": "ALLOC-API-SOURCE",
        "source_attributed_amount": "50",
    })
    assert continuation.status_code == 200
    assert Decimal(continuation.json()["destination_attributed_amount"]) == Decimal("49.5")

def test_normalized_bridge_events_resolve_only_on_exact_retained_message():
    from backend.canonical import canonical_sha256
    from backend.domain import RawEvidenceArtifact

    bridge = app_module.store.create_entity(EntityCreate(canonical_name="Event Fixture Bridge", entity_type=EntityType.BRIDGE))
    route_response = client.post("/v2/bridges/routes", json={
        "bridge_entity_id": bridge.id, "protocol": "FixtureBridge",
        "source_chain": "ETHEREUM", "source_bridge_address": SOURCE_BRIDGE,
        "destination_chain": "POLYGON", "destination_bridge_address": DEST_BRIDGE,
        "source_asset_contract": SOURCE_ASSET.contract_address,
        "destination_asset_contract": DEST_ASSET.contract_address,
        "route_evidence_id": "EVID-ROUTE-EVENT", "review_state": "REVIEWED",
    })
    assert route_response.status_code == 201
    source = transfer("EVENT-SOURCE", Chain.ETHEREUM, SOURCE_USER, SOURCE_BRIDGE, SOURCE_ASSET, "100", 1)
    destination = transfer("EVENT-DEST", Chain.POLYGON, DEST_BRIDGE, DEST_USER, DEST_ASSET, "99", 5)
    for item, direction in ((source, "SOURCE"), (destination, "DESTINATION")):
        app_module.store.save_raw_evidence_artifact_v2(RawEvidenceArtifact(
            id=item.raw_evidence_id, kind="provider_response", provider="fixture_collector",
            retrieved_at=NOW, content_hash_sha256=canonical_sha256({"id": item.raw_evidence_id}),
            metadata={"bridge_event": {"protocol": "FixtureBridge", "direction": direction,
                "message_id": "exact-event-message-0001", "transaction_id": item.transaction_id,
                "transfer_id": item.id}},
        ))
    source_response = client.post("/v2/bridges/events/extract", json={
        "protocol": "FixtureBridge", "direction": "SOURCE", "raw_evidence_id": source.raw_evidence_id,
        "transfer": source.model_dump(mode="json"),
    })
    destination_response = client.post("/v2/bridges/events/extract", json={
        "protocol": "FixtureBridge", "direction": "DESTINATION", "raw_evidence_id": destination.raw_evidence_id,
        "transfer": destination.model_dump(mode="json"),
    })
    assert source_response.status_code == 201
    assert destination_response.status_code == 201
    link_response = client.post("/v2/cross-chain/links/resolve-events", json={
        "route_id": route_response.json()["id"], "source_event_id": source_response.json()["id"],
        "destination_event_id": destination_response.json()["id"],
    })
    assert link_response.status_code == 201
    assert link_response.json()["message_id"] == "exact-event-message-0001"


def test_bridge_event_extraction_rejects_evidence_without_exact_message():
    from backend.canonical import canonical_sha256
    from backend.domain import RawEvidenceArtifact

    item = transfer("NO-MESSAGE", Chain.ETHEREUM, SOURCE_USER, SOURCE_BRIDGE, SOURCE_ASSET, "10", 1)
    app_module.store.save_raw_evidence_artifact_v2(RawEvidenceArtifact(
        id=item.raw_evidence_id, kind="provider_response", provider="fixture_collector", retrieved_at=NOW,
        content_hash_sha256=canonical_sha256({"id": item.raw_evidence_id}),
        metadata={"bridge_event": {"protocol": "FixtureBridge", "direction": "SOURCE", "transaction_id": item.transaction_id}},
    ))
    response = client.post("/v2/bridges/events/extract", json={
        "protocol": "FixtureBridge", "direction": "SOURCE", "raw_evidence_id": item.raw_evidence_id,
        "transfer": item.model_dump(mode="json"),
    })
    assert response.status_code == 422
    assert "message" in response.json()["detail"].lower()


def test_reconcile_interrupted_trace_job_preserves_retry_payload(tmp_path):
    from backend.jobs_v2 import PersistentTraceJobsV2

    store = Store(str(tmp_path / "jobs.db"))
    job = {
        "job_id": "V2JOB-INTERRUPTED", "status": "RUNNING", "created_at": NOW.isoformat(),
        "case_id": "CASEV2-TEST", "trace_request": {"recorded_transfers": []}, "result_id": None, "attempt": 1,
    }
    store.save_v2_trace_job(job)
    assert PersistentTraceJobsV2(store).reconcile_interrupted() == 1
    recovered = store.get_v2_trace_job(job["job_id"])
    assert recovered["status"] == "INTERRUPTED"
    assert recovered["case_id"] == job["case_id"]
    assert recovered["trace_request"] == job["trace_request"]
