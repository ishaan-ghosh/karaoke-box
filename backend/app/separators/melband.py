"""MelBand RoFormer separator adapter and streamed progress parser."""

from __future__ import annotations

import json
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from ..config import MODELS_DIR
from ..profiles import SeparationQuality
from ..runtime import resolve_tool, separator_worker_command, separator_worker_cwd
from .base import ProcessingError, ProgressCallback, SeparatedStems
from .catalog import MELBAND_ROFORMER_ENGINE, MELBAND_ROFORMER_MODEL
from .model_cache import MELBAND_MODEL_MANIFEST, ensure_model

PROGRESS_PREFIX = "KARAOKE_PROGRESS "


@dataclass(frozen=True)
class MelBandProgress:
    fraction: float
    completed_chunks: int
    total_chunks: int
    eta_seconds: int | None = None


class MelBandProgressTracker:
    """Parse the worker's explicit line-oriented chunk protocol and ETA."""

    def __init__(self) -> None:
        self.total_chunks = 1
        self.completed_chunks = 0
        self.started_at: float | None = None

    def feed(self, line: str, now: float | None = None) -> MelBandProgress | None:
        if not line.startswith(PROGRESS_PREFIX):
            return None
        try:
            payload = json.loads(line[len(PROGRESS_PREFIX) :])
            completed_value = payload.get("completed_chunks")
            total_value = payload.get("total_chunks")
            if completed_value is None:
                completed_value = payload["completed"]
            if total_value is None:
                total_value = payload["total"]
            completed = int(completed_value)
            total = int(total_value)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if total <= 0 or completed < 0:
            return None
        self.total_chunks = total
        self.completed_chunks = min(completed, total)
        fraction = self.completed_chunks / self.total_chunks
        timestamp = time.monotonic() if now is None else now
        if self.started_at is None and fraction <= 0.0:
            self.started_at = timestamp
        eta_seconds: int | None = None
        if self.started_at is not None and fraction > 0.0 and fraction < 1.0:
            elapsed = max(0.0, timestamp - self.started_at)
            eta_seconds = max(1, round(elapsed * (1.0 - fraction) / fraction))
        return MelBandProgress(
            fraction=fraction,
            completed_chunks=self.completed_chunks,
            total_chunks=self.total_chunks,
            eta_seconds=eta_seconds,
        )


class MelBandAdapter:
    """Pinned model preparation and CPU subprocess invocation."""

    def prepare(
        self,
        *,
        job_dir: Path,
        source: Path,
        update: ProgressCallback,
        quality: SeparationQuality,
        model: str,
    ) -> None:
        if quality != "preserve" or model != MELBAND_ROFORMER_MODEL:
            raise ProcessingError("The MelBand RoFormer selection is invalid.")
        work_dir = job_dir / "separator-output"
        work_dir.mkdir(parents=True, exist_ok=True)
        update(
            status="preparing",
            progress=0,
            message="Verifying the MelBand RoFormer model",
            eta_seconds=None,
        )

        def model_progress(downloaded: int, total: int) -> None:
            update(
                status="preparing",
                progress=min(100, round(downloaded * 100 / total)) if total else 0,
                message="Downloading the MelBand RoFormer model",
                eta_seconds=None,
            )

        ensure_model(MELBAND_MODEL_MANIFEST, models_dir=MODELS_DIR, progress=model_progress)
        ffmpeg = resolve_tool("ffmpeg")
        if ffmpeg is None:
            raise ProcessingError("Missing required tool: ffmpeg.")
        input_path = work_dir / "input.f32le"
        command = [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-f",
            "f32le",
            str(input_path),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0 or not input_path.is_file():
            detail = (result.stderr or "ffmpeg could not normalize the input audio").strip()
            raise ProcessingError(f"Could not prepare MelBand input audio: {detail[-800:]}")
        update(
            status="separating",
            progress=0,
            message="Separating vocals with MelBand RoFormer on CPU",
            eta_seconds=None,
            current_pass=1,
            total_passes=1,
        )

    def separate(
        self,
        *,
        job_dir: Path,
        source: Path,
        update: ProgressCallback,
        quality: SeparationQuality,
        model: str,
    ) -> SeparatedStems:
        if quality != "preserve" or model != MELBAND_ROFORMER_MODEL:
            raise ProcessingError("The MelBand RoFormer selection is invalid.")
        work_dir = job_dir / "separator-output"
        input_path = work_dir / "input.f32le"
        if not input_path.is_file():
            raise ProcessingError("MelBand input preparation did not produce an audio buffer.")
        # Verify the persistent model immediately before passing it to the child.
        model_path = ensure_model(MELBAND_MODEL_MANIFEST, models_dir=MODELS_DIR)
        output_dir = work_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = job_dir / "melband-roformer.log"
        command = [
            *separator_worker_command(),
            "--model-path",
            str(model_path),
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--model-id",
            model,
        ]
        tracker = MelBandProgressTracker()
        output_tail: deque[str] = deque(maxlen=40)
        last_update_at = 0.0
        last_progress = -1
        with log_path.open("w", encoding="utf-8") as log:
            log.write(f"$ {' '.join(command)}\n\nOUTPUT\n")
            log.flush()
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
                cwd=separator_worker_cwd(),
            )
            if process.stdout is None:
                raise ProcessingError("Could not read MelBand worker progress output.")
            for output_line in process.stdout:
                log.write(output_line)
                stripped = output_line.strip()
                if stripped:
                    output_tail.append(stripped)
                snapshot = tracker.feed(output_line)
                if snapshot is None:
                    continue
                progress = min(100, round(snapshot.fraction * 100))
                now = time.monotonic()
                if progress != last_progress and (now - last_update_at >= 0.4 or progress == 100):
                    update(
                        status="separating",
                        progress=progress,
                        eta_seconds=snapshot.eta_seconds,
                        current_pass=1,
                        total_passes=1,
                    )
                    last_progress = progress
                    last_update_at = now
            return_code = process.wait()
        if return_code != 0:
            detail = "\n".join(output_tail)
            raise ProcessingError(
                "MelBand RoFormer could not separate this track. "
                f"See {log_path.name} for details. {detail[-1000:]}"
            )
        instrumental = output_dir / "instrumental.wav"
        vocals = output_dir / "vocals.wav"
        if not instrumental.is_file() or not vocals.is_file():
            raise ProcessingError("MelBand RoFormer finished without producing the expected stems.")
        return SeparatedStems(instrumental, vocals)


__all__ = ["MelBandAdapter", "MelBandProgress", "MelBandProgressTracker", "PROGRESS_PREFIX"]
