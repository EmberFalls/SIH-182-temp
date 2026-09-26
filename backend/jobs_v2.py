"""SQLite-persisted v2 job records with restart-safe local recovery."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable


class PersistentTraceJobsV2:
    """Persist request inputs so an interrupted local job can be retried safely.

    This is a single-process runner, not a distributed worker. At startup, unfinished
    records are marked INTERRUPTED rather than silently claimed complete. Investigators
    can retry them from the exact retained input payload.
    """

    def __init__(self, store) -> None:
        self.store = store

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def submit(self, case_id: str, trace_request: dict, work: Callable[[], Awaitable[Any]]) -> dict:
        job = {
            "job_id": f"V2JOB-{uuid.uuid4().hex[:12].upper()}", "status": "QUEUED",
            "created_at": self._now(), "case_id": case_id, "trace_request": trace_request,
            "result_id": None, "attempt": 1,
        }
        self.store.save_v2_trace_job(job)
        self._start(job, work)
        return job

    def retry(self, job_id: str, work: Callable[[], Awaitable[Any]]) -> dict | None:
        job = self.store.get_v2_trace_job(job_id)
        if not job:
            return None
        if job.get("status") in {"QUEUED", "RUNNING"}:
            raise ValueError("Trace job is already active.")
        job = self.store.update_v2_trace_job(job_id, {
            "status": "QUEUED", "detail": None, "result_id": None,
            "started_at": None, "completed_at": None, "retry_requested_at": self._now(),
            "attempt": int(job.get("attempt", 1)) + 1,
        })
        self._start(job, work)
        return job

    def reconcile_interrupted(self) -> int:
        """Turn orphaned in-process work into an explicit retryable state at startup."""
        count = 0
        for job in self.store.list_v2_trace_jobs_by_status(["QUEUED", "RUNNING"]):
            self.store.update_v2_trace_job(job["job_id"], {
                "status": "INTERRUPTED",
                "detail": "The local process restarted before this trace job completed. Retry uses the retained case and request payload.",
                "completed_at": self._now(),
            })
            count += 1
        return count

    def _start(self, job: dict, work: Callable[[], Awaitable[Any]]) -> None:
        async def runner():
            self.store.update_v2_trace_job(job["job_id"], {"status": "RUNNING", "started_at": self._now()})
            try:
                result = await work()
                self.store.update_v2_trace_job(job["job_id"], {
                    "status": "COMPLETED", "result_id": result.id, "completed_at": self._now(), "detail": None,
                })
            except Exception as exc:
                self.store.update_v2_trace_job(job["job_id"], {
                    "status": "FAILED", "detail": str(exc), "completed_at": self._now(),
                })
        asyncio.create_task(runner())
