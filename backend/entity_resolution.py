"""Read-only resolver over provenance-backed entity assertions."""
from __future__ import annotations

from datetime import datetime

from .domain import AssertionReviewState, AssertionType, ResolvedEntityAssertion, TrustTier
from .storage import Store


class EntityResolver:
    """Separates stored assertions from the evidence-ranked resolver output."""

    _assertion_rank = {
        AssertionType.VERIFIED: 3,
        AssertionType.RULE_INFERRED: 2,
        AssertionType.ML_INFERRED: 1,
    }
    _tier_rank = {TrustTier.A: 4, TrustTier.B: 3, TrustTier.C: 2, TrustTier.D: 1}
    _review_rank = {
        AssertionReviewState.REVIEWED: 3,
        AssertionReviewState.UNREVIEWED: 2,
        AssertionReviewState.STALE: 1,
        AssertionReviewState.REJECTED: 0,
    }

    def __init__(self, store: Store) -> None:
        self.store = store

    def resolve(self, address: str, chain: str, at: datetime | None = None) -> list[ResolvedEntityAssertion]:
        resolved = self.store.resolve_entity_assertions(address, chain, at)
        return sorted(
            resolved,
            key=lambda item: (
                -self._review_rank[item.effective_review_state],
                -self._assertion_rank[item.assertion.assertion_type],
                -self._tier_rank[item.source.trust_tier],
                item.entity.canonical_name,
                item.assertion.id,
            ),
        )

    def best(self, address: str, chain: str, at: datetime | None = None) -> ResolvedEntityAssertion | None:
        return next(iter(self.resolve(address, chain, at)), None)