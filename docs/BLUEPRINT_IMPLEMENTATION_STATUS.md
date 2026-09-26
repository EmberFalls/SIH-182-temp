# Blueprint Implementation Status

This file records what the prototype can demonstrate today. It is deliberately narrower than a production claim.

| Blueprint area | Current implementation | Evidence / boundary |
| --- | --- | --- |
| Canonical case, asset, transfer, data mode | Implemented | V2 contracts retain `LIVE`, `RECORDED_REAL`, and `SYNTHETIC`, canonical transfer IDs, Decimal amounts, and a saved trace policy. |
| Provider normalization | Implemented for TRON, Ethereum, BNB Chain, and Polygon outbound token retrieval | The v2 runner uses the existing read-only explorer adapters. Bitcoin and Solana remain declared unavailable. |
| Transaction-seeded tracing | Implemented for recorded or synthetic evidence and live TRON TRC-20 events | A transaction-seeded case needs a canonical seed transfer in the evidence package. Live TRON uses confirmed transaction event retrieval; EVM uses confirmed receipt Transfer-log decoding for Ethereum, BNB Chain, and Polygon when a token contract is supplied. |
| Wallet-context live tracing | Implemented | The dashboard creates a `LIVE` wallet-context trace. Its amount is investigator supplied and the result records the approximate-seed limitation. |
| Disputed-fund accounting | Implemented | `FundFlowEngineV2` uses a bounded event-driven proportional haircut allocator, lineage, terminals, conservation tests, and an observed-ledger reconstruction from retained pre-event transfers. It remains partial when the evidence snapshot is incomplete. |
| Entity and VASP intelligence | Implemented | Source-backed entities, address assertions, reviewed source-backed entity relationships, review state, freshness, conflict-aware resolver, and auditable human review history are persisted. |
| Deposit inference | Implemented | Explainable receipt-to-sweep rules use only reviewed verified endpoints as targets. Resulting assertions remain unreviewed. |
| Immutable result and evidence | Implemented | Raw evidence artifacts, transfer hashes, source/assertion references, a versioned result manifest, PDF report, and deterministic trace fingerprint are persisted. |
| Request routing | Implemented as local draft only | A draft is generated from the same result snapshot and never submitted to SAHYOG or a VASP. Synthetic results cannot create a draft. |
| Cross-chain continuation | Evidence workflow implemented | A reviewed route and exact shared protocol message ID are required. Normalized source/destination events can be extracted from retained raw-evidence artifacts and resolved only when their exact IDs match. A protocol-specific collector still has to decode and retain those raw events. |
| ML | Conservative baseline implemented | Feature snapshots support a configured historical lookback, ML is disabled by default, and output stays `ML_INFERRED`. It is not production validated or allowed to create verified labels. |
| Dashboard | Implemented for v2 demo, live wallet-context flow, and recorded evidence replay | It shows data mode, candidates, allocations, inference reasons, report download, and local-draft result. Recorded JSON packages, transfer CSV files pasted as text, and source-backed intelligence assertion CSV data can be imported without a provider call. |
| Container deployment | Prototype-ready with PostgreSQL migration boundary | Compose serves the frontend and uses a named SQLite volume. A PostgreSQL 16+ v2 migration and repository contract are included; the runtime adapter and managed database remain deployment work. |

## Operational prerequisites outside this repository

1. A lawful SAHYOG/VASP integration contract and approved authentication model.
2. A transaction-by-hash collector plus historical balance source for live transaction-seeded analysis.
3. Licensed, reviewed entity labels with provenance, expiry, and reviewer workflow.
4. Reviewed ground truth, holdout validation, monitoring, and approval before enabling ML in an operational environment.
5. A durable worker runtime, a tested multi-user PostgreSQL repository adapter, secrets management, retention controls, and deployment review.

## Demonstration paths

- **Live:** Dashboard → **New v2 live trace** → wallet context. It uses configured read-only explorer credentials and retains provider limitations.
- **Recorded real:** Use the dashboard **Import recorded package** control or `POST /v2/imports/recorded-trace` with canonical `recorded_transfers` and optional `recorded_evidence`. It produces a replayable immutable snapshot without a network request.
- **Synthetic:** **Load v2 evidence demo**. Every output is marked synthetic and routing remains disabled.
