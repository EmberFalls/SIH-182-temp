"""Phase 5 attribution candidates built from v2 flow terminals and entity assertions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from .canonical import canonical_sha256
from .domain import (
    AssertionReviewState,
    AssertionType,
    AttributionCandidateV2,
    AttributionEvidenceComponents,
    AttributionSummaryV2,
    CandidateStatus,
    EntityRole,
    EvidenceBand,
    FlowAllocationV2,
    FundFlowResultV2,
    ResolvedEntityAssertion,
    TerminalReason,
    TrustTier,
)
from .entity_resolution import EntityResolver


ACTIONABLE_ROLES = {
    EntityRole.VASP_DEPOSIT,
    EntityRole.VASP_HOT_WALLET,
    EntityRole.VASP_COLD_WALLET,
    EntityRole.VASP_COLLECTOR,
    EntityRole.CUSTODIAL_SERVICE,
}


@dataclass(frozen=True)
class AttributionScoringConfig:
    exact_reviewed_label_max: int = 40
    cluster_relationship_max: int = 25
    deposit_behavior_max: int = 20
    independent_corroboration_max: int = 10
    freshness_max: int = 5
    strong_threshold: int = 80
    moderate_threshold: int = 60
    weak_threshold: int = 40
    inferred_actionable_threshold: int = 50


class AttributionEngineV2:
    """Builds candidates only from terminal receipts with current VASP evidence."""

    def __init__(self, resolver: EntityResolver, config: AttributionScoringConfig | None = None) -> None:
        self.resolver = resolver
        self.config = config or AttributionScoringConfig()

    def build(self, flow: FundFlowResultV2, chain: str, observed_at: datetime | None = None) -> AttributionSummaryV2:
        observed_at = observed_at or datetime.now(timezone.utc)
        allocation_index = {allocation.id: allocation for allocation in flow.allocations}
        grouped: dict[str, list[tuple[object, ResolvedEntityAssertion]]] = {}
        for terminal in flow.terminals:
            assertion = self._actionable_assertion(terminal.address, chain, observed_at)
            if assertion is None:
                continue
            grouped.setdefault(assertion.entity.id, []).append((terminal, assertion))

        candidates = [self._candidate(entity_id, terminals, allocation_index, flow.seed_amount, flow.seed_timestamp) for entity_id, terminals in grouped.items()]
        candidates = [candidate for candidate in candidates if candidate is not None]
        candidates.sort(key=self._display_key)
        nearest = min(candidates, key=lambda item: (item.min_hops, -item.attributed_amount, item.id)).id if candidates else None
        largest = max(candidates, key=lambda item: (item.attributed_amount, -item.min_hops, item.id)).id if candidates else None
        warnings = list(flow.warnings)
        if not candidates:
            warnings.append("NO_ACTIONABLE_VASP_ENDPOINT")
        return AttributionSummaryV2(
            candidates=candidates,
            nearest_actionable_candidate_id=nearest,
            largest_material_candidate_id=largest,
            unresolved_amount=flow.unresolved_amount,
            warnings=sorted(set(warnings)),
        )

    def _actionable_assertion(self, address: str, chain: str, observed_at: datetime) -> ResolvedEntityAssertion | None:
        for resolved in self.resolver.resolve(address, chain, observed_at):
            assertion = resolved.assertion
            if resolved.effective_review_state != AssertionReviewState.REVIEWED or assertion.role not in ACTIONABLE_ROLES:
                continue
            score, _ = self._score([resolved], observed_at)
            if assertion.assertion_type == AssertionType.VERIFIED:
                return resolved
            if assertion.assertion_type in {AssertionType.RULE_INFERRED, AssertionType.ML_INFERRED} and score >= self.config.inferred_actionable_threshold:
                return resolved
        return None

    def _candidate(self, entity_id: str, terminal_pairs: list[tuple[object, ResolvedEntityAssertion]], allocations: dict[str, FlowAllocationV2], seed_amount: Decimal, flow_seed_timestamp: datetime) -> AttributionCandidateV2 | None:
        first = terminal_pairs[0][1]
        assertions = self._all_entity_assertions(first, terminal_pairs)
        score, components = self._score(assertions, datetime.now(timezone.utc))
        status = self._status(assertions, score)
        if status == CandidateStatus.UNRESOLVED:
            return None
        terminal_addresses = sorted({terminal.address for terminal, _ in terminal_pairs})
        roles = sorted({item.assertion.role for item in assertions}, key=lambda item: item.value)
        amount = sum((terminal.amount for terminal, _ in terminal_pairs), Decimal("0"))
        paths: set[str] = set()
        endpoint_times: list[datetime] = []
        for terminal, _ in terminal_pairs:
            for allocation_id in terminal.parent_allocation_ids:
                if allocation_id in allocations:
                    endpoint_times.append(allocations[allocation_id].timestamp)
                lineage = self._lineage(allocation_id, allocations)
                if lineage:
                    paths.add(f"PATH-{canonical_sha256(lineage)[:20].upper()}")
        evidence_ids = sorted({value for item in assertions for value in (item.assertion.id, item.source.id, item.assertion.evidence_hash_sha256)})
        min_hops = min((terminal.depth for terminal, _ in terminal_pairs), default=0)
        band = self._band(score)
        candidate_id = f"CAND-{canonical_sha256({'entity_id': entity_id, 'addresses': terminal_addresses, 'paths': sorted(paths)})[:20].upper()}"
        return AttributionCandidateV2(
            id=candidate_id,
            entity_id=entity_id,
            entity_name=first.entity.canonical_name,
            terminal_addresses=terminal_addresses,
            terminal_roles=roles,
            status=status,
            min_hops=min_hops,
            attributed_amount=amount,
            disputed_share=(amount / seed_amount) if seed_amount else Decimal("0"),
            first_arrival=min(endpoint_times) if endpoint_times else None,
            latest_arrival=max(endpoint_times) if endpoint_times else None,
            path_ids=sorted(paths),
            evidence_ids=evidence_ids,
            attribution_evidence=components,
            attribution_evidence_score=score,
            attribution_band=band,
            materiality={
                "attributed_amount": str(amount),
                "share_of_seed": str((amount / seed_amount) if seed_amount else Decimal("0")),
                "min_hops": min_hops,
                "path_count": len(paths),
                "time_to_endpoint_seconds": int((min(endpoint_times) - flow_seed_timestamp).total_seconds()) if endpoint_times else None,
            },
        )

    def _all_entity_assertions(self, representative: ResolvedEntityAssertion, pairs: list[tuple[object, ResolvedEntityAssertion]]) -> list[ResolvedEntityAssertion]:
        resolved: dict[str, ResolvedEntityAssertion] = {}
        for terminal, _ in pairs:
            for item in self.resolver.resolve(terminal.address, representative.assertion.chain.value):
                if item.entity.id == representative.entity.id and item.effective_review_state == AssertionReviewState.REVIEWED:
                    resolved[item.assertion.id] = item
        return list(resolved.values())

    def _score(self, assertions: list[ResolvedEntityAssertion], observed_at: datetime) -> tuple[int, AttributionEvidenceComponents]:
        exact = self.config.exact_reviewed_label_max if any(item.assertion.assertion_type == AssertionType.VERIFIED and item.effective_review_state == AssertionReviewState.REVIEWED for item in assertions) else 0
        rule_components = [item.assertion.evidence_components for item in assertions if item.assertion.assertion_type in {AssertionType.RULE_INFERRED, AssertionType.ML_INFERRED}]
        cluster = self.config.cluster_relationship_max if any(item.assertion.role == EntityRole.VASP_COLLECTOR for item in assertions) or any(component.get("direct_verified_collector", 0) > 0 for component in rule_components) else 0
        deposit_signals = ("outflow_concentration", "repeated_short_delay_sweep", "low_destination_diversity", "near_zero_post_sweep")
        deposit = self.config.deposit_behavior_max if any(any(component.get(signal, 0) > 0 for signal in deposit_signals) for component in rule_components) else 0
        sources = {item.source.id for item in assertions}
        corroboration = self.config.independent_corroboration_max if len(sources) > 1 or any(component.get("independent_corroboration", 0) > 0 for component in rule_components) else 0
        fresh = self.config.freshness_max if assertions and all(item.assertion.stale_after is None or item.assertion.stale_after > observed_at for item in assertions) else 0
        components = AttributionEvidenceComponents(exact_reviewed_label=exact, cluster_relationship=cluster, deposit_behavior=deposit, independent_corroboration=corroboration, freshness=fresh)
        return components.total, components

    def _status(self, assertions: list[ResolvedEntityAssertion], score: int) -> CandidateStatus:
        if any(item.assertion.assertion_type == AssertionType.VERIFIED for item in assertions):
            return CandidateStatus.VERIFIED
        if any(item.assertion.assertion_type in {AssertionType.RULE_INFERRED, AssertionType.ML_INFERRED} for item in assertions):
            return CandidateStatus.INFERRED_STRONG if score >= self.config.inferred_actionable_threshold else CandidateStatus.UNRESOLVED
        return CandidateStatus.UNRESOLVED

    def _band(self, score: int) -> EvidenceBand:
        if score >= self.config.strong_threshold:
            return EvidenceBand.STRONG
        if score >= self.config.moderate_threshold:
            return EvidenceBand.MODERATE
        return EvidenceBand.WEAK

    @staticmethod
    def _lineage(allocation_id: str, allocations: dict[str, FlowAllocationV2]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []

        def visit(current: str) -> None:
            if current in seen or current not in allocations:
                return
            seen.add(current)
            for parent in allocations[current].parent_allocation_ids:
                visit(parent)
            ordered.append(current)

        visit(allocation_id)
        return ordered

    @staticmethod
    def _display_key(candidate: AttributionCandidateV2) -> tuple:
        status_order = {CandidateStatus.VERIFIED: 0, CandidateStatus.INFERRED_STRONG: 1, CandidateStatus.INFERRED_WEAK: 2, CandidateStatus.UNRESOLVED: 3}
        return (status_order[candidate.status], candidate.min_hops, -candidate.attributed_amount, -candidate.attribution_evidence_score, candidate.id)