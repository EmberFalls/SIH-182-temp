"""Evidence-first actionability assessment for VASP request preparation.

The assessment intentionally reports bounded amounts and unmet evidence conditions. It
never turns a score into a probability or an automatic freezing instruction.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Protocol
import uuid

from pydantic import BaseModel, Field

from .canonical import canonical_sha256
from .domain import (
    AssertionReviewState, AttributionCandidateV2, CandidateStatus, DataMode,
    InvestigationResultV2, SeedPrecision, TerminalReason,
)
from .models import Chain


class VaspRouteState(str, Enum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    UNCONFIGURED = "UNCONFIGURED"


class ActionRecommendation(str, Enum):
    READY_FOR_LOCAL_DRAFT = "READY_FOR_LOCAL_DRAFT"
    COLLECT_MORE_EVIDENCE = "COLLECT_MORE_EVIDENCE"
    DO_NOT_ROUTE = "DO_NOT_ROUTE"


class ChallengeSeverity(str, Enum):
    BLOCKER = "BLOCKER"
    MATERIAL = "MATERIAL"
    INFORMATIONAL = "INFORMATIONAL"


class VaspReadinessProfileCreateV2(BaseModel):
    entity_id: str
    supported_chains: list[Chain] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=lambda: [
        "case_reference", "legal_authority", "transaction_hashes", "wallet_addresses",
        "asset", "attributed_amount", "evidence_manifest_hash",
    ])
    local_contact_route: str | None = Field(default=None, max_length=500)
    template_version: str = Field(default="local-v1", min_length=2, max_length=80)
    review_state: AssertionReviewState = AssertionReviewState.UNREVIEWED
    notes: str | None = Field(default=None, max_length=2000)


class VaspReadinessProfileV2(VaspReadinessProfileCreateV2):
    id: str
    created_at: datetime
    evidence_hash_sha256: str = Field(min_length=64, max_length=64)


class EvidenceChallengeV2(BaseModel):
    code: str
    severity: ChallengeSeverity
    claim: str
    impact: str
    resolution: str
    evidence_ids: list[str] = Field(default_factory=list)


class NextBestEvidenceV2(BaseModel):
    priority: int = Field(ge=1)
    action: str
    expected_effect: str
    resolves_challenge_codes: list[str]


class FreezeabilityEnvelopeV2(BaseModel):
    confirmed_attributed_amount: Decimal = Field(ge=0)
    model_attributed_amount: Decimal = Field(ge=0)
    maximum_request_amount: Decimal = Field(ge=0)
    unresolved_case_amount: Decimal = Field(ge=0)
    statement: str


class CandidateActionabilityV2(BaseModel):
    candidate_id: str
    entity_id: str
    entity_name: str
    recommendation: ActionRecommendation
    route_state: VaspRouteState
    envelope: FreezeabilityEnvelopeV2
    challenges: list[EvidenceChallengeV2]
    next_best_evidence: list[NextBestEvidenceV2]
    readiness_profile_id: str | None = None
    readiness_notes: list[str] = Field(default_factory=list)


class ActionabilityAssessmentV2(BaseModel):
    result_id: str
    data_mode: DataMode
    generated_at: datetime
    candidates: list[CandidateActionabilityV2]
    methodology: str


class ActionabilityStore(Protocol):
    def get_vasp_readiness_profile_v2(self, entity_id: str) -> VaspReadinessProfileV2 | None: ...


class ActionabilityEngineV2:
    VERSION = "actionability-v1"

    def __init__(self, store: ActionabilityStore) -> None:
        self.store = store

    def assess(self, result: InvestigationResultV2) -> ActionabilityAssessmentV2:
        return ActionabilityAssessmentV2(
            result_id=result.id,
            data_mode=result.data_mode,
            generated_at=datetime.now(timezone.utc),
            candidates=[self._candidate(result, candidate) for candidate in result.attribution.candidates],
            methodology=(
                "Confirmed amount is the case-attributed value reaching an evidence-backed endpoint. "
                "Maximum request amount is zero whenever a blocking condition remains. This is an "
                "investigative preparation assessment, never an automatic freeze decision."
            ),
        )

    def _candidate(self, result: InvestigationResultV2, candidate: AttributionCandidateV2) -> CandidateActionabilityV2:
        profile = self.store.get_vasp_readiness_profile_v2(candidate.entity_id)
        challenges: list[EvidenceChallengeV2] = []
        if result.data_mode == DataMode.SYNTHETIC:
            challenges.append(self._challenge("SYNTHETIC_DATA", ChallengeSeverity.BLOCKER,
                "This result uses synthetic demonstration data.", "Synthetic evidence cannot support an operational request.",
                "Replay a recorded-real or live case before preparing a request."))
        if candidate.status != CandidateStatus.VERIFIED:
            challenges.append(self._challenge("UNVERIFIED_ENDPOINT", ChallengeSeverity.BLOCKER,
                "The endpoint is inferred rather than a reviewed verified VASP assertion.",
                "An inferred endpoint cannot be routed as a verified VASP destination.",
                "Obtain and review an independent VASP address assertion."))
        if result.flow.seed_precision == SeedPrecision.APPROXIMATE:
            challenges.append(self._challenge("APPROXIMATE_SEED", ChallengeSeverity.MATERIAL,
                "The trace began from a wallet-context amount rather than a specific disputed transaction.",
                "The model amount is useful for triage but has weaker evidentiary precision.",
                "Replay from the originating transaction hash and its canonical transfer event."))
        if any(item.incoming_unknown_balance > 0 for item in result.flow.allocations):
            challenges.append(self._challenge("MIXED_BALANCE", ChallengeSeverity.MATERIAL,
                "One or more traced wallets had unknown historical balance at an outgoing transfer.",
                "A pre-existing balance could change the allocation applied to the outgoing transaction.",
                "Retrieve earlier wallet history or an exact historical balance snapshot."))
        if "PARTIAL_PROVIDER_DATA" in result.flow.warnings or any(item.reason == TerminalReason.UNKNOWN for item in result.flow.terminals):
            challenges.append(self._challenge("PARTIAL_PROVIDER_COVERAGE", ChallengeSeverity.MATERIAL,
                "Provider retrieval was incomplete for part of the trace.", "Unseen transactions may affect the case-flow accounting.",
                "Retry provider retrieval or import a recorded evidence package covering the missing period."))
        if any(item.reason == TerminalReason.BRIDGE_UNRESOLVED for item in result.flow.terminals):
            challenges.append(self._challenge("UNRESOLVED_BRIDGE", ChallengeSeverity.MATERIAL,
                "A bridge boundary lacks an exact source-to-destination message link.", "Value beyond the bridge cannot be attributed to this endpoint.",
                "Collect the source and destination bridge events with their exact shared message identifier."))

        route_state, readiness_notes = self._route_state(profile, result.transfers[0].chain if result.transfers else None)
        if route_state != VaspRouteState.READY:
            challenges.append(self._challenge("ROUTING_PROFILE_INCOMPLETE", ChallengeSeverity.MATERIAL,
                "No reviewed local VASP routing profile covers this endpoint and chain.",
                "The evidence may be ready, but the correct local request packet is not configured.",
                "Configure and review the local VASP readiness profile before routing."))

        blockers = [item for item in challenges if item.severity == ChallengeSeverity.BLOCKER]
        confirmed = candidate.attributed_amount if candidate.status == CandidateStatus.VERIFIED else Decimal("0")
        maximum = confirmed if not blockers and route_state == VaspRouteState.READY else Decimal("0")
        if blockers:
            recommendation = ActionRecommendation.DO_NOT_ROUTE
        elif maximum > 0:
            recommendation = ActionRecommendation.READY_FOR_LOCAL_DRAFT
        else:
            recommendation = ActionRecommendation.COLLECT_MORE_EVIDENCE
        next_steps = self._next_steps(challenges)
        return CandidateActionabilityV2(
            candidate_id=candidate.id, entity_id=candidate.entity_id, entity_name=candidate.entity_name,
            recommendation=recommendation, route_state=route_state,
            envelope=FreezeabilityEnvelopeV2(
                confirmed_attributed_amount=confirmed,
                model_attributed_amount=candidate.attributed_amount,
                maximum_request_amount=maximum,
                unresolved_case_amount=result.flow.unresolved_amount + result.flow.retained_amount,
                statement=(
                    "Maximum request amount is the confirmed case-attributed value only when all blockers are cleared and a reviewed local routing profile is available."
                    if maximum > 0 else
                    "No request amount is proposed until the blocking evidence or routing conditions are resolved."
                ),
            ),
            challenges=challenges, next_best_evidence=next_steps,
            readiness_profile_id=profile.id if profile else None, readiness_notes=readiness_notes,
        )

    @staticmethod
    def _challenge(code: str, severity: ChallengeSeverity, claim: str, impact: str, resolution: str) -> EvidenceChallengeV2:
        return EvidenceChallengeV2(code=code, severity=severity, claim=claim, impact=impact, resolution=resolution)

    @staticmethod
    def _route_state(profile: VaspReadinessProfileV2 | None, chain: Chain | None) -> tuple[VaspRouteState, list[str]]:
        if not profile:
            return VaspRouteState.UNCONFIGURED, ["No local routing profile has been registered for this VASP entity."]
        if profile.review_state != AssertionReviewState.REVIEWED:
            return VaspRouteState.PARTIAL, ["The local routing profile exists but has not been reviewed."]
        chains = {chain.value for chain in profile.supported_chains}
        if chains and chain and chain.value not in chains:
            return VaspRouteState.PARTIAL, ["The reviewed profile does not list the candidate chain."]
        if not profile.local_contact_route:
            return VaspRouteState.PARTIAL, ["The reviewed profile has no local contact route."]
        return VaspRouteState.READY, [f"Reviewed local profile {profile.template_version} covers this routing decision."]

    @staticmethod
    def _next_steps(challenges: list[EvidenceChallengeV2]) -> list[NextBestEvidenceV2]:
        seen: set[str] = set()
        steps: list[NextBestEvidenceV2] = []
        for challenge in sorted(challenges, key=lambda item: (0 if item.severity == ChallengeSeverity.BLOCKER else 1, item.code)):
            if challenge.resolution in seen:
                continue
            seen.add(challenge.resolution)
            steps.append(NextBestEvidenceV2(
                priority=len(steps) + 1, action=challenge.resolution,
                expected_effect=challenge.impact, resolves_challenge_codes=[challenge.code],
            ))
        return steps


def new_vasp_readiness_profile_v2(payload: VaspReadinessProfileCreateV2, created_at: datetime | None = None) -> VaspReadinessProfileV2:
    created_at = created_at or datetime.now(timezone.utc)
    body = {"payload": payload, "created_at": created_at}
    return VaspReadinessProfileV2(
        id=f"VASP-ROUTE-{uuid.uuid4().hex[:12].upper()}", created_at=created_at,
        evidence_hash_sha256=canonical_sha256(body), **payload.model_dump(),
    )


