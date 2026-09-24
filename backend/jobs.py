import asyncio
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Any


class TraceJobs:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}

    def submit(self, work: Callable[[], Awaitable[Any]]) -> dict[str, Any]:
        job_id = f"JOB-{uuid.uuid4().hex[:12].upper()}"
        self.jobs[job_id] = {"job_id": job_id, "status": "QUEUED", "created_at": datetime.now(timezone.utc).isoformat()}

        async def runner() -> None:
            self.jobs[job_id]["status"] = "RUNNING"
            try:
                result = await work()
                self.jobs[job_id].update({"status": "COMPLETED", "run_id": result.run_id, "completed_at": datetime.now(timezone.utc).isoformat()})
            except Exception as exc:  # preserve safe error text for the investigator
                self.jobs[job_id].update({"status": "FAILED", "detail": str(exc), "completed_at": datetime.now(timezone.utc).isoformat()})

        asyncio.create_task(runner())
        return self.jobs[job_id]

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.jobs.get(job_id)
