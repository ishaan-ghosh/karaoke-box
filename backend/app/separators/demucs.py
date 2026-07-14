from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import time
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path

from ..profiles import SeparationQuality, get_profile
from ..runtime import demucs_command
from .base import ProcessingError, ProgressCallback, SeparatedStems

_BAG_SIZE_PATTERN = re.compile(r"Selected model is a bag of (?P<count>\d+) models?")
_PROGRESS_PATTERN = re.compile(
    r"(?P<percent>\d{1,3})%\|.*?\|\s*"
    r"(?P<current>\d+(?:\.\d+)?)/(?P<total>\d+(?:\.\d+)?)\s*"
    r"\[[^\]]*(?:seconds/s|s/seconds)\]"
)


@dataclass(frozen=True)
class DemucsProgress:
    fraction: float
    current_pass: int
    total_passes: int


class DemucsProgressTracker:
    """Combine Demucs/tqdm progress bars into one fraction across model passes."""

    def __init__(self, expected_passes: int):
        self.total_passes = max(1, expected_passes)
        self.current_pass = 1
        self._last_pass_fraction = 0.0

    def feed(self, line: str) -> DemucsProgress | None:
        bag_match = _BAG_SIZE_PATTERN.search(line)
        if bag_match:
            self.total_passes = max(1, int(bag_match.group("count")))

        progress_match = _PROGRESS_PATTERN.search(line)
        if progress_match is None:
            return None

        current = float(progress_match.group("current"))
        total = float(progress_match.group("total"))
        if total <= 0:
            return None
        pass_fraction = min(1.0, max(0.0, current / total))

        # tqdm prints a fresh bar for every model in a bag. A reset after a nearly
        # complete bar marks the next pass; duplicate 100% lines remain in one pass.
        if pass_fraction < 0.1 and self._last_pass_fraction >= 0.9:
            self.current_pass = min(self.total_passes, self.current_pass + 1)
        self._last_pass_fraction = pass_fraction

        completed_passes = self.current_pass - 1
        overall = (completed_passes + pass_fraction) / self.total_passes
        return DemucsProgress(
            fraction=min(1.0, overall),
            current_pass=self.current_pass,
            total_passes=self.total_passes,
        )


def _demucs_output_path(work_dir: Path, model: str, stem: str) -> Path:
    model_directory = model.replace("hf://", "").replace("/", "_")
    return work_dir / model_directory / "source" / f"{stem}.wav"


class DemucsAdapter:
    """Current Demucs implementation, kept semantically identical to the MVP."""

    def prepare(
        self,
        *,
        job_dir: Path,
        source: Path,
        update: ProgressCallback,
        quality: SeparationQuality,
        model: str,
    ) -> None:
        if importlib.util.find_spec("demucs") is None:
            raise ProcessingError(
                "Missing required tool: demucs. Run the setup instructions in README.md."
            )
        # Demucs has no separate model-preparation protocol. Its subprocess
        # performs any one-time model setup before the first progress line.
        return None

    def separate(
        self,
        *,
        job_dir: Path,
        source: Path,
        update: ProgressCallback,
        quality: SeparationQuality,
        model: str,
    ) -> SeparatedStems:
        work_dir = job_dir / "demucs-output"
        log_path = job_dir / "demucs.log"
        profile = replace(get_profile(quality), model=model)

        command = [
            *demucs_command(),
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
        tracker = DemucsProgressTracker(profile.model_passes)
        process_started_at = time.monotonic()
        work_started_at: float | None = None
        last_update_at = 0.0
        last_progress = -1
        output_tail: deque[str] = deque(maxlen=40)

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
            )
            if process.stdout is None:
                raise ProcessingError("Could not read Demucs progress output.")

            for output_line in process.stdout:
                log.write(output_line)
                stripped = output_line.strip()
                if stripped:
                    output_tail.append(stripped)

                snapshot = tracker.feed(output_line)
                if snapshot is None:
                    continue

                now = time.monotonic()
                progress = min(100, round(snapshot.fraction * 100))
                if work_started_at is None:
                    # Demucs emits a 0% bar after model download/loading. Starting
                    # here avoids treating one-time setup as recurring work in ETA.
                    work_started_at = now if snapshot.fraction < 0.01 else process_started_at
                elapsed = max(0.0, now - work_started_at)
                eta_seconds = None
                if snapshot.fraction >= 0.01 and snapshot.fraction < 1:
                    eta_seconds = max(
                        1,
                        round(elapsed * (1 - snapshot.fraction) / snapshot.fraction),
                    )

                # Polling is once per second, so avoid rewriting job.json for every
                # tqdm refresh while still emitting changed percentages promptly.
                if progress != last_progress and (now - last_update_at >= 0.4 or progress == 100):
                    update(
                        progress=progress,
                        eta_seconds=eta_seconds,
                        current_pass=snapshot.current_pass,
                        total_passes=snapshot.total_passes,
                    )
                    last_progress = progress
                    last_update_at = now

            return_code = process.wait()

        if return_code != 0:
            detail = "\n".join(output_tail)
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

        return SeparatedStems(instrumental_source, vocals_source)


__all__ = [
    "DemucsAdapter",
    "DemucsProgress",
    "DemucsProgressTracker",
    "_demucs_output_path",
]
