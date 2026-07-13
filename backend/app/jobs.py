from __future__ import annotations

import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel

from .processor import ProcessingError, process_job
from .profiles import DEFAULT_QUALITY, SeparationQuality

JobStatus = Literal[
    "queued", "validating", "separating", "finalizing", "completed", "failed"
]
ACTIVE_STATUSES = {"queued", "validating", "separating", "finalizing"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Job(BaseModel):
    id: str
    original_filename: str
    source_filename: str
    size_bytes: int
    status: JobStatus = "queued"
    progress: int = 0
    message: str = "Waiting to start"
    duration_seconds: float | None = None
    eta_seconds: int | None = None
    current_pass: int | None = None
    total_passes: int | None = None
    error: str | None = None
    quality: SeparationQuality = DEFAULT_QUALITY
    created_at: str
    updated_at: str


class JobStore:
    def __init__(self, jobs_dir: Path):
        self.jobs_dir = jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._mark_interrupted_jobs()

    def job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def _metadata_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    def create(
        self,
        original_filename: str,
        source_filename: str,
        size_bytes: int,
        quality: SeparationQuality = DEFAULT_QUALITY,
    ) -> Job:
        now = utc_now()
        job = Job(
            id=str(uuid4()),
            original_filename=original_filename,
            source_filename=source_filename,
            size_bytes=size_bytes,
            quality=quality,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self.job_dir(job.id).mkdir(parents=True, exist_ok=False)
            self._write(job)
        return job

    def get(self, job_id: str) -> Job | None:
        path = self._metadata_path(job_id)
        with self._lock:
            if not path.is_file():
                return None
            try:
                return Job.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None

    def update(self, job_id: str, **changes: Any) -> Job:
        with self._lock:
            job = self.get(job_id)
            if job is None:
                raise KeyError(job_id)
            updated = job.model_copy(update={**changes, "updated_at": utc_now()})
            self._write(updated)
            return updated

    def list(self, limit: int = 50) -> list[Job]:
        with self._lock:
            jobs = [
                job
                for path in self.jobs_dir.glob("*/job.json")
                if (job := self.get(path.parent.name)) is not None
            ]
        jobs.sort(key=lambda job: job.created_at, reverse=True)
        return jobs[:limit]

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self.get(job_id)
            if job is None:
                return False
            if job.status in ACTIVE_STATUSES:
                raise RuntimeError("An active job cannot be deleted.")
            shutil.rmtree(self.job_dir(job_id))
            return True

    def _write(self, job: Job) -> None:
        path = self._metadata_path(job.id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)

    def _mark_interrupted_jobs(self) -> None:
        for path in self.jobs_dir.glob("*/job.json"):
            try:
                job = Job.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if job.status in ACTIVE_STATUSES:
                self.update(
                    job.id,
                    status="failed",
                    progress=job.progress,
                    message="Processing was interrupted",
                    eta_seconds=None,
                    error="The local API stopped before this job finished. Please upload it again.",
                )


class JobManager:
    def __init__(self, store: JobStore):
        self.store = store
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="karaoke-job")
        self._shutdown = False

    def submit(self, job_id: str) -> None:
        if self._shutdown:
            raise RuntimeError("The job manager is shutting down.")
        self._executor.submit(self._run, job_id)

    def shutdown(self) -> None:
        self._shutdown = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        try:
            process_job(
                self.store.job_dir(job.id),
                job.source_filename,
                lambda **changes: self.store.update(job.id, **changes),
                quality=job.quality,
            )
        except (ProcessingError, OSError, subprocess.SubprocessError) as exc:
            self.store.update(
                job.id,
                status="failed",
                message="Separation failed",
                eta_seconds=None,
                error=str(exc)[:4000],
            )
        except Exception as exc:  # Keep a failed local job inspectable instead of losing it.
            self.store.update(
                job.id,
                status="failed",
                message="Unexpected processing error",
                eta_seconds=None,
                error=f"{type(exc).__name__}: {exc}"[:4000],
            )
