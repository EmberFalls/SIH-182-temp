"""SQLite-persisted v2 job records with restart-safe local recovery."""
from __future__ import annotations

import asyncio
import inspect
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

    def submit(self, case_id: str, trace_request: dict, work: Callable[..., Awaitable[Any]]) -> dict:
        job = {
            "job_id": f"V2JOB-{uuid.uuid4().hex[:12].upper()}", "status": "QUEUED",
            "created_at": self._now(), "case_id": case_id, "trace_request": trace_request,
            "result_id": None, "attempt": 1, "current_stage": "queued", "progress_events": [],
            "cancellation_requested": False,
        }
        self.store.save_v2_trace_job(job)
        self._start(job, work)
        return job

    def retry(self, job_id: str, work: Callable[..., Awaitable[Any]]) -> dict | None:
        job = self.store.get_v2_trace_job(job_id)
        if not job:
            return None
        if job.get("status") in {"QUEUED", "RUNNING", "WAITING_PROVIDER", "RETRYING"}:
            raise ValueError("Trace job is already active.")
        job = self.store.update_v2_trace_job(job_id, {
            "status": "QUEUED", "detail": None, "result_id": None,
            "started_at": None, "completed_at": None, "retry_requested_at": self._now(),
            "attempt": int(job.get("attempt", 1)) + 1, "current_stage": "queued", "cancellation_requested": False,
            "progress_events": list(job.get("progress_events", [])) + [{"at": self._now(), "stage": "retry queued"}],
        })
        self._start(job, work)
        return job

    def cancel(self, job_id: str) -> dict | None:
        job = self.store.get_v2_trace_job(job_id)
        if not job:
            return None
        if job.get("status") in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise ValueError("Only active or retryable trace jobs can be cancelled.")
        changes = {
            "cancellation_requested": True,
            "current_stage": "cancellation requested",
            "progress_events": list(job.get("progress_events", [])) + [{"at": self._now(), "stage": "cancellation requested"}],
        }
        if job.get("status") == "QUEUED":
            changes.update({"status": "CANCELLED", "completed_at": self._now(), "detail": "Cancelled before provider acquisition began."})
        return self.store.update_v2_trace_job(job_id, changes)

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

    def _start(self, job: dict, work: Callable[..., Awaitable[Any]]) -> None:
        async def runner():
            current = self.store.get_v2_trace_job(job["job_id"])
            if current and current.get("status") == "CANCELLED":
                return
            self.store.update_v2_trace_job(job["job_id"], {"status": "RUNNING", "started_at": self._now(), "current_stage": "starting", "progress_events": list((current or job).get("progress_events", [])) + [{"at": self._now(), "stage": "starting"}]})
            def cancelled() -> bool:
                latest = self.store.get_v2_trace_job(job["job_id"])
                return bool(latest and latest.get("cancellation_requested"))
            def progress(stage: str) -> None:
                latest = self.store.get_v2_trace_job(job["job_id"])
                if latest:
                    self.store.update_v2_trace_job(job["job_id"], {"current_stage": stage, "progress_events": list(latest.get("progress_events", [])) + [{"at": self._now(), "stage": stage}]})
            try:
                result = await (work(progress, cancelled) if len(inspect.signature(work).parameters) >= 2 else work())
                self.store.update_v2_trace_job(job["job_id"], {
                    "status": "COMPLETED", "result_id": result.id, "completed_at": self._now(), "detail": None, "current_stage": "completed",
                })
            except Exception as exc:
                is_cancelled = cancelled() or exc.__class__.__name__ == "TraceCancelled"
                self.store.update_v2_trace_job(job["job_id"], {
                    "status": "CANCELLED" if is_cancelled else "FAILED", "detail": str(exc), "completed_at": self._now(),
                    "current_stage": "cancelled" if is_cancelled else "failed",
                })
        asyncio.create_task(runner())
