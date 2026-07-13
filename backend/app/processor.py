from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import MAX_DURATION_SECONDS
from .profiles import DEFAULT_QUALITY, SeparationQuality, get_profile

ProgressCallback = Callable[..., None]


class ProcessingError(RuntimeError):
    """An expected media-processing failure that can be shown to the user."""


def tool_status() -> dict[str, bool]:
    return {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "demucs": importlib.util.find_spec("demucs") is not None,
    }


def ensure_tools() -> None:
    missing = [name for name, available in tool_status().items() if not available]
    if missing:
        raise ProcessingError(
            f"Missing required tool{'s' if len(missing) > 1 else ''}: {', '.join(missing)}. "
            "Run the setup instructions in README.md."
        )


def probe_audio(source: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,format_name:stream=codec_type,codec_name",
        "-of",
        "json",
        str(source),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or "ffprobe could not read this file"
        raise ProcessingError(f"The upload is not valid audio: {detail[-800:]}")

    try:
        metadata = json.loads(result.stdout)
        duration = float(metadata.get("format", {}).get("duration", 0))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProcessingError("Could not determine the audio duration.") from exc

    streams = metadata.get("streams", [])
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise ProcessingError("The uploaded file does not contain an audio stream.")
    if duration <= 0:
        raise ProcessingError("The uploaded audio is empty.")
    if duration > MAX_DURATION_SECONDS:
        limit_minutes = int(MAX_DURATION_SECONDS // 60)
        raise ProcessingError(f"Audio must be {limit_minutes} minutes or shorter.")

    return {"duration_seconds": round(duration, 3), "metadata": metadata}


def _demucs_output_path(work_dir: Path, model: str, stem: str) -> Path:
    model_directory = model.replace("hf://", "").replace("/", "_")
    return work_dir / model_directory / "source" / f"{stem}.wav"


def process_job(
    job_dir: Path,
    source_filename: str,
    update: ProgressCallback,
    quality: SeparationQuality = DEFAULT_QUALITY,
) -> None:
    source = job_dir / source_filename
    work_dir = job_dir / "demucs-output"
    log_path = job_dir / "demucs.log"
    profile = get_profile(quality)

    update(status="validating", progress=10, message="Checking audio file")
    ensure_tools()
    probe = probe_audio(source)
    update(
        status="separating",
        progress=20,
        message=profile.progress_message,
        duration_seconds=probe["duration_seconds"],
    )

    command = [
        sys.executable,
        "-m",
        "demucs",
        "--two-stems",
        "vocals",
        "--device",
        "cpu",
        "--jobs",
        "1",
        "--name",
        profile.model,
        "--other-method",
        profile.other_method,
        "--out",
        str(work_dir),
        str(source),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    log_path.write_text(
        f"$ {' '.join(command)}\n\nSTDOUT\n{result.stdout}\n\nSTDERR\n{result.stderr}",
        encoding="utf-8",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ProcessingError(
            "Demucs could not separate this track. "
            f"See {log_path.name} for details. {detail[-1000:]}"
        )

    instrumental_source = _demucs_output_path(
        work_dir, profile.model, profile.instrumental_stem
    )
    vocals_source = _demucs_output_path(work_dir, profile.model, "vocals")
    if not instrumental_source.is_file() or not vocals_source.is_file():
        raise ProcessingError("Demucs finished without producing the expected stems.")

    update(status="finalizing", progress=92, message="Preparing full-quality WAV files")
    shutil.move(str(instrumental_source), job_dir / "instrumental.wav")
    shutil.move(str(vocals_source), job_dir / "vocals.wav")
    shutil.rmtree(work_dir, ignore_errors=True)
    update(status="completed", progress=100, message="Your karaoke track is ready")
