from __future__ import annotations

import importlib.util
import json
import math
import queue
import re
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .config import (
    MAX_DURATION_SECONDS,
    MAX_UPLOAD_BYTES,
    YOUTUBE_DOWNLOAD_TIMEOUT_SECONDS,
    YOUTUBE_METADATA_TIMEOUT_SECONDS,
    YOUTUBE_SOCKET_TIMEOUT_SECONDS,
)
from .processor import ProcessingError
from .runtime import ytdlp_command

ProgressCallback = Callable[..., None]

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_SHORT_YOUTUBE_HOSTS = {"youtu.be", "www.youtu.be"}
_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_DOWNLOAD_PROGRESS_PATTERN = re.compile(r"\[download\]\s+(?P<percent>\d+(?:\.\d+)?)%")
# Some videos expose only a combined format. Keep an audio-only preference but
# allow yt-dlp's best audio-containing fallback so ffprobe can validate the
# resulting source instead of failing before download.
_YOUTUBE_FORMAT_SELECTOR = "bestaudio/best"
_URL_PATTERN = re.compile(r"https?://\S+")


class YouTubeUrlError(ValueError):
    """The submitted URL is not one individual HTTPS YouTube video."""


@dataclass(frozen=True)
class YouTubeSource:
    canonical_url: str
    video_id: str


def classify_youtube_url(value: str) -> YouTubeSource:
    """Validate and canonicalize a supported individual YouTube video URL."""

    if not isinstance(value, str) or len(value) > 2048:
        raise YouTubeUrlError("Enter an HTTPS URL for one YouTube video.")

    try:
        parsed = urlsplit(value.strip())
        hostname = parsed.hostname.lower() if parsed.hostname else ""
        port = parsed.port
    except ValueError as exc:
        raise YouTubeUrlError("Enter a valid YouTube URL.") from exc

    if (
        parsed.scheme.lower() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        raise YouTubeUrlError("YouTube URLs must use HTTPS without credentials or a custom port.")

    if hostname in _YOUTUBE_HOSTS:
        if parsed.path != "/watch":
            raise YouTubeUrlError("Only individual YouTube video URLs are supported.")
        query = parse_qs(parsed.query, keep_blank_values=True)
        # A watch URL with an explicit v= value still identifies one video.
        # YouTube commonly adds list=RD... and start_radio=1 to address-bar
        # links; canonicalize those queue-context parameters away instead of
        # rejecting an otherwise valid individual-video source.
        video_values = query.get("v", [])
        if len(video_values) != 1:
            raise YouTubeUrlError("The YouTube URL must identify one video.")
        video_id = video_values[0]
    elif hostname in _SHORT_YOUTUBE_HOSTS:
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) != 1:
            raise YouTubeUrlError("Only individual YouTube video URLs are supported.")
        video_id = unquote(path_parts[0])
    else:
        raise YouTubeUrlError("Only youtube.com and youtu.be URLs are supported.")

    if not _VIDEO_ID_PATTERN.fullmatch(video_id):
        raise YouTubeUrlError("The YouTube URL does not contain a valid video ID.")
    return YouTubeSource(
        canonical_url=f"https://www.youtube.com/watch?v={video_id}",
        video_id=video_id,
    )


def _clean_text(value: Any, limit: int = 400) -> str | None:
    if value is None:
        return None
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value))
    text = " ".join(text.split()).strip()
    return text[:limit] or None


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _known_download_size(info: dict[str, Any]) -> int | None:
    """Return the selected audio size when yt-dlp can determine it preflight."""

    requested_formats = info.get("requested_formats")
    if isinstance(requested_formats, list) and requested_formats:
        sizes = [
            _finite_number(format_info.get("filesize") or format_info.get("filesize_approx"))
            for format_info in requested_formats
            if isinstance(format_info, dict)
        ]
        known_sizes = [size for size in sizes if size is not None]
        if known_sizes:
            return math.ceil(sum(known_sizes))

    for key in ("filesize", "filesize_approx"):
        size = _finite_number(info.get(key))
        if size is not None:
            return math.ceil(size)
    return None


