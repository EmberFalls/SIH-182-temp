"""Canonical serialization and stable identifiers for the v2 investigation domain."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel


DOMAIN_SCHEMA_VERSION = "2.0.0"
TRACE_ENGINE_VERSION = "2.0.0-alpha.1"
ENTITY_RESOLVER_VERSION = "2.0.0-alpha.1"
ATTRIBUTION_ENGINE_VERSION = "2.0.0-alpha.1"
RESULT_SCHEMA_VERSION = "2.0.0-alpha.1"


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def canonicalize(value: Any) -> Any:
    """Convert supported domain values to a deterministic JSON-safe representation."""
    if isinstance(value, BaseModel):
        return canonicalize(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {str(key): canonicalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Canonical timestamps must include a timezone.")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return canonicalize(value.value)
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(canonicalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()
