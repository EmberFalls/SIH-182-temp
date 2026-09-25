# Repository Audit — Phase 0

**Date:** 2026-09-25
**Scope:** Baseline audit before implementing `SIH26182_IMPLEMENTATION_BLUEPRINT.md`.

## Baseline verification

The current prototype was inspected before architectural changes.

| Check | Result |
| --- | --- |
| Test command | `E:\Python\python.exe -m pytest -q -p no:cacheprovider` with `TEMP` and `TMP` set to `.test-tmp` |
| Result | **11 passed** in 0.62 seconds |
| Warning | Starlette's current `TestClient` usage emits one upstream deprecation warning. |
| Standard test command caveat | The host-owned default pytest temp directory is inaccessible to the sandbox account. This is an environment permission issue; the isolated workspace-temp run passes. |
| Working local demo | `POST /demo/scenarios/multihop-deposit-sweep` returns an explicitly marked `SIMULATED_DEMO` Ethereum three-hop path to a reviewed Binance address. |
| Live route | Ethereum, BNB Chain, Polygon through Etherscan V2-compatible calls; TRON through TronGrid. Both require configured API keys. |

## Current implementation map

### Backend and framework

- **Framework:** FastAPI and Pydantic v2 in `backend/app.py` and `backend/models.py`.
- **Persistence:** SQLite JSON-payload store in `backend/storage.py`. A separate, currently unused PostgreSQL starter schema is in `deployment/postgres_schema.sql`.
- **Provider clients:** `backend/ethereum.py` normalizes outbound ERC-20 transfers from Etherscan V2-compatible APIs. `backend/tron.py` normalizes outbound TRC-20 transfers from TronGrid.
- **Trace orchestration:** `backend/tracing.py` performs bounded downstream wallet traversal and produces graph, path, provider-provenance, limitation, and manifest data.
- **Flow and attribution:** `backend/flow.py` assigns case funds by conservative FIFO. `backend/attribution.py` ranks reviewed labeled endpoints.
- **Supporting intelligence:** `backend/risk.py`, `backend/cross_case.py`, and `backend/cross_chain.py` provide scoped alerts and explicit bridge boundaries.
- **Operations:** PDF report in `backend/reports.py`; local draft-only SAHYOG packet in `backend/sahyog.py`; optional bearer authentication, roles, and rate limiting in `backend/security.py`.

### Frontend

- **Framework:** Static HTML/CSS/JavaScript served by FastAPI.
- **Primary files:** `frontend/index.html`, `frontend/static/app.js`, `frontend/static/graph.js`, and `frontend/static/styles.css`.
- **Graph:** Locally bundled Cytoscape.js. It displays trace edges, shortest supporting VASP paths, node/edge evidence, and trace frontiers.
- **Current workflow:** Create/select case → run trace → inspect candidates/graph/evidence → inspect limitations → verify manifest → create a local draft if permitted.

### Current API surface

| Area | Endpoints |
| --- | --- |
| Health and UI | `GET /health`, `GET /` |
| Cases | `POST /cases`, `GET /cases`, `GET/PATCH /cases/{case_id}`, case notes |
| Labels | create/list/import/review labels and retrieve label-review history |
| Tracing | synchronous trace, in-memory trace jobs, trace-run retrieval |
| Evidence | evidence package, manifest verification, PDF report, challenge simulation |
| Operational boundary | local SAHYOG draft generation only |
| Demonstration | `POST /demo/scenarios/multihop-deposit-sweep` |

### Existing domain representation

| Blueprint concept | Current representation | Audit finding |
| --- | --- | --- |
| Case | `CaseCreate`, `CaseSummary` | Wallet-seeded only. It has chain, token, amount, and incident window, but no seed transaction, asset identity, trace policy, or data-mode field on the case. |
| Chain | `Chain` enum | EVM and TRON paths work through adapters; Bitcoin and Solana deliberately return unavailable. |
| Transfer | `TransferEvidence` | Already uses `Decimal`, source/destination, token contract, time, block, confirmation, provider, and retrieval time. It lacks a canonical transfer ID, transaction entity, event/log index, transfer type, and raw-evidence reference. |
| Flow allocation | `FlowAllocation`, `FlowAnalysis` | Uses deterministic FIFO and tracks starting, allocated, and unallocated source value. It does not represent parent allocations, mixed balances, or a configurable allocation policy. |
| Entity label | `VaspLabel` | Has source URL/name/time, reviewer, expiry, review state, role-like label type, and conflict behavior. It is still one flat address label rather than an entity, source, and assertion registry. |
| Candidate | `VaspCandidate` | Has address, hop, attributed amount, supporting transaction, and a blended ranking score. It does not separate attribution evidence strength from flow materiality or expose explicit candidate state. |
| Evidence | transfer fields, provenance events, manifest hash/payload | Good starting point. Raw provider payloads, evidence artifacts, request fingerprints, and versioned result snapshots do not yet persist independently. |
| Result snapshot | persisted `TraceResult` JSON | A saved trace is present and hash-verifiable. There is no explicit versioned `InvestigationResult`, trace fingerprint, or canonical schema/version set. |

### Data, demo, reports, and deployment

- `demo/reviewed_ethereum_labels.json` contains a small reviewed public-source label pack and `scripts/import_label_pack.py` imports it idempotently by name/source URL.
- `backend/demo.py` creates a fixed synthetic three-hop scenario and clearly marks it `SIMULATED_DEMO`.
- `backend/reports.py` renders directly from a saved trace run; it does not claim real SAHYOG submission.
- Docker includes an API and PostgreSQL service, but the running application is still SQLite-backed and does not use the supplied PostgreSQL schema.

