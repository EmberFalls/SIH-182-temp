"""SQLite-persisted v2 job records with explicit restart semantics."""
from __future__ import annotations
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Any

class PersistentTraceJobsV2:
    def __init__(self, store) -> None:
        self.store = store

    def submit(self, work: Callable[[], Awaitable[Any]]) -> dict:
        job = {"job_id": f"V2JOB-{uuid.uuid4().hex[:12].upper()}", "status": "QUEUED", "created_at": datetime.now(timezone.utc).isoformat(), "result_id": None}
        self.store.save_v2_trace_job(job)
        async def runner():
            self.store.update_v2_trace_job(job["job_id"], {"status": "RUNNING", "started_at": datetime.now(timezone.utc).isoformat()})
            try:
                result = await work()
                self.store.update_v2_trace_job(job["job_id"], {"status": "COMPLETED", "result_id": result.id, "completed_at": datetime.now(timezone.utc).isoformat()})
            except Exception as exc:
                self.store.update_v2_trace_job(job["job_id"], {"status": "FAILED", "detail": str(exc), "completed_at": datetime.now(timezone.utc).isoformat()})
        asyncio.create_task(runner())
        return job