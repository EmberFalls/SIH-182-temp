# Phase 8 Result and Local Export Boundary

## Source of truth

Every v2 report, evidence-manifest response, and local request draft is derived from a persisted `InvestigationResultV2` snapshot. The snapshot records the fund-flow accounting, candidate endpoints, path IDs, evidence IDs, inference records, limitations, and versioned algorithm identifiers.

The manifest is canonical JSON and carries a SHA-256 hash. It checks the integrity of the saved evidence references; it does not prove the truth of a provider or entity-label source.

## Data modes

`LIVE`, `RECORDED_REAL`, and `SYNTHETIC` are retained in the result. The included v2 scenario is `SYNTHETIC`; it is presentation data only. The server rejects attempts to generate an operational local draft from synthetic results.

## Local request export

`POST /v2/results/{result_id}/request-drafts` creates a `LOCAL_DRAFT_REQUIRES_AUTHORIZED_REVIEW` record. It never sends data to SAHYOG, a VASP, or any other external service.

A local draft requires:

- a non-synthetic result;
- a v2 case in `UNDER_REVIEW` status; and
- an evidence-supported actionable candidate.

It includes the selected endpoint, candidate amount, path-derived transfer IDs, transaction IDs, evidence IDs, manifest hash, purpose placeholder, and investigator notes. An authorized investigator must review, edit, approve, and submit it through the official lawful workflow.