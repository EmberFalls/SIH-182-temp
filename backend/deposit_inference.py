"""Explainable rule-based inference for previously unlabeled VASP deposit wallets."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from statistics import median

from .canonical import canonical_sha256
from .domain import (
    AssertionReviewState,
    AssertionType,
    AssetRef,
    CanonicalTransfer,
    DepositInferenceResult,
    EntityRole,
    EntityType,
)
from .entity_resolution import EntityResolver


ZERO = Decimal("0")
TRUSTED_TARGET_ROLES = {
    EntityRole.VASP_DEPOSIT,
    EntityRole.VASP_HOT_WALLET,
    EntityRole.VASP_COLD_WALLET,
    EntityRole.VASP_COLLECTOR,
    EntityRole.CUSTODIAL_SERVICE,
}


@dataclass(frozen=True)
class DepositInferenceConfig:
    direct_verified_collector_weight: int = 30
    concentration_weight: int = 20
    repeated_sweep_weight: int = 15
    low_destination_diversity_weight: int = 10
    near_zero_post_sweep_weight: int = 10
    independent_corroboration_weight: int = 10
    fee_funder_weight: int = 5
    concentration_threshold: Decimal = Decimal("0.90")
    short_sweep_delay_seconds: int = 3600
    minimum_repeated_sweeps: int = 2
    maximum_destination_diversity: int = 2
    minimum_inference_score: int = 60
    maximum_inference_depth: int = 1


class DepositPatternResolver:
    """Uses only reviewed, verified target assertions to avoid circular inference."""

    def __init__(self, entity_resolver: EntityResolver, config: DepositInferenceConfig | None = None) -> None:
        self.entity_resolver = entity_resolver
        self.config = config or DepositInferenceConfig()

    def infer(self, address: str, asset: AssetRef, transfers: list[CanonicalTransfer], observed_at: datetime | None = None, inference_depth: int = 0) -> list[DepositInferenceResult]:
        if inference_depth > self.config.maximum_inference_depth:
            return []
        observed_at = observed_at or datetime.now(timezone.utc)
        normalized = address.lower() if address.startswith("0x") else address
        relevant = [item for item in transfers if item.asset == asset]
        incoming = sorted((item for item in relevant if item.destination_address == normalized), key=lambda item: (item.timestamp, item.id))
        outgoing = sorted((item for item in relevant if item.source_address == normalized), key=lambda item: (item.timestamp, item.id))
        if not outgoing:
            return []
        targets: dict[str, list[tuple[CanonicalTransfer, object]]] = {}
        for transfer in outgoing:
            for assertion in self._trusted_targets(transfer.destination_address, asset.chain.value, observed_at):
                targets.setdefault(assertion.entity.id, []).append((transfer, assertion))

        results: list[DepositInferenceResult] = []
        for entity_id, directed in targets.items():
            entity = directed[0][1].entity
            target_outflow = sum((transfer.normalized_amount for transfer, _ in directed), ZERO)
            total_outflow = sum((transfer.normalized_amount for transfer in outgoing), ZERO)
            concentration = (target_outflow / total_outflow) if total_outflow else ZERO
            delays = self._receipt_to_sweep_delays(incoming, [item[0] for item in directed])
            source_ids = {assertion.source.id for _, assertion in directed}
            components = {
                "direct_verified_collector": self.config.direct_verified_collector_weight,
                "outflow_concentration": self.config.concentration_weight if concentration >= self.config.concentration_threshold else 0,
                "repeated_short_delay_sweep": self.config.repeated_sweep_weight if len(delays) >= self.config.minimum_repeated_sweeps and median(delays) <= self.config.short_sweep_delay_seconds else 0,
                "low_destination_diversity": self.config.low_destination_diversity_weight if len({item.destination_address for item in outgoing}) <= self.config.maximum_destination_diversity else 0,
                "near_zero_post_sweep": 0,
                "independent_corroboration": self.config.independent_corroboration_weight if len(source_ids) > 1 else 0,
                "fee_funder": 0,
            }
            score = sum(components.values())
            if score < self.config.minimum_inference_score:
                continue
            feature_snapshot = {
                "incoming_transaction_count": len(incoming),
                "outgoing_transaction_count": len(outgoing),
                "unique_senders": len({item.source_address for item in incoming}),
                "unique_receivers": len({item.destination_address for item in outgoing}),
                "total_inflow": str(sum((item.normalized_amount for item in incoming), ZERO)),
                "total_outflow": str(total_outflow),
                "target_entity_outflow": str(target_outflow),
                "outflow_concentration": str(concentration),
                "receipt_to_sweep_delay_seconds": delays,
                "median_receipt_to_sweep_delay_seconds": median(delays) if delays else None,
                "sweep_amount_ratio": str((target_outflow / sum((item.normalized_amount for item in incoming), ZERO)) if incoming else ZERO),
                "post_sweep_balance_available": False,
                "stablecoin_share": "1" if asset.symbol in {"USDT", "USDC", "DAI", "FDUSD", "TUSD"} else "0",
                "active_days": len({item.timestamp.date().isoformat() for item in incoming + outgoing}),
                "target_assertion_sources": sorted(source_ids),
            }
            reasons = self._reasons(components, entity.canonical_name, concentration, delays)
            lineage = sorted({value for _, assertion in directed for value in (assertion.assertion.id, assertion.source.id, assertion.assertion.evidence_hash_sha256)})
            result_id = f"INF-{canonical_sha256({'address': normalized, 'entity': entity_id, 'lineage': lineage, 'features': feature_snapshot})[:24].upper()}"
            results.append(DepositInferenceResult(
                id=result_id, address=normalized, asset=asset, candidate_entity_id=entity_id, candidate_entity_name=entity.canonical_name,
                evidence_score=score, evidence_components=components, feature_snapshot=feature_snapshot, reasons=reasons,
                evidence_lineage_ids=lineage, inference_depth=inference_depth, created_at=observed_at,
            ))
        return sorted(results, key=lambda item: (-item.evidence_score, item.candidate_entity_name, item.id))

    def _trusted_targets(self, address: str, chain: str, observed_at: datetime):
        for resolved in self.entity_resolver.resolve(address, chain, observed_at):
            assertion = resolved.assertion
            if (
                resolved.entity.entity_type == EntityType.VASP
                and assertion.assertion_type == AssertionType.VERIFIED
                and resolved.effective_review_state == AssertionReviewState.REVIEWED
                and assertion.role in TRUSTED_TARGET_ROLES
            ):
                yield resolved

    @staticmethod
    def _receipt_to_sweep_delays(incoming: list[CanonicalTransfer], targeted_outgoing: list[CanonicalTransfer]) -> list[int]:
        delays: list[int] = []
        used_outgoing: set[str] = set()
        for receipt in incoming:
            sweep = next((item for item in targeted_outgoing if item.id not in used_outgoing and item.timestamp >= receipt.timestamp), None)
            if sweep is None:
                continue
            used_outgoing.add(sweep.id)
            delays.append(int((sweep.timestamp - receipt.timestamp).total_seconds()))
        return delays

    @staticmethod
    def _reasons(components: dict[str, int], entity_name: str, concentration: Decimal, delays: list[int]) -> list[str]:
        reasons: list[str] = []
        if components["direct_verified_collector"]:
            reasons.append(f"Observed direct outgoing transfer(s) to a reviewed, verified {entity_name} endpoint.")
        if components["outflow_concentration"]:
            reasons.append(f"{concentration * 100}% of observed outgoing value concentrates toward that verified VASP entity.")
        if components["repeated_short_delay_sweep"]:
            reasons.append(f"Observed {len(delays)} receipt-to-sweep sequence(s) with a short median delay.")
        if components["low_destination_diversity"]:
            reasons.append("Observed outbound transfers have low destination diversity.")
        if components["independent_corroboration"]:
            reasons.append("The target entity is supported by multiple independent reviewed sources.")
        return reasons

def persist_unreviewed_inference(store, inference: DepositInferenceResult):
    """Persist rule evidence and an unreviewed assertion; never auto-promote it."""
    from .domain import (
        AssertionReviewState,
        EntityAddressAssertionCreate,
        IntelligenceSourceCreate,
        IntelligenceSourceType,
        TrustTier,
    )

    store.save_deposit_inference(inference)
    marker = f"deposit_inference_id={inference.id}"
    existing = [item for item in store.list_entity_address_assertions(inference.address, inference.asset.chain.value) if item.entity_id == inference.candidate_entity_id and item.notes and marker in item.notes]
    if existing:
        return existing[0]
    source = store.create_intelligence_source(IntelligenceSourceCreate(
        name=f"Deposit-pattern rule inference {inference.id}",
        source_type=IntelligenceSourceType.RULE_ENGINE,
        trust_tier=TrustTier.D,
        retrieved_at=inference.created_at,
        notes=f"{marker}; verified evidence lineage: {', '.join(inference.evidence_lineage_ids)}",
    ))
    return store.create_entity_address_assertion(EntityAddressAssertionCreate(
        entity_id=inference.candidate_entity_id,
        address=inference.address,
        chain=inference.asset.chain,
        role=inference.inferred_role,
        assertion_type=inference.assertion_type,
        source_id=source.id,
        review_state=AssertionReviewState.UNREVIEWED,
        evidence_score=inference.evidence_score,
        evidence_components=inference.evidence_components,
        notes=f"{marker}; rule inference remains unreviewed. " + " | ".join(inference.reasons),
    ))