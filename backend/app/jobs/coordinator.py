from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.core.storage import SqliteRepository
from app.models.domain import JobRecord, JobStatus, JobType


@dataclass(slots=True)
class JobExecutionContext:
    job_id: str
    repo: SqliteRepository
    cancel_event: asyncio.Event

    async def report(self, progress: int, message: str) -> None:
        job = self.repo.get_job(self.job_id)
        if not job:
            return
        timestamp = datetime.now(UTC).strftime("%H:%M:%S")
        job.progress = progress
        job.message = message
        job.updated_at = datetime.now(UTC)
        job.logs.append(f"[{timestamp}] {message}")
        self.repo.upsert_job(job)

    def cancel_requested(self) -> bool:
        return self.cancel_event.is_set()


class JobCoordinator:
    def __init__(self, repo: SqliteRepository) -> None:
        self.repo = repo
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}

    def recover_interrupted_jobs(self, *, stale_before: datetime | None = None) -> list[JobRecord]:
        recovered: list[JobRecord] = []
        now = datetime.now(UTC)
        for job in self.repo.list_jobs():
            if job.status not in {JobStatus.PENDING, JobStatus.RUNNING}:
                continue
            if stale_before is not None and job.updated_at > stale_before:
                continue
            job.status = JobStatus.FAILED
            job.message = "Interrupted by a Workbench restart; eligible background work will be requeued safely."
            job.logs.append(f"[{now.strftime('%H:%M:%S')}] Workbench restarted before this job completed.")
            job.updated_at = now
            job.finished_at = now
            self.repo.upsert_job(job)
            recovered.append(job)
        return recovered

    def create_job(
        self,
        *,
        job_type: JobType,
        title: str,
        owner: str,
        server_id: str,
        payload: dict[str, Any],
    ) -> JobRecord:
        job = JobRecord(job_type=job_type, title=title, owner=owner, server_id=server_id, payload=payload)
        self.repo.upsert_job(job)
        return job

    def submit(
        self,
        job: JobRecord,
        handler: Callable[[JobExecutionContext], Awaitable[dict[str, Any]]],
    ) -> JobRecord:
        cancel_event = asyncio.Event()
        self._cancel_events[job.id] = cancel_event

        async def runner() -> None:
            current = self.repo.get_job(job.id)
            if not current:
                return
            current.status = JobStatus.RUNNING
            current.started_at = datetime.now(UTC)
            current.updated_at = datetime.now(UTC)
            current.message = "Running"
            self.repo.upsert_job(current)
            context = JobExecutionContext(job.id, self.repo, cancel_event)
            try:
                result = await handler(context)
                final = self.repo.get_job(job.id)
                if not final:
                    return
                final.updated_at = datetime.now(UTC)
                final.finished_at = datetime.now(UTC)
                if cancel_event.is_set() or result.get("cancelled"):
                    final.status = JobStatus.CANCELLED
                    final.message = "Cancelled"
                else:
                    final.status = JobStatus.SUCCEEDED
                    final.progress = 100
                    final.message = "Completed"
                final.result = result
                if artifact_path := result.get("artifact_path"):
                    final.artifact_path = artifact_path
                self.repo.upsert_job(final)
            except Exception as exc:
                final = self.repo.get_job(job.id)
                if final:
                    final.status = JobStatus.FAILED
                    final.message = str(exc)
                    final.logs.append(f"[{datetime.now(UTC).strftime('%H:%M:%S')}] ERROR {exc}")
                    final.updated_at = datetime.now(UTC)
                    final.finished_at = datetime.now(UTC)
                    self.repo.upsert_job(final)
            finally:
                self._tasks.pop(job.id, None)
                self._cancel_events.pop(job.id, None)

        self._tasks[job.id] = asyncio.create_task(runner(), name=f"job-{job.id}")
        return job

    def list_jobs(self, owner: str) -> list[JobRecord]:
        return self.repo.list_jobs(owner)

    def get_job(self, job_id: str) -> JobRecord | None:
        return self.repo.get_job(job_id)

    def cancel_job(self, job_id: str) -> JobRecord | None:
        job = self.repo.get_job(job_id)
        if not job:
            return None
        job.cancel_requested = True
        job.updated_at = datetime.now(UTC)
        job.message = "Cancellation requested"
        self.repo.upsert_job(job)
        cancel_event = self._cancel_events.get(job_id)
        if cancel_event:
            cancel_event.set()
        task = self._tasks.get(job_id)
        if task and task.done():
            self._tasks.pop(job_id, None)
        return self.repo.get_job(job_id)
