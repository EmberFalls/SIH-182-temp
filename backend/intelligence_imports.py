"""Strict bulk import for source-backed v2 entity assertions."""
from __future__ import annotations

import csv
import io
from datetime import datetime

from .domain import (
    AssertionReviewState, AssertionType, EntityAddressAssertionCreate, EntityCreate,
    EntityRole, EntityType, IntelligenceSourceCreate, IntelligenceSourceType, TrustTier,
)
from .models import Chain

REQUIRED_COLUMNS = {"entity_name", "entity_type", "address", "chain", "role", "assertion_type", "source_name", "source_type", "trust_tier", "retrieved_at"}


def import_entity_assertions_csv(store, csv_text: str) -> dict:
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")
    missing = REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(sorted(missing))}.")
    imported, rejected, assertion_ids = 0, [], []
    for line, row in enumerate(reader, start=2):
        try:
            entity_type = EntityType(row["entity_type"].upper())
            entity = store.find_entity(row["entity_name"].strip(), entity_type) or store.create_entity(EntityCreate(canonical_name=row["entity_name"].strip(), entity_type=entity_type, jurisdiction=row.get("jurisdiction") or None))
            source = store.create_intelligence_source(IntelligenceSourceCreate(name=row["source_name"].strip(), source_type=IntelligenceSourceType(row["source_type"].upper()), source_uri=row.get("source_uri") or None, trust_tier=TrustTier(row["trust_tier"].upper()), retrieved_at=datetime.fromisoformat(row["retrieved_at"].replace("Z", "+00:00")), notes=row.get("source_notes") or None))
            assertion = store.create_entity_address_assertion(EntityAddressAssertionCreate(entity_id=entity.id, address=row["address"].strip(), chain=Chain(row["chain"].upper()), role=EntityRole(row["role"].upper()), assertion_type=AssertionType(row["assertion_type"].upper()), source_id=source.id, review_state=AssertionReviewState(row.get("review_state", "UNREVIEWED").upper()), notes=row.get("notes") or None, risk_tags=[tag.strip() for tag in (row.get("risk_tags") or "").split("|") if tag.strip()]))
            imported += 1
            assertion_ids.append(assertion.id)
        except Exception as exc:
            rejected.append({"line": line, "detail": str(exc)})
    return {"imported": imported, "rejected": rejected, "assertion_ids": assertion_ids}