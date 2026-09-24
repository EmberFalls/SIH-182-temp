from decimal import Decimal
import math

from .models import FlowAnalysis, VaspCandidate


class AttributionEngine:
    """Ranks only source-backed VASP endpoints that received case-attributed value."""

    def rank(self, candidates: list[VaspCandidate], flow: FlowAnalysis) -> list[VaspCandidate]:
        allocations = {(item.transaction_hash.lower(), item.destination_address.lower()): item.attributed_amount for item in flow.allocations}
        grouped: dict[tuple[str, str, int], tuple[VaspCandidate, Decimal, Decimal]] = {}
        for candidate in candidates:
            amount = allocations.get((candidate.supporting_transaction.lower(), candidate.address.lower()), Decimal("0"))
            if amount <= 0:
                continue
            key = (candidate.label_id, candidate.address.lower(), candidate.hop)
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = (candidate, amount, amount)
                continue
            representative, total_amount, largest_transfer = existing
            if amount > largest_transfer:
                representative = candidate
                largest_transfer = amount
            grouped[key] = (representative, total_amount + amount, largest_transfer)

        ranked: list[VaspCandidate] = []
        for candidate, amount, _ in grouped.values():
            label_strength = 1.0 if candidate.evidence_grade == "verified" else 0.75
            proximity = math.exp(-0.45 * max(candidate.hop - 1, 0))
            flow_share = min(float(amount / flow.starting_amount), 1.0) if flow.starting_amount > 0 else 0.0
            score = round(100 * (0.55 * label_strength + 0.30 * proximity + 0.15 * flow_share), 1)
            ranked.append(candidate.model_copy(update={
                "attributed_amount": amount, "priority_score": score,
                "ranking_reason": f"{candidate.evidence_grade.capitalize()} address label; observed at hop {candidate.hop}; {amount} of the case-derived token balance reached this endpoint. Supporting transaction records are retained in the evidence manifest.",
            }))
        return sorted(ranked, key=lambda item: (-item.priority_score, item.hop, -item.attributed_amount))
