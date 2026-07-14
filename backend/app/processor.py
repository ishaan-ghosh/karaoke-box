from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import MAX_DURATION_SECONDS
from .profiles import DEFAULT_QUALITY, SeparationQuality, get_profile
from .runtime import resolve_tool
from .separators.base import ProcessingError
from .separators.catalog import (
    DEFAULT_SEPARATOR_ENGINE,
    ResolvedSelection,
    SeparatorEngine,
    resolve_selection,
)
from .separators.demucs import (
    DemucsProgress,
    DemucsProgressTracker,
    _demucs_output_path,
)
from .separators.registry import get_separator_adapter

ProgressCallback = Callable[..., None]


def tool_status() -> dict[str, bool]:
    return {
        "ffmpeg": resolve_tool("ffmpeg") is not None,
        "ffprobe": resolve_tool("ffprobe") is not None,
        "demucs": importlib.util.find_spec("demucs") is not None,
        "yt-dlp": importlib.util.find_spec("yt_dlp") is not None,
    }


def ensure_tools() -> None:
    """Check tools shared by all separator adapters."""

    required = {
        "ffmpeg": resolve_tool("ffmpeg") is not None,
        "ffprobe": resolve_tool("ffprobe") is not None,
    }
    missing = [name for name, available in required.items() if not available]
    if missing:
        raise ProcessingError(
            f"Missing required tool{'s' if len(missing) > 1 else ''}: {', '.join(missing)}. "
            "Run the setup instructions in README.md."
        )


def probe_audio(source: Path) -> dict[str, Any]:
    ffprobe = resolve_tool("ffprobe")
    if ffprobe is None:
        raise ProcessingError("Missing required tool: ffprobe.")
    command = [
        ffprobe,
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


def _finalize_stems(job_dir: Path, instrumental_source: Path, vocals_source: Path) -> None:
    shutil.move(str(instrumental_source), job_dir / "instrumental.wav")
    shutil.move(str(vocals_source), job_dir / "vocals.wav")


def process_job(
    job_dir: Path,
    source_filename: str,
    update: ProgressCallback,
    quality: SeparationQuality = DEFAULT_QUALITY,
    separator_engine: SeparatorEngine = DEFAULT_SEPARATOR_ENGINE,
    separator_model: str | None = None,
) -> None:
    selection = resolve_selection(separator_engine, quality)
    if separator_model is not None:
        selection = ResolvedSelection(
            separator_engine=selection.separator_engine,
            separator_model=separator_model,
            quality=selection.quality,
        )

    source = job_dir / source_filename
    adapter = get_separator_adapter(selection)

    update(status="validating", progress=0, message="Checking audio file")
    ensure_tools()
    probe = probe_audio(source)
    update(
        status="separating",
        progress=0,
        message=get_profile(selection.quality).progress_message,
        duration_seconds=probe["duration_seconds"],
        eta_seconds=None,
        current_pass=1,
        total_passes=get_profile(selection.quality).model_passes,
    )

    adapter.prepare(
        job_dir=job_dir,
        source=source,
        update=update,
        quality=selection.quality,
        model=selection.separator_model,
    )
    stems = adapter.separate(
        job_dir=job_dir,
        source=source,
        update=update,
        quality=selection.quality,
        model=selection.separator_model,
    )

    if not stems.instrumental.is_file() or not stems.vocals.is_file():
        raise ProcessingError("The separator finished without producing the expected stems.")

    update(
        status="finalizing",
        progress=100,
        message="Preparing full-quality WAV files",
        eta_seconds=None,
    )
    _finalize_stems(job_dir, stems.instrumental, stems.vocals)
    # The adapter owns its scratch layout. Successful jobs do not retain it.
    shutil.rmtree(job_dir / "demucs-output", ignore_errors=True)
    shutil.rmtree(job_dir / "separator-output", ignore_errors=True)
    update(
        status="completed",
        progress=100,
        message="Your karaoke track is ready",
        eta_seconds=None,
    )


__all__ = [
    "DemucsProgress",
    "DemucsProgressTracker",
    "ProcessingError",
    "_demucs_output_path",
    "ensure_tools",
    "probe_audio",
    "process_job",
    "tool_status",
]
