from __future__ import annotations

import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, model_validator

from .processor import ProcessingError, process_job
from .profiles import DEFAULT_QUALITY, SeparationQuality
from .separators.catalog import (
    DEFAULT_SEPARATOR_ENGINE,
    MELBAND_ROFORMER_ENGINE,
    ResolvedSelection,
    SeparatorEngine,
    resolve_selection,
)
from .rights import RIGHTS_ATTESTATION_TEXT, RIGHTS_ATTESTATION_VERSION
from .youtube import ingest_youtube_job

SourceType = Literal["upload", "youtube"]
JobStatus = Literal[
    "queued",
    "ingesting",
    "preparing",
    "validating",
    "separating",
    "finalizing",
    "completed",
    "failed",
]
ACTIVE_STATUSES = {"queued", "ingesting", "preparing", "validating", "separating", "finalizing"}
KARAOKE_ACTIVE_STATUSES = {"queued", "rendering"}


class KaraokeCommitConflict(RuntimeError):
    """The project changed while a karaoke mutation was being prepared."""


class KaraokeCommitError(RuntimeError):
    """A karaoke mutation could not be committed atomically."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Job(BaseModel):
    id: str
    original_filename: str
    source_filename: str
    source_type: SourceType = "upload"
    source_url: str | None = None
    canonical_url: str | None = None
    video_id: str | None = None
    title: str | None = None
    uploader: str | None = None
    uploader_id: str | None = None
    channel: str | None = None
    channel_id: str | None = None
    extractor: str | None = None
    fetched_at: str | None = None
    rights_attestation_version: str = RIGHTS_ATTESTATION_VERSION
    rights_attestation_text: str = RIGHTS_ATTESTATION_TEXT
    rights_confirmed_at: str | None = None
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
    separator_engine: SeparatorEngine = DEFAULT_SEPARATOR_ENGINE
    separator_model: str
    karaoke_status: Literal["empty", "draft", "queued", "rendering", "completed", "failed"] = "empty"
    karaoke_progress: int = 0
    karaoke_message: str = ""
    karaoke_error: str | None = None
    karaoke_project_revision: int | None = None
    karaoke_rendered_revision: int | None = None
    karaoke_updated_at: str | None = None
    created_at: str
    updated_at: str

    @model_validator(mode="before")
    @classmethod
    def migrate_separator_selection(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        migrated = dict(values)
        quality = migrated.get("quality", DEFAULT_QUALITY)
        engine = migrated.get("separator_engine", DEFAULT_SEPARATOR_ENGINE)
        selection: ResolvedSelection = resolve_selection(engine, quality)
        migrated.setdefault("separator_engine", selection.separator_engine)
        if (
            selection.separator_engine == MELBAND_ROFORMER_ENGINE
            and migrated.get("separator_model", selection.separator_model)
            != selection.separator_model
        ):
            raise ValueError("The MelBand RoFormer model ID is not supported.")
        migrated.setdefault("separator_model", selection.separator_model)
        return migrated


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
        source_type: SourceType = "upload",
        source_url: str | None = None,
        canonical_url: str | None = None,
        video_id: str | None = None,
        rights_confirmed_at: str | None = None,
        separator_engine: SeparatorEngine = DEFAULT_SEPARATOR_ENGINE,
        separator_model: str | None = None,
    ) -> Job:
        selection = resolve_selection(separator_engine, quality)
        if separator_model is not None and separator_model != selection.separator_model:
            raise ValueError("The separator model does not match the selected engine/profile.")

        now = utc_now()
        job = Job(
            id=str(uuid4()),
            original_filename=original_filename,
            source_filename=source_filename,
            source_type=source_type,
            source_url=source_url,
            canonical_url=canonical_url,
            video_id=video_id,
            rights_confirmed_at=rights_confirmed_at or now,
            size_bytes=size_bytes,
            quality=selection.quality,
            separator_engine=selection.separator_engine,
            separator_model=selection.separator_model,
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

    def has_active_jobs(self) -> bool:
        """Return whether any persisted job currently blocks desktop shutdown."""
        with self._lock:
            for path in self.jobs_dir.glob("*/job.json"):
                job = self.get(path.parent.name)
                if job is not None and (job.status in ACTIVE_STATUSES or job.karaoke_status in KARAOKE_ACTIVE_STATUSES):
                    return True
        return False

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self.get(job_id)
            if job is None:
                return False
            if job.status in ACTIVE_STATUSES or job.karaoke_status in KARAOKE_ACTIVE_STATUSES:
                raise RuntimeError("An active job cannot be deleted.")
            shutil.rmtree(self.job_dir(job_id))
            return True

    def queue_karaoke_render(self, job_id: str) -> Job | None:
        """Atomically transition a completed job into the render queue."""
        with self._lock:
            job = self.get(job_id)
            if job is None or job.karaoke_status in KARAOKE_ACTIVE_STATUSES:
                return None
            queued = job.model_copy(update={
                "karaoke_status": "queued",
                "karaoke_progress": 0,
                "karaoke_message": "Waiting to render karaoke video",
                "karaoke_error": None,
                "karaoke_updated_at": utc_now(),
            })
            self._write(queued)
            return queued

    def commit_karaoke_revision(self, job_id: str, project: Any, *, background_temp: Path | None = None) -> tuple[Any, Job]:
        """Commit a project, optional PNG install, and job state under one lock.

        Expensive provider/image work is deliberately performed before this method. The
        final active-state check and all durable writes happen together, so an edit can
        never hide a queued/rendering child process.
        """
        from .karaoke import load_project, project_path

        with self._lock:
            job = self.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.karaoke_status in KARAOKE_ACTIVE_STATUSES:
                raise KaraokeCommitConflict("Karaoke rendering is active.")
            job_dir = self.job_dir(job_id)
            metadata = self._metadata_path(job_id)
            project_file = project_path(job_dir)
            persisted_project = load_project(job_dir)
            expected_revision = persisted_project.revision if persisted_project is not None else 1
            if getattr(project, "revision", None) != expected_revision:
                raise KaraokeCommitConflict("The karaoke project changed while this revision was prepared.")
            old_metadata = metadata.read_bytes() if metadata.is_file() else None
            old_project = project_file.read_bytes() if project_file.is_file() else None
            old_backgrounds = {
                path: path.read_bytes()
                for path in job_dir.glob("karaoke-background.*")
                if path.is_file()
            }
            current = self.get(job_id)
            revision = (current and getattr(current, "karaoke_project_revision", None)) or getattr(project, "revision", 1)
            revision = max(int(revision or 1), int(getattr(project, "revision", 1))) + 1
            committed_project = project.model_copy(update={"revision": revision})
            target = job_dir / "karaoke-background.png"
            temporary: Path | None = None
            try:
                if background_temp is not None:
                    os.replace(background_temp, target)
                    for suffix in (".jpg", ".jpeg", ".webp"):
                        (job_dir / f"karaoke-background{suffix}").unlink(missing_ok=True)
                temporary = project_file.with_name(f".{project_file.name}.{id(committed_project)}.tmp")
                temporary.write_text(committed_project.model_dump_json(indent=2), encoding="utf-8")
                temporary.replace(project_file)
                updated = job.model_copy(update={
                    "karaoke_status": "draft",
                    "karaoke_progress": 0,
                    "karaoke_message": "Karaoke draft ready",
                    "karaoke_error": None,
                    "karaoke_project_revision": committed_project.revision,
                    "karaoke_updated_at": utc_now(),
                })
                self._write(updated)
                return committed_project, updated
            except Exception as exc:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
                for path in job_dir.glob("karaoke-background.*"):
                    path.unlink(missing_ok=True)
                for path, data in old_backgrounds.items():
                    path.write_bytes(data)
                if old_project is None:
                    project_file.unlink(missing_ok=True)
                else:
                    project_file.write_bytes(old_project)
                if old_metadata is not None:
                    metadata.write_bytes(old_metadata)
                metadata.with_suffix(".tmp").unlink(missing_ok=True)
                raise KaraokeCommitError("Could not persist the karaoke revision.") from exc

    def rollback_karaoke_queue(self, job_id: str, message: str = "Karaoke draft ready", error: str | None = None) -> Job:
        with self._lock:
            job = self.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.karaoke_status != "queued":
                return job
            updated = job.model_copy(update={
                "karaoke_status": "draft",
                "karaoke_progress": 0,
                "karaoke_message": message,
                "karaoke_error": error,
                "karaoke_updated_at": utc_now(),
            })
            self._write(updated)
            return updated

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
                    error="The local API stopped before this job finished. Please start it again.",
                )
            elif job.karaoke_status in KARAOKE_ACTIVE_STATUSES:
                self.update(
                    job.id,
                    karaoke_status="failed",
                    karaoke_progress=job.karaoke_progress,
                    karaoke_message="Karaoke rendering was interrupted",
                    karaoke_error="The local API stopped before rendering finished. Please try again.",
                    karaoke_updated_at=utc_now(),
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

    def submit_render(self, job_id: str) -> None:
        if self._shutdown:
            raise RuntimeError("The job manager is shutting down.")
        self._executor.submit(self._run_render, job_id)

    def shutdown(self) -> None:
        self._shutdown = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _render_error(self, exc: Exception) -> str:
        message = str(exc).splitlines()[0][:400]
        safe_messages = {
            "FFmpeg is required to render a karaoke video.",
            "ffprobe is required to render a karaoke video.",
            "The instrumental WAV is not available.",
            "ffprobe timed out while reading instrumental duration.",
            "Could not read instrumental duration.",
            "Instrumental duration is outside the supported range.",
            "FFmpeg encoder probe timed out.",
            "This FFmpeg build does not include the required libx264 encoder.",
            "Choose and upload a custom background image before rendering.",
            "This karaoke project has too many render states.",
            "Not enough free disk space for a karaoke render.",
            "Save a karaoke project before rendering.",
            "FFmpeg could not render the karaoke video. See karaoke-render.log.",
        }
        if message in safe_messages:
            return message
        return "Karaoke render failed. See karaoke-render.log for local diagnostics."

    def _run_render(self, job_id: str) -> None:
        from .karaoke import load_project, render_job

        job = self.store.get(job_id)
        if job is None:
            return
        try:
            project = load_project(self.store.job_dir(job.id))
            if project is None:
                raise ProcessingError("Save a karaoke project before rendering.")
            self.store.update(job.id, karaoke_status="rendering", karaoke_progress=0, karaoke_message="Starting karaoke render", karaoke_error=None, karaoke_project_revision=project.revision, karaoke_updated_at=utc_now())
            render_job(self.store.job_dir(job.id), project, lambda **changes: self.store.update(job.id, karaoke_progress=changes.get("progress", job.karaoke_progress), karaoke_message=changes.get("message", "Rendering karaoke video"), karaoke_updated_at=utc_now()))
            self.store.update(job.id, karaoke_status="completed", karaoke_progress=100, karaoke_message="Karaoke video is ready", karaoke_error=None, karaoke_project_revision=project.revision, karaoke_rendered_revision=project.revision, karaoke_updated_at=utc_now())
        except Exception as exc:
            self.store.update(job.id, karaoke_status="failed", karaoke_progress=0, karaoke_message="Karaoke render failed", karaoke_error=self._render_error(exc), karaoke_updated_at=utc_now())

    def _run(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            return
        try:
            update = lambda **changes: self.store.update(job.id, **changes)
            source_filename = job.source_filename
            if job.source_type == "youtube":
                if not job.source_url:
                    raise ProcessingError("This YouTube job has no source URL.")
                source_filename = ingest_youtube_job(
                    self.store.job_dir(job.id),
                    job.source_url,
                    update,
                )
            process_job(
                self.store.job_dir(job.id),
                source_filename,
                update,
                quality=job.quality,
                separator_engine=job.separator_engine,
                separator_model=job.separator_model,
            )
        except (ProcessingError, OSError, subprocess.SubprocessError) as exc:
            failed_job = self.store.get(job.id)
            message = (
                "YouTube ingest failed"
                if failed_job is not None and failed_job.source_type == "youtube"
                else "Separation failed"
            )
            self.store.update(
                job.id,
                status="failed",
                message=message,
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
