"""Construction of immutable Phase 8 investigation result snapshots."""
from __future__ import annotations

from datetime import datetime, timezone
import uuid

from .canonical import (
    ATTRIBUTION_ENGINE_VERSION,
    ENTITY_RESOLVER_VERSION,
    RESULT_SCHEMA_VERSION,
    TRACE_ENGINE_VERSION,
    canonical_sha256,
)
from .domain import (
    CanonicalTransfer,
    DepositInferenceResult,
    EvidenceManifestEntry,
    EvidenceManifestV2,
    FundFlowResultV2,
    InvestigationCaseV2,
    InvestigationResultV2,
    AttributionSummaryV2,
)
from .storage import Store


class InvestigationResultService:
    """Creates the single immutable record used by report and request-draft outputs."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def create(
        self,
        case: InvestigationCaseV2,
        flow: FundFlowResultV2,
        attribution: AttributionSummaryV2,
        transfers: list[CanonicalTransfer],
        deposit_inferences: list[DepositInferenceResult],
        limitations: list[str],
        generated_at: datetime | None = None,
    ) -> InvestigationResultV2:
        generated_at = generated_at or datetime.now(timezone.utc)
        trace_fingerprint = canonical_sha256({"case_context": case.context, "trace_policy": case.trace_policy, "transfers": transfers, "flow": flow, "attribution": attribution, "deposit_inference_ids": [item.id for item in deposit_inferences]})
        existing = self.store.get_investigation_result_by_fingerprint_v2(case.id, trace_fingerprint)
        if existing:
            return existing
        version = self.store.next_investigation_result_version(case.id)
        entries = self._evidence_entries(case, transfers, attribution, deposit_inferences)
        algorithm_versions = {
            "schema": RESULT_SCHEMA_VERSION,
            "tracer": TRACE_ENGINE_VERSION,
            "entity_resolver": ENTITY_RESOLVER_VERSION,
            "attribution": ATTRIBUTION_ENGINE_VERSION,
        }
        manifest_body = {
            "case_id": case.id,
            "result_version": version,
            "generated_at": generated_at,
            "algorithm_versions": algorithm_versions,
            "evidence": entries,
        }
        manifest = EvidenceManifestV2(**manifest_body, sha256=canonical_sha256(manifest_body))
        result = InvestigationResultV2(
            id=f"RESULT-{uuid.uuid4().hex[:16].upper()}",
            case_id=case.id,
            version=version,
            generated_at=generated_at,
            trace_fingerprint=trace_fingerprint,
            data_mode=case.context.data_mode,
            trace_engine_version=TRACE_ENGINE_VERSION,
            entity_resolver_version=ENTITY_RESOLVER_VERSION,
            attribution_engine_version=ATTRIBUTION_ENGINE_VERSION,
            flow=flow,
            transfers=transfers,
            attribution=attribution,
            deposit_inferences=deposit_inferences,
            evidence_manifest=manifest,
            limitations=sorted(set(limitations)),
            methodology={
                **flow.methodology,
                "result_schema": RESULT_SCHEMA_VERSION,
                "evidence_manifest": "Canonical JSON SHA-256 over the immutable snapshot evidence references.",
                "interpretation_boundary": "Attribution identifies evidence-supported custodial endpoints; it does not establish beneficial ownership or authorize a freeze.",
            },
        )
        return self.store.save_investigation_result_v2(result)

    def _evidence_entries(
        self,
        case: InvestigationCaseV2,
        transfers: list[CanonicalTransfer],
        attribution: AttributionSummaryV2,
        inferences: list[DepositInferenceResult],
    ) -> list[EvidenceManifestEntry]:
        mode_provider = "synthetic_fixture" if case.context.data_mode.value == "SYNTHETIC" else "normalized_chain_data"
        entries: dict[str, EvidenceManifestEntry] = {}
        for transfer in transfers:
            entries[f"transfer:{transfer.id}"] = EvidenceManifestEntry(
                id=f"transfer:{transfer.id}", kind="normalized_transfer", provider=mode_provider,
                sha256=canonical_sha256(transfer), retrieved_at=transfer.timestamp,
            )
            artifact = self.store.get_raw_evidence_artifact_v2(transfer.raw_evidence_id)
            entries[f"raw_evidence:{transfer.raw_evidence_id}"] = EvidenceManifestEntry(
                id=f"raw_evidence:{transfer.raw_evidence_id}",
                kind=artifact.kind if artifact else "transfer_evidence_reference",
                provider=artifact.provider if artifact else mode_provider,
                sha256=(artifact.content_hash_sha256 or artifact.request_fingerprint) if artifact else canonical_sha256({"raw_evidence_id": transfer.raw_evidence_id, "transfer_id": transfer.id}),
                retrieved_at=artifact.retrieved_at if artifact else transfer.timestamp,
                source_uri=artifact.source_uri if artifact else None,
            )
        for inference in inferences:
            entries[f"inference:{inference.id}"] = EvidenceManifestEntry(
                id=f"inference:{inference.id}", kind="rule_inference", provider="deposit_pattern_rule_engine",
                sha256=canonical_sha256(inference), retrieved_at=inference.created_at,
            )
            for lineage in inference.evidence_lineage_ids:
                self._add_registry_reference(entries, lineage)
        for candidate in attribution.candidates:
            for evidence_id in candidate.evidence_ids:
                self._add_registry_reference(entries, evidence_id)
        return sorted(entries.values(), key=lambda item: item.id)

    def _add_registry_reference(self, entries: dict[str, EvidenceManifestEntry], evidence_id: str) -> None:
        key = f"registry:{evidence_id}"
        if key in entries:
            return
        assertion = self.store.get_entity_address_assertion(evidence_id) if evidence_id.startswith("ASSERT-") else None
        if assertion:
            entries[key] = EvidenceManifestEntry(
                id=key, kind="entity_address_assertion", provider="entity_registry",
                sha256=assertion.evidence_hash_sha256, retrieved_at=assertion.created_at,
            )
            return
        source = self.store.get_intelligence_source(evidence_id) if evidence_id.startswith("SOURCE-") else None
        if source:
            entries[key] = EvidenceManifestEntry(
                id=key, kind="intelligence_source", provider=source.source_type.value,
                sha256=canonical_sha256(source), retrieved_at=source.retrieved_at, source_uri=source.source_uri,
            )
            return
        entries[key] = EvidenceManifestEntry(
            id=key, kind="evidence_reference", provider="entity_registry",
            sha256=evidence_id if len(evidence_id) == 64 else canonical_sha256({"evidence_id": evidence_id}),
        )