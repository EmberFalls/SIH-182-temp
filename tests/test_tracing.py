import asyncio
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

from backend.models import CaseCreate, Chain, TraceRequest, TransferEvidence, VaspLabelCreate
from backend.storage import Store
from backend.tracing import TraceService


ROOT = "T" + "A" * 33
DESTINATION = "T" + "B" * 33


class FakeTronClient:
    async def outgoing_trc20_transfers(self, address, token_symbol, limit):
        assert address == ROOT
        return [TransferEvidence(
            transaction_hash="a" * 64,
            source_address=ROOT,
            destination_address=DESTINATION,
            token_symbol="USDT",
            token_contract="TR7NHqjeKQxGTCi8q8ZY4pL8otSzg",
            amount=Decimal("125.50"),
            timestamp=datetime(2026, 9, 24, tzinfo=timezone.utc),
            block_number=123,
            confirmed=True,
            provider="FakeTron",
            retrieved_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
        )], {"provider": "FakeTron", "retrieved_at": "2026-09-24T00:00:00+00:00"}


def test_trace_only_attributes_a_sourced_label(tmp_path):
    store = Store(str(tmp_path / "trace.db"))
    case = store.create_case(CaseCreate(title="Investigated transfer", suspect_wallet=ROOT))
    label = store.add_label(VaspLabelCreate(
        address=DESTINATION,
        chain=Chain.TRON,
        vasp_name="Verified Exchange",
        label_type="hot_wallet",
        confidence="verified",
        reviewer="Reviewer",
        source={"url": "https://example.org/evidence", "source_name": "Explorer label", "observed_at": "2026-09-24T00:00:00Z"},
    ))
    result = asyncio.run(TraceService(store, tron_client=FakeTronClient()).trace_case(case, TraceRequest(max_hops=1)))
    assert result.status == "COMPLETED"
    assert len(result.transfers) == 1
    assert result.candidates[0].vasp_name == "Verified Exchange"
    assert result.candidates[0].label_id == label.id
    assert len(result.manifest_sha256) == 64
    assert result.graph is not None
    assert len(result.graph.edges) == 1
    assert result.graph.edges[0].attributed_amount == Decimal("125.50")
    assert result.graph.paths[0].candidate_label_id == label.id
    assert result.graph.paths[0].node_addresses == [ROOT, DESTINATION]
    assert result.graph.edges[0].explorer_url.startswith("https://tronscan.org/")
    assert result.manifest_payload is not None
    assert hashlib.sha256(json.dumps(result.manifest_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest() == result.manifest_sha256
