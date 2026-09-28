# Full Enhancement Blueprint — Implementation Status

This document tracks the implementation of `VASP_TRACE_FULL_ENHANCEMENT_BLUEPRINT.md` against the current repository. It distinguishes delivered local capability from work that requires an approved production environment or third-party access.

## Delivered in the first enhancement milestone

### Trustworthy acquisition and canonicalisation

- Token decimals are accepted only from provider or investigator-supplied contract metadata. The canonical adapter no longer derives decimals from a displayed transfer amount.
- Token identity uses chain, asset type, contract or mint, and token standard. Symbols are display metadata, not asset identity.
- Recorded replay is network-isolated; its invalid provider-loading path has been removed.
- Canonical transfers retain block number, transaction/log ordering fields, parser name, parser version, and canonicalisation version.
- Provider artefacts retain secret-redacted request provenance, a raw response payload when supplied by the provider, and a content hash.
- Provider acquisition creates factual coverage records: complete, bounded, or provider-truncated. Result snapshots persist those records and the frontend renders them.

### Investigation workflow

- Trace jobs have durable local status, stage events, retry state, and cancellation requests.
- Cancellation prevents further allocation expansion and is never reported as a completed result.
- The investigation UI has a flat, case-focused shell. It exposes one primary intake action and moves imports, review, bridge evidence, history, and demonstration data into evidence tools.

### Evidence, collaboration, and case network

- Investigators can add immutable notes to a case or evidence target without changing provider evidence.
- Saved V2 results create exact, explainable cross-case links for shared addresses, transactions, and reviewed entities.
- Audit events are appended to a hash chain. Integrity verification checks the result fingerprint, manifest, retained raw-payload hashes, and audit continuity.
- Evidence-bundle export includes the case, immutable result, manifest, retained raw-evidence metadata, audit chain, and PDF report.

## Verified acceptance evidence

- Automated suite: **68 passed** at the time of this milestone.
- Frontend V2 script syntax check passes.
- Tests cover amount-decimal rejection, network-isolated replay, annotations, audit continuity, exact cross-case links, evidence integrity, evidence-bundle export, and safe queued-job cancellation.

## Next implementation gates

1. Historical balance adapters with exact, reconstructed-complete, partial, and unknown quality states.
2. PostgreSQL, object-storage, OIDC, RBAC, case isolation, and distributed worker deployment. These need deployment configuration and an identity/database environment.
3. Rich entity lifecycle: aliases, multi-source conflict state, assignments, expiry workflows, and VASP routing-template versioning.
4. Automatic bridge destination lookup, DEX/swap continuation, and protocol-specific adapters beyond the existing evidence-bound Wormhole path.
5. Permission-aware cross-case search and operation/case-group workflows after RBAC is active.
6. Dedicated Bitcoin and Solana engines, each with chain-appropriate data and accounting models.

The project does not claim these external or production-dependent capabilities before their data sources, infrastructure, and review controls are present.
