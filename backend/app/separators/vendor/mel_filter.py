"""Fixed Slaney mel filter bank for the pinned 44.1 kHz RoFormer model.

This is the small equivalent of librosa.filters.mel with its default Slaney
normalization. Keeping it local avoids pulling the broad librosa dependency into
the desktop runtime.
"""

from __future__ import annotations

import numpy as np


_MIN_LOG_HZ = 1000.0
_MIN_LOG_MEL = 15.0
_HZ_SPACING = 200.0 / 3.0
_LOG_STEP = np.log(6.4) / 27.0


def _hz_to_mel(frequency: np.ndarray) -> np.ndarray:
    frequency = np.asarray(frequency, dtype=np.float64)
    log_frequency = np.maximum(frequency, _MIN_LOG_HZ)
    return np.where(
        frequency < _MIN_LOG_HZ,
        frequency / _HZ_SPACING,
        _MIN_LOG_MEL + np.log(log_frequency / _MIN_LOG_HZ) / _LOG_STEP,
    )


def _mel_to_hz(mel: np.ndarray) -> np.ndarray:
    mel = np.asarray(mel, dtype=np.float64)
    return np.where(
        mel < _MIN_LOG_MEL,
        mel * _HZ_SPACING,
        _MIN_LOG_HZ * np.exp(_LOG_STEP * (mel - _MIN_LOG_MEL)),
    )


def fixed_slaney_mel(sr: int, n_fft: int, n_mels: int) -> np.ndarray:
    """Return the pinned librosa-compatible Slaney filter bank."""

    if sr != 44100 or n_fft != 2048 or n_mels != 60:
        raise ValueError("The MelBand RoFormer filter is pinned to 44.1 kHz/2048/60.")

    min_frequency = 0.0
    max_frequency = sr / 2.0
    mel_points = np.linspace(
        _hz_to_mel(np.asarray(min_frequency)),
        _hz_to_mel(np.asarray(max_frequency)),
        n_mels + 2,
    )
    frequencies = _mel_to_hz(mel_points)
    fft_frequencies = np.fft.rfftfreq(n=n_fft, d=1.0 / sr)
    ramps = frequencies[:, None] - fft_frequencies[None, :]

    lower = -ramps[:-2] / (ramps[1:-1] - ramps[:-2])
    upper = ramps[2:] / (ramps[2:] - ramps[1:-1])
    weights = np.maximum(0.0, np.minimum(lower, upper))

    # Slaney normalization used by librosa's default norm="slaney".
    enorm = 2.0 / (frequencies[2 : n_mels + 2] - frequencies[:n_mels])
    weights *= enorm[:, None]
    return weights.astype(np.float32, copy=False)


__all__ = ["fixed_slaney_mel"]
