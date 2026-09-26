-- PostgreSQL 16+ schema for VASP Trace v2.
-- Apply with a dedicated migration runner before enabling a PostgreSQL adapter.
-- Payload columns are JSONB so immutable evidence can be replayed exactly; indexed
-- columns support operational case, entity, bridge, and trace-job lookups.

BEGIN;

CREATE TABLE IF NOT EXISTS investigation_cases_v2 (
  id TEXT PRIMARY KEY, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS investigation_cases_v2_created_idx ON investigation_cases_v2 (created_at DESC);

CREATE TABLE IF NOT EXISTS raw_evidence_artifacts_v2 (
  id TEXT PRIMARY KEY, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS raw_evidence_artifacts_v2_created_idx ON raw_evidence_artifacts_v2 (created_at DESC);

CREATE TABLE IF NOT EXISTS intelligence_sources (
  id TEXT PRIMARY KEY, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS entities_name_idx ON entities (canonical_name);

CREATE TABLE IF NOT EXISTS entity_address_assertions (
  id TEXT PRIMARY KEY, address TEXT NOT NULL, chain TEXT NOT NULL, entity_id TEXT NOT NULL,
  source_id TEXT NOT NULL, role TEXT NOT NULL, assertion_type TEXT NOT NULL,
  payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL,
  UNIQUE (address, chain, entity_id, source_id, role, assertion_type)
);
CREATE INDEX IF NOT EXISTS entity_assertions_address_chain_idx ON entity_address_assertions (address, chain, created_at DESC);

CREATE TABLE IF NOT EXISTS assertion_reviews_v2 (
  id TEXT PRIMARY KEY, assertion_id TEXT NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS assertion_reviews_v2_assertion_idx ON assertion_reviews_v2 (assertion_id, created_at DESC);

CREATE TABLE IF NOT EXISTS entity_relationships_v2 (
  id TEXT PRIMARY KEY, source_entity_id TEXT NOT NULL, target_entity_id TEXT NOT NULL,
  payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL,
  UNIQUE (source_entity_id, target_entity_id, payload)
);
CREATE INDEX IF NOT EXISTS entity_relationships_v2_source_idx ON entity_relationships_v2 (source_entity_id, created_at DESC);
CREATE INDEX IF NOT EXISTS entity_relationships_v2_target_idx ON entity_relationships_v2 (target_entity_id, created_at DESC);

CREATE TABLE IF NOT EXISTS investigation_results_v2 (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL, version INTEGER NOT NULL,
  payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL, UNIQUE (case_id, version)
);
CREATE INDEX IF NOT EXISTS investigation_results_v2_case_idx ON investigation_results_v2 (case_id, version DESC);
CREATE TABLE IF NOT EXISTS request_drafts_v2 (
  id TEXT PRIMARY KEY, case_id TEXT NOT NULL, result_id TEXT NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS request_drafts_v2_case_idx ON request_drafts_v2 (case_id, created_at DESC);

CREATE TABLE IF NOT EXISTS feature_snapshots_v2 (
  id TEXT PRIMARY KEY, address TEXT NOT NULL, chain TEXT NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS feature_snapshots_v2_address_idx ON feature_snapshots_v2 (address, chain, created_at DESC);
CREATE TABLE IF NOT EXISTS training_datasets_v2 (
  id TEXT PRIMARY KEY, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS model_versions_v2 (
  id TEXT PRIMARY KEY, model_name TEXT NOT NULL, version TEXT NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL,
  UNIQUE (model_name, version)
);
CREATE TABLE IF NOT EXISTS model_inferences_v2 (
  id TEXT PRIMARY KEY, model_version_id TEXT NOT NULL, feature_snapshot_id TEXT NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS model_inferences_v2_snapshot_idx ON model_inferences_v2 (feature_snapshot_id, created_at DESC);

CREATE TABLE IF NOT EXISTS bridge_routes_v2 (
  id TEXT PRIMARY KEY, bridge_entity_id TEXT NOT NULL, protocol TEXT NOT NULL,
  source_chain TEXT NOT NULL, destination_chain TEXT NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS bridge_routes_v2_pair_idx ON bridge_routes_v2 (source_chain, destination_chain, created_at DESC);
CREATE TABLE IF NOT EXISTS bridge_events_v2 (
  id TEXT PRIMARY KEY, protocol TEXT NOT NULL, direction TEXT NOT NULL, message_id TEXT NOT NULL,
  raw_evidence_id TEXT NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS bridge_events_v2_message_idx ON bridge_events_v2 (protocol, message_id, created_at DESC);
CREATE TABLE IF NOT EXISTS cross_chain_links_v2 (
  id TEXT PRIMARY KEY, route_id TEXT NOT NULL, status TEXT NOT NULL, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS cross_chain_links_v2_route_idx ON cross_chain_links_v2 (route_id, created_at DESC);

CREATE TABLE IF NOT EXISTS v2_trace_jobs (
  id TEXT PRIMARY KEY, payload JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS v2_trace_jobs_created_idx ON v2_trace_jobs (created_at DESC);

COMMIT;