## Current tracing behavior

1. Start from a case wallet.
2. Retrieve outbound matching token transfers for each frontier wallet.
3. Bound work by hop count, wallet count, transfer count, provider pages, and incident window.
4. Mark a destination as a VASP only when a current reviewed local address label exists.
5. Allocate case value after traversal using a FIFO available-balance ledger.
6. Rank source-backed VASP receipts and build shortest supporting paths.
7. Save a JSON trace result with a deterministic hash of its manifest.

This behavior is useful and should remain available during migration, but it is not yet the blueprint's disputed-fund tracing v2. It cannot begin from a specific disputed transaction, discover deposit infrastructure, maintain allocation lineage, or return a full accounting of all branch terminals.

## Architectural risks and contradictions with the blueprint

1. **Seed precision:** the current case schema is wallet-only. Blueprint v2 requires a transaction seed as the preferred input and must mark wallet-context input as less precise.
2. **Allocation policy:** existing FIFO allocation is deterministic but differs from the blueprint's default proportional haircut policy. It also needs merge, split, cycle, and conservation-invariant coverage.
3. **Traversal versus tracing:** current traversal retrieves transfers before fund allocation, which can pull in irrelevant activity. V2 needs event-driven flow propagation.
4. **Entity registry:** current labels cannot represent multiple assertions, independent sources, assertion class (`VERIFIED`, `RULE_INFERRED`, `ML_INFERRED`), an entity cluster, or reversible entity relationships.
5. **Score semantics:** `priority_score` blends label grade, hop distance, and amount. Blueprint v2 requires separate attribution-evidence score and flow-materiality fields; no uncalibrated probability display.
6. **Candidate coverage:** candidates are known labeled receipt addresses only. Rule-based inference for previously unlabeled deposit wallets is absent.
7. **Evidence preservation:** normalized transfer facts and manifest are stored, but raw provider responses and independent evidence artifacts are not preserved.
8. **Result versioning and replay:** stored runs are immutable in practice but have no trace fingerprint, algorithm/config versions, recorded-real replay provider, or explicit result-version model.
9. **Data modes:** current values are `LIVE_CONFIRMED` and `SIMULATED_DEMO`. Blueprint v2 requires a common public contract: `LIVE`, `RECORDED_REAL`, and `SYNTHETIC`.
10. **Operational gate:** the frontend blocks inappropriate draft actions, but backend draft generation should enforce all actionability requirements itself, including live data mode and investigator review.
11. **Async jobs:** trace jobs are process-local and unsuitable for durable long-running execution; this is acceptable for the baseline but must be isolated behind a job interface.
12. **Deployment mismatch:** PostgreSQL schema and Docker exist, but the application repository does not implement PostgreSQL persistence.

## Blueprint mapping by repository file

| Current file | Blueprint phase / target responsibility |
| --- | --- |
| `backend/models.py` | Phase 1 canonical domain and API schemas |
| `backend/ethereum.py`, `backend/tron.py` | Phase 1 provider adapter boundary and normalized transfer ingestion |
| `backend/tracing.py` | Phase 3 fund-flow engine v2, then Phase 5 result assembly |
| `backend/flow.py` | Phase 3 proportional allocation policies and invariants |
| `backend/storage.py` | Phase 2 persistence, Phase 4 registry, Phase 5 snapshots |
| `backend/attribution.py` | Phase 5 candidate assembly and separate evidence/materiality computation |
| `backend/cross_chain.py` | Phase 10 cross-chain edge and bridge resolver |
| `backend/demo.py` | Phase 7 recorded/synthetic robust demos |
| `backend/reports.py`, `backend/sahyog.py` | Phase 8 report and draft generated from a single result snapshot |
| `frontend/*` | Phase 7 evidence-first investigator workflow |
| `tests/*` | Baseline regression suite; expand with blueprint fixtures and invariants before each engine change |
| `deployment/*` | Future persistence deployment work after repository abstractions exist |

## Smallest safe Phase 1 change set

Phase 1 must preserve the current endpoints and demo. It should introduce new canonical models alongside the legacy response models, without replacing trace behavior yet.

1. Add explicit version constants and a canonical JSON hashing helper.
2. Add `DataMode`, `SeedType`, `AssertionType`, and terminal-reason enums.
3. Add canonical `AssetRef`, `CanonicalTransaction`, `CanonicalTransfer`, and an extended case-context model that supports both transaction and wallet-context seeds.
4. Add a provider-adapter protocol and adapter result object that carries normalized transfers plus raw-evidence metadata, while wrapping the existing Etherscan and TronGrid clients.
5. Add tests for EVM/TRON normalization, decimal preservation, address normalization, and stable canonical hashing.
6. Do not change the frontend, replace FIFO allocation, add ML, add cross-chain flow continuation, or migrate SQLite in Phase 1.

## Baseline preservation requirements

- Retain existing `POST /cases`, trace, graph, report, manifest verification, and demo behavior while introducing v2 behind an explicit feature boundary.
- Keep synthetic evidence visibly synthetic at every API and UI layer.
- Preserve existing reviewed labels and source/reviewer/expiry behavior during assertion-model migration.
- Keep Bitcoin and Solana explicitly unavailable until supported adapters exist.
- Do not add external SAHYOG access, scraping, or simulated successful submission behavior.

## Phase 0 outcome

The repository is suitable for incremental evolution. A rewrite is not justified. The safe next step is **Phase 1 — Canonical domain model and provider-normalization boundary**, with regression tests added first.
