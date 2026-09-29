"""Reproducible, evidence-linked cross-case connections for V2 results."""
from __future__ import annotations

from datetime import datetime, timezone

from .canonical import canonical_sha256
from .domain import CaseConnectionV2, CrossCaseConnectionType, InvestigationResultV2


class CrossCaseIndexerV2:
    """Indexes only exact, explainable overlap; it never infers common ownership."""

    def __init__(self, store) -> None:
        self.store = store

    def index(self, result: InvestigationResultV2) -> list[CaseConnectionV2]:
        created: list[CaseConnectionV2] = []
        for other_case in self.store.list_investigation_cases_v2():
            if other_case.id == result.case_id:
                continue
            other_results = self.store.list_investigation_results_v2(other_case.id)
            if not other_results:
                continue
            other = other_results[0]
            created.extend(self._connections_between(result, other))
        return [self.store.save_case_connection_v2(item) for item in created]

    def _connections_between(self, left: InvestigationResultV2, right: InvestigationResultV2) -> list[CaseConnectionV2]:
        # Keep one stable orientation for each pair so re-indexing either result
        # does not create a second, reversed copy of the same investigative lead.
        if left.case_id > right.case_id:
            left, right = right, left
        links: list[CaseConnectionV2] = []
        left_addresses = {address.lower(): transfer.id for transfer in left.transfers for address in (transfer.source_address, transfer.destination_address)}
        right_addresses = {address.lower(): transfer.id for transfer in right.transfers for address in (transfer.source_address, transfer.destination_address)}
        for address in sorted(set(left_addresses) & set(right_addresses)):
            links.append(self._new(left, right, CrossCaseConnectionType.SAME_ADDRESS, address, [left_addresses[address], right_addresses[address]], "The same observed blockchain address appears in both saved results. This is an investigative lead and does not prove shared beneficial ownership."))
        left_transactions = {transfer.transaction_id.lower(): transfer.id for transfer in left.transfers}
        right_transactions = {transfer.transaction_id.lower(): transfer.id for transfer in right.transfers}
        for transaction_id in sorted(set(left_transactions) & set(right_transactions)):
            links.append(self._new(left, right, CrossCaseConnectionType.SAME_TRANSACTION, transaction_id, [left_transactions[transaction_id], right_transactions[transaction_id]], "The same canonical transaction is referenced by both saved results."))
        left_entities = {candidate.entity_id: candidate.id for candidate in left.attribution.candidates if candidate.status.value == "VERIFIED"}
        right_entities = {candidate.entity_id: candidate.id for candidate in right.attribution.candidates if candidate.status.value == "VERIFIED"}
        for entity_id in sorted(set(left_entities) & set(right_entities)):
            links.append(self._new(left, right, CrossCaseConnectionType.SAME_VERIFIED_ENTITY, entity_id, [left_entities[entity_id], right_entities[entity_id]], "Both cases reached the same verified entity under their respective immutable result snapshots."))
        return links

    @staticmethod
    def _new(left: InvestigationResultV2, right: InvestigationResultV2, kind: CrossCaseConnectionType, relation_key: str, evidence_ids: list[str], explanation: str) -> CaseConnectionV2:
        body = {"source_result_id": left.id, "related_result_id": right.id, "connection_type": kind.value, "relation_key": relation_key}
        return CaseConnectionV2(
            id=f"CASELINK-{canonical_sha256(body)[:24].upper()}", source_case_id=left.case_id,
            related_case_id=right.case_id, source_result_id=left.id, related_result_id=right.id,
            connection_type=kind, relation_key=relation_key, evidence_ids=evidence_ids,
            explanation=explanation, created_at=datetime.now(timezone.utc),
        )
