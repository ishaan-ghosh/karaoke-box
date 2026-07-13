from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .config import DEMUCS_BEST_MODEL, DEMUCS_MODEL

SeparationQuality = Literal["preserve", "best", "standard"]
DEFAULT_QUALITY: SeparationQuality = "preserve"


@dataclass(frozen=True)
class SeparationProfile:
    model: str
    other_method: Literal["add", "minus"]
    instrumental_stem: Literal["no_vocals", "minus_vocals"]
    progress_message: str


QUALITY_PROFILES: dict[SeparationQuality, SeparationProfile] = {
    "preserve": SeparationProfile(
        model=DEMUCS_MODEL,
        other_method="minus",
        instrumental_stem="minus_vocals",
        progress_message="Preserving the backing while removing predicted vocals",
    ),
    "best": SeparationProfile(
        model=DEMUCS_BEST_MODEL,
        other_method="minus",
        instrumental_stem="minus_vocals",
        progress_message="Running the fine-tuned model on CPU — this will take longer",
    ),
    "standard": SeparationProfile(
        model=DEMUCS_MODEL,
        other_method="add",
        instrumental_stem="no_vocals",
        progress_message="Separating and summing the predicted instrument stems",
    ),
}


def get_profile(quality: SeparationQuality) -> SeparationProfile:
    return QUALITY_PROFILES[quality]
