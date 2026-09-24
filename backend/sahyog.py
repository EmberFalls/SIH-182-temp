import uuid

from .models import CaseSummary, SahyogDraft, TraceResult


class SahyogDraftService:
    def create(self, case: CaseSummary, trace: TraceResult, candidate_rank: int = 1) -> SahyogDraft:
        if not trace.candidates or candidate_rank < 1 or candidate_rank > len(trace.candidates):
            raise ValueError("No supported VASP candidate exists at the requested rank.")
        candidate = trace.candidates[candidate_rank - 1]
        action = "PRESERVATION_REQUEST" if candidate.evidence_grade == "verified" and candidate.priority_score >= 80 else "KYC_AND_TRANSACTION_LOGS"
        return SahyogDraft(
            draft_id=f"DRAFT-{uuid.uuid4().hex[:12].upper()}", case_id=case.id, run_id=trace.run_id,
            vasp_name=candidate.vasp_name, target_address=candidate.address,
            relevant_transactions=[candidate.supporting_transaction], attributed_amount=candidate.attributed_amount,
            recommended_action=action, status="DRAFT_REQUIRES_INVESTIGATOR_REVIEW",
            evidence_summary=f"{candidate.ranking_reason} The request is a draft only and needs authorized investigator and legal review before SAHYOG submission.",
        )
