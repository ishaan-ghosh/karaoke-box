from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..profiles import DEFAULT_QUALITY, SeparationQuality, get_profile

SeparatorEngine = Literal["demucs", "melband_roformer"]
DEMUCS_ENGINE: Literal["demucs"] = "demucs"
DEFAULT_SEPARATOR_ENGINE: SeparatorEngine = DEMUCS_ENGINE
MELBAND_ROFORMER_ENGINE: Literal["melband_roformer"] = "melband_roformer"
MELBAND_ROFORMER_MODEL = "kimberley_melband_roformer_v1"


@dataclass(frozen=True)
class ResolvedSelection:
    """Validated, durable engine/model selection for a job."""

    separator_engine: SeparatorEngine
    separator_model: str
    quality: SeparationQuality

    @property
    def engine(self) -> SeparatorEngine:
        return self.separator_engine

    @property
    def model(self) -> str:
        return self.separator_model


def resolve_selection(
    separator_engine: str = DEFAULT_SEPARATOR_ENGINE,
    quality: SeparationQuality = DEFAULT_QUALITY,
) -> ResolvedSelection:
    """Resolve a public engine/profile pair to its exact persisted model."""

    if separator_engine == MELBAND_ROFORMER_ENGINE:
        if quality != "preserve":
            raise ValueError(
                "The MelBand RoFormer engine only supports the preserve quality profile."
            )
        return ResolvedSelection(
            separator_engine=MELBAND_ROFORMER_ENGINE,
            separator_model=MELBAND_ROFORMER_MODEL,
            quality=quality,
        )

    if separator_engine != DEMUCS_ENGINE:
        raise ValueError(f"Unknown separator engine: {separator_engine}")

    # get_profile resolves configured Demucs model names. Convert its lookup
    # failure into the same public validation error used for engine selection.
    try:
        profile = get_profile(quality)
    except (KeyError, TypeError) as exc:
        raise ValueError(f"Unknown separation quality: {quality}") from exc
    return ResolvedSelection(
        separator_engine=DEMUCS_ENGINE,
        separator_model=profile.model,
        quality=quality,
    )
