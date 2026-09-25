"""Local, generic lawful-request draft boundary for v2 snapshots."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol
import uuid

from .canonical import canonical_sha256
from .domain import CandidateStatus, DataMode, InvestigationCaseV2, InvestigationResultV2, RequestDraftV2


class LawfulRequestExportAdapter(Protocol):
    def build_draft(
        self,
        case: InvestigationCaseV2,
        investigation_result: InvestigationResultV2,
        candidate_id: str | None = None,
        request_purpose: str = "Request preservation, KYC, and relevant transaction records under authorized process.",
        investigator_notes: str = "",
    ) -> RequestDraftV2: ...


class GenericSahyogDraftExporter:
    """Creates a local draft only. No API submission, browser automation, or transmission exists here."""

    def build_draft(
        self,
        case: InvestigationCaseV2,
        investigation_result: InvestigationResultV2,
        candidate_id: str | None = None,
        request_purpose: str = "Request preservation, KYC, and relevant transaction records under authorized process.",
        investigator_notes: str = "",
    ) -> RequestDraftV2:
        if investigation_result.case_id != case.id:
            raise ValueError("The investigation result does not belong to the supplied case.")
        if investigation_result.data_mode == DataMode.SYNTHETIC:
            raise ValueError("Synthetic results cannot produce an operational request draft.")
        if case.status != "UNDER_REVIEW":
            raise ValueError("A v2 case must be UNDER_REVIEW before a local request draft can be generated.")
        candidates = investigation_result.attribution.candidates
        candidate = next((item for item in candidates if item.id == candidate_id), candidates[0] if candidate_id is None and candidates else None)
        if candidate is None:
            raise ValueError("No actionable VASP candidate exists in this investigation result.")
        if candidate.status not in {CandidateStatus.VERIFIED, CandidateStatus.INFERRED_STRONG}:
            raise ValueError("The selected candidate is not evidence-supported enough for an operational draft.")
        transfer_ids = self._transfer_ids_for_candidate(investigation_result, candidate.path_ids)
        transfers = [item for item in investigation_result.transfers if item.id in transfer_ids]
        return RequestDraftV2(
            id=f"LOCAL-DRAFT-{uuid.uuid4().hex[:12].upper()}",
            case_id=case.id,
            result_id=investigation_result.id,
            result_version=investigation_result.version,
            vasp_entity_id=candidate.entity_id,
            vasp_entity_name=candidate.entity_name,
            terminal_addresses=candidate.terminal_addresses,
            terminal_roles=candidate.terminal_roles,
            relevant_transfer_ids=sorted(transfer_ids),
            relevant_transaction_ids=sorted({item.transaction_id for item in transfers}),
            attributed_amount=candidate.attributed_amount,
            chain=case.context.chain,
            asset=case.context.asset,
            evidence_manifest_sha256=investigation_result.evidence_manifest.sha256,
            evidence_ids=candidate.evidence_ids,
            request_purpose=request_purpose,
            investigator_notes=investigator_notes,
            created_at=datetime.now(timezone.utc),
            boundary_notice="LOCAL EXPORT ONLY. This draft has not been transmitted to SAHYOG or any VASP. An authorized investigator must review, edit, approve, and submit it through the official lawful workflow.",
        )

    @staticmethod
    def _transfer_ids_for_candidate(result: InvestigationResultV2, path_ids: list[str]) -> set[str]:
        allocation_by_id = {item.id: item for item in result.flow.allocations}
        required: set[str] = set()
        for terminal in result.flow.terminals:
            for allocation_id in terminal.parent_allocation_ids:
                lineage = GenericSahyogDraftExporter._lineage(allocation_id, allocation_by_id)
                path_id = f"PATH-{canonical_sha256(lineage)[:20].upper()}" if lineage else None
                if path_id not in path_ids:
                    continue
                required.update(allocation_by_id[item].transfer_id for item in lineage)
        return required

    @staticmethod
    def _lineage(allocation_id: str, allocations: dict) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()

        def visit(current: str) -> None:
            if current in seen or current not in allocations:
                return
            seen.add(current)
            for parent in allocations[current].parent_allocation_ids:
                visit(parent)
            ordered.append(current)

        visit(allocation_id)
        return ordered