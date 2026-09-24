import json
import sqlite3
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .config import settings
from .models import CaseCreate, CaseNote, CaseSummary, CaseUpdate, LabelReview, LabelReviewEvent, VaspLabel, VaspLabelCreate


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, Decimal)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    raise TypeError(f"Unsupported JSON value: {type(value)!r}")


class Store:
    def __init__(self, database_path: str | None = None) -> None:
        self.path = Path(database_path or settings.database_path)
        self._initialize()

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS labels (
                    id TEXT PRIMARY KEY, address TEXT NOT NULL, chain TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(address, chain, payload)
                );
                CREATE TABLE IF NOT EXISTS trace_runs (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL,
                    resource TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS case_notes (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, author TEXT NOT NULL,
                    note TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS label_reviews (
                    id TEXT PRIMARY KEY, label_id TEXT NOT NULL, reviewer TEXT NOT NULL,
                    status TEXT NOT NULL, rationale TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)

    def create_case(self, payload: CaseCreate) -> CaseSummary:
        created_at = _utcnow()
        case = CaseSummary(id=f"CASE-{uuid.uuid4().hex[:12].upper()}", created_at=created_at, **payload.model_dump())
        with self._connection() as connection:
            connection.execute("INSERT INTO cases VALUES (?, ?, ?)", (case.id, json.dumps(case.model_dump(mode="json")), created_at.isoformat()))
        return case

    def get_case(self, case_id: str) -> CaseSummary | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM cases WHERE id = ?", (case_id,)).fetchone()
        return CaseSummary.model_validate_json(row["payload"]) if row else None

    def list_cases(self) -> list[CaseSummary]:
        with self._connection() as connection:
            rows = connection.execute("SELECT payload FROM cases ORDER BY created_at DESC").fetchall()
        return [CaseSummary.model_validate_json(row["payload"]) for row in rows]

    def update_case(self, case_id: str, update: CaseUpdate) -> CaseSummary | None:
        case = self.get_case(case_id)
        if not case:
            return None
        changes = update.model_dump(exclude_unset=True)
        # A blank notes value is permitted only when explicitly supplied.
        updated = case.model_copy(update=changes)
        with self._connection() as connection:
            connection.execute("UPDATE cases SET payload = ? WHERE id = ?", (json.dumps(updated.model_dump(mode="json")), case_id))
        return updated

    def add_case_note(self, case_id: str, author: str, note: str) -> CaseNote:
        event = CaseNote(id=f"NOTE-{uuid.uuid4().hex[:12].upper()}", case_id=case_id, author=author, note=note, created_at=_utcnow())
        with self._connection() as connection:
            connection.execute("INSERT INTO case_notes VALUES (?, ?, ?, ?, ?)", (event.id, event.case_id, event.author, event.note, event.created_at.isoformat()))
        return event

    def list_case_notes(self, case_id: str) -> list[CaseNote]:
        with self._connection() as connection:
            rows = connection.execute("SELECT id, case_id, author, note, created_at FROM case_notes WHERE case_id = ? ORDER BY created_at ASC", (case_id,)).fetchall()
        return [CaseNote.model_validate(dict(row)) for row in rows]

    def add_label(self, payload: VaspLabelCreate) -> VaspLabel:
        created_at = _utcnow()
        normalized = self._normalized_address(payload.address, payload.chain.value)
        existing = self.labels_for_address(normalized, payload.chain.value)
        conflicting = any(item.review_status == "APPROVED" and item.vasp_name != payload.vasp_name for item in existing)
        label = VaspLabel(id=f"LABEL-{uuid.uuid4().hex[:12].upper()}", created_at=created_at, review_status="CONFLICT" if conflicting else "APPROVED", **{**payload.model_dump(), "address": normalized})
        serialized = json.dumps(label.model_dump(mode="json"), default=_json_default, sort_keys=True)
        with self._connection() as connection:
            connection.execute("INSERT INTO labels VALUES (?, ?, ?, ?, ?)", (label.id, label.address, label.chain.value, serialized, created_at.isoformat()))
        return label

    def find_label(self, address: str, chain: str) -> VaspLabel | None:
        labels = self.labels_for_address(address, chain)
        if any(item.review_status == "CONFLICT" for item in labels):
            return None
        now = _utcnow()
        return next((item for item in labels if item.review_status == "APPROVED" and (item.expires_at is None or item.expires_at > now)), None)

    def labels_for_address(self, address: str, chain: str) -> list[VaspLabel]:
        address = self._normalized_address(address, chain)
        with self._connection() as connection:
            rows = connection.execute("SELECT payload FROM labels WHERE address = ? AND chain = ? ORDER BY created_at DESC", (address, chain)).fetchall()
        return [VaspLabel.model_validate_json(row["payload"]) for row in rows]

    def list_labels(self, chain: str | None = None) -> list[VaspLabel]:
        with self._connection() as connection:
            if chain:
                rows = connection.execute("SELECT payload FROM labels WHERE chain = ? ORDER BY created_at DESC", (chain,)).fetchall()
            else:
                rows = connection.execute("SELECT payload FROM labels ORDER BY created_at DESC").fetchall()
        return [VaspLabel.model_validate_json(row["payload"]) for row in rows]

    def review_label(self, label_id: str, reviewer: str, review: LabelReview) -> VaspLabel | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM labels WHERE id = ?", (label_id,)).fetchone()
            if not row:
                return None
            original = VaspLabel.model_validate_json(row["payload"])
            updated = original.model_copy(update={"review_status": review.status})
            connection.execute("UPDATE labels SET payload = ? WHERE id = ?", (json.dumps(updated.model_dump(mode="json"), default=_json_default, sort_keys=True), label_id))
            event = LabelReviewEvent(label_id=label_id, reviewer=reviewer, status=review.status, rationale=review.rationale, created_at=_utcnow())
            connection.execute("INSERT INTO label_reviews VALUES (?, ?, ?, ?, ?, ?)", (f"REVIEW-{uuid.uuid4().hex[:12].upper()}", event.label_id, event.reviewer, event.status, event.rationale, event.created_at.isoformat()))
        return updated

    def label_review_history(self, label_id: str) -> list[LabelReviewEvent]:
        with self._connection() as connection:
            rows = connection.execute("SELECT label_id, reviewer, status, rationale, created_at FROM label_reviews WHERE label_id = ? ORDER BY created_at ASC", (label_id,)).fetchall()
        return [LabelReviewEvent.model_validate(dict(row)) for row in rows]

    def save_run(self, run_id: str, case_id: str, payload: dict[str, Any], created_at: datetime) -> None:
        serialized = json.dumps(payload, default=_json_default, sort_keys=True, separators=(",", ":"))
        with self._connection() as connection:
            connection.execute("INSERT INTO trace_runs VALUES (?, ?, ?, ?)", (run_id, case_id, serialized, created_at.isoformat()))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT payload FROM trace_runs WHERE id = ?", (run_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_runs(self, exclude_case_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT payload FROM trace_runs"
        params: tuple[Any, ...] = ()
        if exclude_case_id:
            query += " WHERE case_id != ?"
            params = (exclude_case_id,)
        query += " ORDER BY created_at DESC"
        with self._connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def record_audit(self, actor: str, action: str, resource: str, detail: dict[str, Any] | None = None) -> None:
        created_at = _utcnow()
        with self._connection() as connection:
            connection.execute("INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?)", (
                f"AUDIT-{uuid.uuid4().hex[:12].upper()}", actor, action, resource,
                json.dumps(detail or {}, default=_json_default, sort_keys=True), created_at.isoformat(),
            ))

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute("SELECT id, actor, action, resource, detail, created_at FROM audit_events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(row), "detail": json.loads(row["detail"])} for row in rows]

    @staticmethod
    def _normalized_address(address: str, chain: str) -> str:
        return address.lower() if chain in {"ETHEREUM", "BNB_CHAIN", "POLYGON"} else address