def map_youtube_metadata(info: dict[str, Any], source: YouTubeSource) -> dict[str, Any]:
    """Keep only bounded provenance and preflight fields from yt-dlp output."""

    if info.get("_type") not in (None, "video"):
        raise ProcessingError("Only individual YouTube videos are supported.")
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
        raise ProcessingError("Live YouTube streams are not supported.")
    resolved_id = _clean_text(info.get("id"), 64)
    if resolved_id and resolved_id != source.video_id:
        raise ProcessingError("The YouTube URL resolved to a different video.")
    if resolved_id and not _VIDEO_ID_PATTERN.fullmatch(resolved_id):
        raise ProcessingError("YouTube returned an invalid video ID.")

    metadata = {
        "canonical_url": source.canonical_url,
        "video_id": source.video_id,
        "title": _clean_text(info.get("title")) or f"YouTube video {source.video_id}",
        "uploader": _clean_text(info.get("uploader")),
        "uploader_id": _clean_text(info.get("uploader_id"), 200),
        "channel": _clean_text(info.get("channel")),
        "channel_id": _clean_text(info.get("channel_id"), 200),
        "extractor": _clean_text(info.get("extractor_key") or info.get("extractor"), 200),
        "duration_seconds": _finite_number(info.get("duration")),
        "size_bytes": _known_download_size(info),
    }
    duration = metadata["duration_seconds"]
    if duration is not None and duration > MAX_DURATION_SECONDS:
        limit_minutes = int(MAX_DURATION_SECONDS // 60)
        raise ProcessingError(
            f"The YouTube audio must be {limit_minutes} minutes or shorter."
        )
    size = metadata["size_bytes"]
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise ProcessingError(
            f"The YouTube audio is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )
    return metadata


def _sanitized_diagnostic(value: str, limit: int = 2000) -> str:
    value = _URL_PATTERN.sub("[url]", value)
    value = re.sub(r"[\x00-\x1f\x7f]", " ", value)
    return value.strip()[:limit]


def _log_output(log, text: str) -> None:
    for line in text.splitlines():
        if line.strip():
            log.write(_sanitized_diagnostic(line) + "\n")
    log.flush()


def _metadata_from_output(stdout: str) -> dict[str, Any]:
    try:
        metadata = json.loads(stdout.strip())
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProcessingError("YouTube did not return readable video metadata.") from exc
    if not isinstance(metadata, dict):
        raise ProcessingError("YouTube returned invalid video metadata.")
    return metadata


def _resolve_metadata(source: YouTubeSource, log) -> dict[str, Any]:
    command = [
        *ytdlp_command(),
        "--ignore-config",
        "--no-playlist",
        "--use-extractors",
        "youtube",
        "--no-warnings",
        "--dump-single-json",
        "--skip-download",
        "--format",
        _YOUTUBE_FORMAT_SELECTOR,
        "--socket-timeout",
        str(YOUTUBE_SOCKET_TIMEOUT_SECONDS),
        source.canonical_url,
    ]
    log.write("$ " + " ".join("[url]" if part == source.canonical_url else part for part in command) + "\n")
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=YOUTUBE_METADATA_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProcessingError("Timed out while reading YouTube video details.") from exc
    except OSError as exc:
        raise ProcessingError(f"Could not start yt-dlp: {exc}") from exc

    _log_output(log, result.stderr or "")
    if result.returncode != 0:
        detail = _sanitized_diagnostic(result.stderr or result.stdout or "")
        raise ProcessingError(
            "yt-dlp could not read this YouTube video."
            + (f" {detail[-800:]}" if detail else "")
        )
    _log_output(log, result.stdout or "")
    return _metadata_from_output(result.stdout)


def _downloaded_source_size(job_dir: Path) -> int:
    sizes = []
    for path in job_dir.glob("source.*"):
        if path.is_file():
            try:
                sizes.append(path.stat().st_size)
            except OSError:
                pass
    return max(sizes, default=0)


def _stop_process(process) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _download_audio(source: YouTubeSource, job_dir: Path, log, update: ProgressCallback) -> Path:
    output_template = str(job_dir / "source.%(ext)s")
    command = [
        *ytdlp_command(),
        "--ignore-config",
        "--no-playlist",
        "--use-extractors",
        "youtube",
        "--no-warnings",
        "--no-mtime",
        "--no-write-info-json",
        "--no-write-thumbnail",
        "--no-write-description",
        "--no-write-subs",
        "--no-write-auto-subs",
        "--format",
        _YOUTUBE_FORMAT_SELECTOR,
        "--output",
        output_template,
        "--max-filesize",
        str(MAX_UPLOAD_BYTES),
        "--socket-timeout",
        str(YOUTUBE_SOCKET_TIMEOUT_SECONDS),
        "--newline",
        "--progress",
        source.canonical_url,
    ]
    log.write("$ " + " ".join("[url]" if part == source.canonical_url else part for part in command) + "\n")
    log.flush()

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise ProcessingError(f"Could not start yt-dlp: {exc}") from exc
    if process.stdout is None:
        raise ProcessingError("Could not read yt-dlp progress output.")

    output_queue: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        try:
            for line in process.stdout:
                output_queue.put(line)
        finally:
            output_queue.put(None)

    reader = threading.Thread(target=read_output, name="youtube-download-output", daemon=True)
    reader.start()
    output_tail: deque[str] = deque(maxlen=30)
    started = time.monotonic()
    deadline = started + YOUTUBE_DOWNLOAD_TIMEOUT_SECONDS
    last_update_at = 0.0
    last_progress = -1
    reader_finished = False
    timed_out = False
    too_large = False

    while not reader_finished:
        try:
            line = output_queue.get(timeout=0.2)
        except queue.Empty:
            line = ""
        if line is None:
            reader_finished = True
        elif line:
            log.write(_sanitized_diagnostic(line) + "\n")
            log.flush()
            stripped = line.strip()
            if stripped:
                output_tail.append(stripped)
            match = _DOWNLOAD_PROGRESS_PATTERN.search(line)
            if match:
                progress = min(99, max(0, round(float(match.group("percent")))))
                now = time.monotonic()
                if progress != last_progress and (now - last_update_at >= 0.3 or progress == 99):
                    update(progress=progress, message="Downloading audio from YouTube")
                    last_progress = progress
                    last_update_at = now

        if _downloaded_source_size(job_dir) > MAX_UPLOAD_BYTES:
            too_large = True
            _stop_process(process)
            break
        if time.monotonic() > deadline:
            timed_out = True
            _stop_process(process)
            break
        if process.poll() is not None and reader_finished:
            break

    if timed_out:
        raise ProcessingError("The YouTube audio download timed out.")
    if too_large:
        raise ProcessingError(
            f"The YouTube audio is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    return_code = process.wait()
    if return_code != 0:
        detail = _sanitized_diagnostic("\n".join(output_tail))
        raise ProcessingError(
            "yt-dlp could not download this YouTube video."
            + (f" {detail[-1000:]}" if detail else "")
        )

    candidates = [
        path
        for path in job_dir.glob("source.*")
        if path.is_file() and not path.name.endswith(".part")
    ]
    if len(candidates) != 1:
        raise ProcessingError("yt-dlp finished without producing one audio source file.")
    source_path = candidates[0]
    try:
        size = source_path.stat().st_size
    except OSError as exc:
        raise ProcessingError("Could not inspect the downloaded YouTube audio.") from exc
    if size <= 0:
        raise ProcessingError("The downloaded YouTube audio is empty.")
    if size > MAX_UPLOAD_BYTES:
        raise ProcessingError(
            f"The YouTube audio is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )
    update(progress=100, message="YouTube audio downloaded")
    return source_path


def _remove_download_artifacts(job_dir: Path) -> None:
    for path in job_dir.glob("source.*"):
        try:
            path.unlink()
        except OSError:
            pass


def _display_name(title: str | None, video_id: str) -> str:
    value = _clean_text(title) or f"YouTube video {video_id}"
    value = re.sub(r'[<>:"/\\|?*]', "_", value).strip(" .")
    return value[:180] or f"YouTube video {video_id}"


def ingest_youtube_job(
    job_dir: Path,
    source_url: str,
    update: ProgressCallback,
) -> str:
    """Resolve, download, and persist one validated YouTube source."""

    if importlib.util.find_spec("yt_dlp") is None:
        raise ProcessingError("Missing required tool: yt-dlp. Run the setup instructions in README.md.")
    try:
        source = classify_youtube_url(source_url)
    except YouTubeUrlError as exc:
        raise ProcessingError(str(exc)) from exc

    log_path = job_dir / "yt-dlp.log"
    with log_path.open("w", encoding="utf-8") as log:
        update(
            status="ingesting",
            progress=0,
            message="Reading YouTube video details",
            eta_seconds=None,
        )
        metadata = map_youtube_metadata(_resolve_metadata(source, log), source)
        update(
            original_filename=_display_name(metadata["title"], source.video_id),
            source_url=source.canonical_url,
            canonical_url=metadata["canonical_url"],
            video_id=metadata["video_id"],
            title=metadata["title"],
            uploader=metadata["uploader"],
            uploader_id=metadata["uploader_id"],
            channel=metadata["channel"],
            channel_id=metadata["channel_id"],
            extractor=metadata["extractor"],
            duration_seconds=metadata["duration_seconds"],
            message="Downloading audio from YouTube",
        )
        try:
            source_path = _download_audio(source, job_dir, log, update)
        except Exception:
            _remove_download_artifacts(job_dir)
            raise

    fetched_at = datetime.now(timezone.utc).isoformat()
    size_bytes = source_path.stat().st_size
    update(
        source_filename=source_path.name,
        size_bytes=size_bytes,
        fetched_at=fetched_at,
        progress=100,
        message="YouTube audio downloaded",
    )
    return source_path.name
