from __future__ import annotations

import secrets
import shutil
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from .config import (
    ALLOWED_SUFFIXES,
    CORS_ORIGINS,
    JOBS_DIR,
    MAX_UPLOAD_BYTES,
    SESSION_TOKEN,
)
from .jobs import ACTIVE_STATUSES, Job, JobManager, JobStore
from .processor import tool_status
from .profiles import DEFAULT_QUALITY, SeparationQuality
from .separators.catalog import (
    DEFAULT_SEPARATOR_ENGINE,
    SeparatorEngine,
    resolve_selection,
)
from .rights import RIGHTS_ATTESTATION_VERSION
from .runtime import web_dist_dir
from .youtube import YouTubeUrlError, classify_youtube_url

app = FastAPI(title="Karaoke Box API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

job_store = JobStore(JOBS_DIR)
job_manager = JobManager(job_store)


@app.middleware("http")
async def require_desktop_session(request: Request, call_next):
    if SESSION_TOKEN and request.url.path.startswith("/api/"):
        cookie = request.cookies.get("karaoke_session", "")
        if not secrets.compare_digest(cookie, SESSION_TOKEN):
            return JSONResponse({"detail": "Invalid desktop session."}, status_code=401)
    return await call_next(request)


@app.get("/desktop/start", include_in_schema=False)
def start_desktop_session(token: str) -> RedirectResponse:
    if not SESSION_TOKEN or not secrets.compare_digest(token, SESSION_TOKEN):
        raise HTTPException(status_code=404, detail="Not found.")
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        "karaoke_session",
        SESSION_TOKEN,
        httponly=True,
        samesite="strict",
        secure=False,
    )
    return response


def public_job(job: Job) -> dict[str, Any]:
    payload = job.model_dump(exclude={"source_filename"})
    job_dir = job_store.job_dir(job.id)
    payload["assets"] = {
        name: f"/api/jobs/{job.id}/assets/{name}"
        for name in ("instrumental", "vocals")
        if (job_dir / f"{name}.wav").is_file()
    }
    return payload


def require_rights_confirmation(rights_confirmed: bool, attestation_version: str) -> None:
    if not rights_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Confirm that you are allowed to process and export this source recording.",
        )
    if attestation_version != RIGHTS_ATTESTATION_VERSION:
        raise HTTPException(status_code=400, detail="This rights confirmation is out of date.")


@app.get("/api/health")
def health() -> dict[str, Any]:
    tools = tool_status()
    return {"ready": all(tools.values()), "tools": tools}


@app.post("/api/jobs", status_code=202)
async def create_job(
    file: Annotated[UploadFile, File()],
    rights_confirmed: Annotated[bool, Form()],
    attestation_version: Annotated[str, Form()],
    quality: Annotated[SeparationQuality, Form()] = DEFAULT_QUALITY,
    separator_engine: Annotated[SeparatorEngine, Form()] = DEFAULT_SEPARATOR_ENGINE,
) -> dict[str, Any]:
    require_rights_confirmation(rights_confirmed, attestation_version)
    try:
        selection = resolve_selection(separator_engine, quality)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    original_filename = Path(file.filename or "audio").name
    suffix = Path(original_filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
        raise HTTPException(status_code=415, detail=f"Unsupported file type. Use: {allowed}")

    # Create metadata first so the job directory has an unpredictable, server-owned path.
    job = job_store.create(
        original_filename,
        f"source{suffix}",
        0,
        quality,
        source_type="upload",
        separator_engine=selection.separator_engine,
        separator_model=selection.separator_model,
    )
    source_path = job_store.job_dir(job.id) / job.source_filename
    size = 0
    try:
        with source_path.open("xb") as destination:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                    )
                destination.write(chunk)
    except Exception:
        shutil.rmtree(job_store.job_dir(job.id), ignore_errors=True)
        raise
    finally:
        await file.close()

    if size == 0:
        shutil.rmtree(job_store.job_dir(job.id), ignore_errors=True)
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    job = job_store.update(job.id, size_bytes=size)
    job_manager.submit(job.id)
    return public_job(job)


class YouTubeJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    rights_confirmed: bool
    attestation_version: str
    quality: SeparationQuality = DEFAULT_QUALITY
    separator_engine: SeparatorEngine = DEFAULT_SEPARATOR_ENGINE


@app.post("/api/jobs/youtube", status_code=202)
def create_youtube_job(request: YouTubeJobRequest) -> dict[str, Any]:
    require_rights_confirmation(request.rights_confirmed, request.attestation_version)
    try:
        selection = resolve_selection(request.separator_engine, request.quality)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        source = classify_youtube_url(request.url)
    except YouTubeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job = job_store.create(
        f"YouTube video {source.video_id}",
        "source.pending",
        0,
        request.quality,
        source_type="youtube",
        separator_engine=selection.separator_engine,
        separator_model=selection.separator_model,
        source_url=source.canonical_url,
        canonical_url=source.canonical_url,
        video_id=source.video_id,
    )
    job_manager.submit(job.id)
    return public_job(job)


@app.get("/api/jobs")
def list_jobs(limit: Annotated[int, Query(ge=1, le=100)] = 50) -> list[dict[str, Any]]:
    return [public_job(job) for job in job_store.list(limit)]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return public_job(job)


@app.get("/api/jobs/{job_id}/assets/{asset_name}")
def get_asset(job_id: str, asset_name: str, download: bool = False) -> FileResponse:
    if asset_name not in {"instrumental", "vocals"}:
        raise HTTPException(status_code=404, detail="Asset not found.")
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    path = job_store.job_dir(job_id) / f"{asset_name}.wav"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Asset is not ready.")
    export_name = f"{Path(job.original_filename).stem}-{asset_name}.wav"
    return FileResponse(
        path,
        media_type="audio/wav",
        filename=export_name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str) -> None:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status in ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Wait for the active job to finish.")
    job_store.delete(job_id)


_frontend = web_dist_dir()
if _frontend.is_dir():
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
