"""Private CPU-only MelBand RoFormer worker.

The parent process invokes this module with server-created paths. It deliberately
has no network or model-cache behavior: model verification belongs to MelBandAdapter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# This must happen before importing torch or any vendored model module.
os.environ["CUDA_VISIBLE_DEVICES"] = ""

import numpy as np
import torch

from .catalog import MELBAND_ROFORMER_MODEL
from .model_cache import MODEL_EXPECTED_SIZE, MODEL_SHA256
from .vendor.mel_band_roformer import MelBandRoformer

SAMPLE_RATE = 44100
CHANNELS = 2
CHUNK_SIZE = 485100
STEP_SIZE = 352800
MODEL_CONFIG_REFERENCE = Path(__file__).with_name("models") / "config_vocals_mel_band_roformer_kj.yaml"
MODEL_CONFIG_INFERENCE = Path(__file__).with_name("models") / "vocals_mel_band_roformer.yaml"
MODEL_CONFIG_REFERENCE_SHA256 = "f63f38eb1e6e40a7db0dade714a5ae257555dd8748f4e774eae8679275a81926"
MODEL_CONFIG_INFERENCE_SHA256 = "b958b29c8f7195f0d86bee6759a33980db675c4ecaf2fcaa80fa125828e6cd38"
ProgressCallback = Callable[[int, int], None]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pinned_runtime() -> None:
    if MELBAND_ROFORMER_MODEL != "kimberley_melband_roformer_v1":
        raise RuntimeError("Unsupported MelBand model catalog entry.")
    if (
        MODEL_EXPECTED_SIZE != 913106900
        or MODEL_SHA256 != "87201f4d31afb5bc79993230fc49446918425574db48c01c405e44f365c7559e"
    ):
        raise RuntimeError("Invalid pinned MelBand model manifest.")
    for path, expected in (
        (MODEL_CONFIG_REFERENCE, MODEL_CONFIG_REFERENCE_SHA256),
        (MODEL_CONFIG_INFERENCE, MODEL_CONFIG_INFERENCE_SHA256),
    ):
        if not path.is_file() or _sha256(path) != expected:
            raise RuntimeError(f"Pinned MelBand configuration is invalid: {path.name}")
    device = torch.device("cpu")
    if device.type != "cpu":
        raise RuntimeError("MelBand worker must use CPU.")


def _scale_if_needed(audio: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 1.0:
        return audio / peak
    return audio


def load_raw_audio(path: Path) -> np.ndarray:
    raw = np.fromfile(path, dtype="<f4")
    if raw.size == 0 or raw.size % CHANNELS:
        raise RuntimeError("The normalized input is not stereo float32 audio.")
    audio = raw.reshape(-1, CHANNELS).T.astype(np.float32, copy=False)
    return _scale_if_needed(audio)


def _model_output_to_array(output: Any) -> np.ndarray:
    if isinstance(output, (tuple, list)):
        output = output[0]
    if isinstance(output, torch.Tensor):
        output = output.detach().to("cpu").float().numpy()
    output = np.asarray(output, dtype=np.float32)
    if output.ndim == 4:
        output = output[:, 0]
    if output.ndim == 3:
        output = output[0]
    if output.ndim != 2:
        raise RuntimeError("MelBand model returned an unexpected tensor shape.")
    if output.shape[0] != CHANNELS and output.shape[1] == CHANNELS:
        output = output.T
    if output.shape[0] != CHANNELS:
        raise RuntimeError("MelBand model did not return stereo vocals.")
    return output


def _predict_chunk(model: Any, chunk: np.ndarray) -> np.ndarray:
    # The vendored model accepts [batch, channels, samples]. A fake model with
    # the same shape contract can be used for deterministic short-array tests.
    tensor = torch.from_numpy(chunk).unsqueeze(0)
    with torch.no_grad():
        result = model(tensor)
    vocals = _model_output_to_array(result)
    if vocals.shape[1] < CHUNK_SIZE:
        vocals = np.pad(vocals, ((0, 0), (0, CHUNK_SIZE - vocals.shape[1])))
    return vocals[:, :CHUNK_SIZE]


def separate_chunks(
    model: Any,
    normalized_mix: np.ndarray,
    progress: ProgressCallback | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Run chunked CPU inference and return ``(vocals, instrumental)`` arrays."""

    if normalized_mix.ndim != 2 or normalized_mix.shape[0] != CHANNELS:
        raise ValueError("MelBand input must have shape [2, samples].")
    sample_count = normalized_mix.shape[1]
    total_chunks = max(1, (sample_count + STEP_SIZE - 1) // STEP_SIZE)
    vocals_accum = np.zeros((CHANNELS, sample_count), dtype=np.float64)
    weight_accum = np.zeros(sample_count, dtype=np.float64)
    window = np.hamming(CHUNK_SIZE).astype(np.float64)

    for completed, start in enumerate(range(0, sample_count, STEP_SIZE), start=1):
        actual_length = min(CHUNK_SIZE, sample_count - start)
        chunk = normalized_mix[:, start : start + actual_length]
        if actual_length < CHUNK_SIZE:
            chunk = np.pad(chunk, ((0, 0), (0, CHUNK_SIZE - actual_length)))
        predicted = _predict_chunk(model, chunk)
        vocals_accum[:, start : start + actual_length] += (
            predicted[:, :actual_length] * window[:actual_length]
        )
        weight_accum[start : start + actual_length] += window[:actual_length]
        if progress is not None:
            progress(completed, total_chunks)

    weights = np.maximum(weight_accum, np.finfo(np.float64).eps)
    vocals = (vocals_accum / weights[None, :]).astype(np.float32)
    instrumental = normalized_mix - vocals
    # Apply independent safety scaling only after the residual is computed.
    vocals = _scale_if_needed(vocals)
    instrumental = _scale_if_needed(instrumental)
    return vocals, instrumental


def _build_model() -> MelBandRoformer:
    model = MelBandRoformer(
        dim=384,
        depth=6,
        stereo=True,
        num_stems=1,
        time_transformer_depth=1,
        freq_transformer_depth=1,
        num_bands=60,
        dim_head=64,
        heads=8,
        attn_dropout=0.0,
        ff_dropout=0.0,
        flash_attn=True,
        dim_freqs_in=1025,
        sample_rate=SAMPLE_RATE,
        stft_n_fft=2048,
        stft_hop_length=441,
        stft_win_length=2048,
        stft_normalized=False,
        mask_estimator_depth=2,
        multi_stft_resolution_loss_weight=1.0,
        multi_stft_resolutions_window_sizes=(4096, 2048, 1024, 512, 256),
        multi_stft_hop_size=147,
        multi_stft_normalized=False,
    )
    return model.to(torch.device("cpu")).eval()


def _load_checkpoint(model_path: Path) -> MelBandRoformer:
    model = _build_model()
    try:
        checkpoint = torch.load(model_path, map_location="cpu", weights_only=True)
    except TypeError:
        # Torch versions before weights_only support still load only from a
        # server-verified local checkpoint path, never from a user path/URL.
        checkpoint = torch.load(model_path, map_location="cpu")
    if not isinstance(checkpoint, dict):
        raise RuntimeError("The MelBand checkpoint is not a state dictionary.")
    state = checkpoint.get("state_dict", checkpoint)
    if not isinstance(state, dict):
        raise RuntimeError("The MelBand checkpoint state dictionary is invalid.")
    model.load_state_dict(state, strict=True)
    return model


def _write_float_wav(path: Path, audio: np.ndarray) -> None:
    if audio.ndim != 2 or audio.shape[0] != CHANNELS:
        raise ValueError("WAV output must have shape [2, samples].")
    interleaved = np.ascontiguousarray(audio.T.astype("<f4", copy=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = interleaved.tobytes()
    fmt = struct.pack(
        "<4sIHHIIHH",
        b"fmt ",
        16,
        3,  # WAVE_FORMAT_IEEE_FLOAT / pcm_f32le
        CHANNELS,
        SAMPLE_RATE,
        SAMPLE_RATE * CHANNELS * 4,
        CHANNELS * 4,
        32,
    )
    data = struct.pack("<4sI", b"data", len(payload)) + payload
    riff_size = 4 + len(fmt) + len(data)
    with path.open("wb") as output:
        output.write(struct.pack("<4sI4s", b"RIFF", riff_size, b"WAVE"))
        output.write(fmt)
        output.write(data)


def run_worker(model_path: Path, input_path: Path, output_dir: Path, model_id: str) -> None:
    validate_pinned_runtime()
    if model_id != MELBAND_ROFORMER_MODEL:
        raise RuntimeError("Unsupported MelBand model ID.")
    if not model_path.is_file():
        raise RuntimeError("The verified MelBand model file is missing.")
    normalized_mix = load_raw_audio(input_path)
    model = _load_checkpoint(model_path)

    def emit(completed: int, total: int) -> None:
        print(
            "KARAOKE_PROGRESS "
            + json.dumps({"completed": completed, "total": total}),
            flush=True,
        )

    # Establish the inference clock before the first completed chunk.
    sample_count = normalized_mix.shape[1]
    total_chunks = max(1, (sample_count + STEP_SIZE - 1) // STEP_SIZE)
    emit(0, total_chunks)
    vocals, instrumental = separate_chunks(model, normalized_mix, emit)
    _write_float_wav(output_dir / "vocals.wav", vocals)
    _write_float_wav(output_dir / "instrumental.wav", instrumental)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Karaoke Box MelBand RoFormer worker")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--input", dest="input_path", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--model-id", default=MELBAND_ROFORMER_MODEL)
    options = parser.parse_args(arguments)
    try:
        validate_pinned_runtime()
        if options.probe:
            print("KARAOKE_SEPARATOR_PROBE ok", flush=True)
            return 0
        if not options.model_path or not options.input_path or not options.output_dir:
            parser.error("--model-path, --input, and --output-dir are required")
        run_worker(options.model_path, options.input_path, options.output_dir, options.model_id)
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"MelBand worker failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
