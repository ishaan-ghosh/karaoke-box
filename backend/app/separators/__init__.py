"""Separator engine adapters used by the source-neutral processing pipeline."""

from .base import ProcessingError, SeparatedStems, SeparatorAdapter
from .catalog import (
    DEFAULT_SEPARATOR_ENGINE,
    MELBAND_ROFORMER_ENGINE,
    MELBAND_ROFORMER_MODEL,
    DEMUCS_ENGINE,
    ResolvedSelection,
    SeparatorEngine,
    resolve_selection,
)
from .registry import get_separator_adapter

__all__ = [
    "DEMUCS_ENGINE",
    "DEFAULT_SEPARATOR_ENGINE",
    "MELBAND_ROFORMER_ENGINE",
    "MELBAND_ROFORMER_MODEL",
    "ProcessingError",
    "ResolvedSelection",
    "SeparatedStems",
    "SeparatorAdapter",
    "SeparatorEngine",
    "get_separator_adapter",
    "resolve_selection",
]
