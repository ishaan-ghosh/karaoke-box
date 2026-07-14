from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..profiles import SeparationQuality

ProgressCallback = Callable[..., None]


class ProcessingError(RuntimeError):
    """An expected media-processing failure that can be shown to the user."""


@dataclass(frozen=True)
class SeparatedStems:
    """Scratch output returned by a separator before stable job finalization."""

    instrumental: Path
    vocals: Path


class SeparatorAdapter(Protocol):
    """Engine-specific preparation and separation contract."""

    def prepare(
        self,
        *,
        job_dir: Path,
        source: Path,
        update: ProgressCallback,
        quality: SeparationQuality,
        model: str,
    ) -> None: ...

    def separate(
        self,
        *,
        job_dir: Path,
        source: Path,
        update: ProgressCallback,
        quality: SeparationQuality,
        model: str,
    ) -> SeparatedStems: ...
