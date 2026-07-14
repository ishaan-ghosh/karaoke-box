from __future__ import annotations

from pathlib import Path

from ..profiles import SeparationQuality
from .base import ProcessingError, ProgressCallback, SeparatedStems, SeparatorAdapter
from .catalog import (
    DEMUCS_ENGINE,
    MELBAND_ROFORMER_ENGINE,
    ResolvedSelection,
    SeparatorEngine,
)
from .demucs import DemucsAdapter


class _LazyMelBandAdapter:
    """Load optional RoFormer dependencies only when that engine is selected."""

    def _adapter(self) -> SeparatorAdapter:
        try:
            from .melband import MelBandAdapter
        except ImportError as exc:
            raise ProcessingError(
                "The MelBand RoFormer dependencies are not installed. Run the setup instructions in README.md."
            ) from exc
        return MelBandAdapter()

    def prepare(self, **kwargs: object) -> None:
        self._adapter().prepare(**kwargs)  # type: ignore[arg-type]

    def separate(self, **kwargs: object) -> SeparatedStems:
        return self._adapter().separate(**kwargs)  # type: ignore[arg-type]


_ADAPTERS: dict[SeparatorEngine, SeparatorAdapter] = {
    DEMUCS_ENGINE: DemucsAdapter(),
    MELBAND_ROFORMER_ENGINE: _LazyMelBandAdapter(),
}


def get_separator_adapter(selection: ResolvedSelection | SeparatorEngine) -> SeparatorAdapter:
    engine = selection.separator_engine if isinstance(selection, ResolvedSelection) else selection
    try:
        return _ADAPTERS[engine]
    except KeyError as exc:
        raise ProcessingError(f"Unknown separator engine: {engine}") from exc


# Short alias for adapter callers and focused tests.
get_adapter = get_separator_adapter


__all__ = ["get_adapter", "get_separator_adapter"]
