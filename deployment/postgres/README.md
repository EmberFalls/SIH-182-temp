# PostgreSQL deployment boundary

`001_vasp_trace_v2.sql` is the PostgreSQL 16+ migration for the evidence-first v2
records. It uses `JSONB` payloads so an investigation can preserve the exact
serialized evidence, policy, result, and audit-relevant fields that produced a
conclusion. The explicit columns and indexes support the case, address, entity,
bridge, and queue lookups used by the service.

The running prototype intentionally uses SQLite by default. `backend/repository_contract.py`
defines the application-facing v2 persistence boundary so a PostgreSQL adapter can be
introduced without changing route handlers or evidence models. Do not point
`DATABASE_PATH` at a PostgreSQL URL: that requires the adapter plus a managed
PostgreSQL service, migration runner, credential handling, and backup policy.
