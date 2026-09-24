from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.attribution import AttributionEngine
from backend.flow import FlowAllocator
from backend.models import FlowAnalysis, TransferEvidence, VaspCandidate
from backend.risk import RiskEngine
from backend.sahyog import SahyogDraftService
from backend.models import CaseCreate, CaseSummary, TraceResult
from backend.demo import DemoScenarioService
from backend.storage import Store


ROOT = "T" + "A" * 33
MULE = "T" + "B" * 33
VASP = "T" + "C" * 33
NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def transfer(tx_hash, source, destination, amount, minutes=0):
    return TransferEvidence(
        transaction_hash=tx_hash, source_address=source, destination_address=destination,
        token_symbol="USDT", token_contract="TR7", amount=Decimal(amount), timestamp=NOW + timedelta(minutes=minutes),
        block_number=1, confirmed=True, provider="test", retrieved_at=NOW,
    )


def test_allocation_ranking_and_risk_use_case_amount():
    transfers = [transfer("a" * 64, ROOT, MULE, "100"), transfer("b" * 64, MULE, VASP, "95", 5)]
    flow = FlowAllocator().analyze(transfers, ROOT, Decimal("100"))
    assert flow.allocated_amount == Decimal("100")
    assert flow.allocations[1].attributed_amount == Decimal("95")
    candidate = VaspCandidate(label_id="LABEL-1", vasp_name="Exchange", address=VASP, hop=2, label_type="deposit_address", evidence_grade="verified", supporting_transaction="b" * 64)
    ranked = AttributionEngine().rank([candidate], flow)
    assert ranked[0].attributed_amount == Decimal("95")
    assert ranked[0].priority_score > 0
    alerts = RiskEngine().analyze(transfers, [])
    assert any(alert.code == "rapid_movement" for alert in alerts)


def test_ranking_consolidates_multiple_deposits_to_one_vasp_endpoint():
    transfers = [
        transfer("a" * 64, ROOT, VASP, "40"),
        transfer("b" * 64, ROOT, VASP, "60", 1),
    ]
    flow = FlowAllocator().analyze(transfers, ROOT, Decimal("100"))
    candidates = [
        VaspCandidate(label_id="LABEL-1", vasp_name="Exchange", address=VASP, hop=1, label_type="hot_wallet", evidence_grade="verified", supporting_transaction="a" * 64),
        VaspCandidate(label_id="LABEL-1", vasp_name="Exchange", address=VASP, hop=1, label_type="hot_wallet", evidence_grade="verified", supporting_transaction="b" * 64),
    ]
    ranked = AttributionEngine().rank(candidates, flow)
    assert len(ranked) == 1
    assert ranked[0].attributed_amount == Decimal("100")
    assert ranked[0].supporting_transaction == "b" * 64


def test_sahyog_is_draft_only():
    case = CaseSummary(id="CASE-1", title="Case", suspect_wallet=ROOT, chain="TRON", token_symbol="USDT", disputed_amount=Decimal("100"), incident_start=None, incident_end=None, fir_number="FIR-1", notes=None, created_at=NOW)
    candidate = VaspCandidate(label_id="LABEL-1", vasp_name="Exchange", address=VASP, hop=1, label_type="deposit_address", evidence_grade="verified", supporting_transaction="a" * 64, attributed_amount=Decimal("100"), priority_score=90, ranking_reason="Verified label")
    flow = FlowAnalysis(starting_amount=Decimal("100"), allocated_amount=Decimal("100"), unallocated_amount=Decimal("0"), allocations=[], endpoint_amounts={VASP: Decimal("100")}, method_note="test")
    trace = TraceResult(run_id="RUN-1", case_id=case.id, status="COMPLETED", nodes=[], transfers=[], candidates=[candidate], limitations=[], provenance={}, manifest_sha256="a" * 64, created_at=NOW, flow_analysis=flow)
    draft = SahyogDraftService().create(case, trace)
    assert draft.status == "DRAFT_REQUIRES_INVESTIGATOR_REVIEW"
    assert draft.recommended_action == "PRESERVATION_REQUEST"


def test_curated_demo_is_explicitly_simulated(tmp_path):
    store = Store(str(tmp_path / "demo.db"))
    case, trace = DemoScenarioService(store).create_multihop_deposit_sweep()
    assert case.fir_number == "DEMO/SIH182/001"
    assert trace.provenance["data_mode"] == "SIMULATED_DEMO"
    assert len(trace.transfers) == 3
    assert trace.candidates[0].vasp_name == "Binance"
    assert trace.graph is not None
    assert trace.graph.paths[0].node_addresses[0] == case.suspect_wallet
    assert any("SIMULATED_DEMO" in limitation for limitation in trace.limitations)
