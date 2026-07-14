from __future__ import annotations

import hashlib
import struct
from pathlib import Path

import pytest
import torch

from app.runtime import separator_worker_command, separator_worker_cwd
from app.separators.base import ProcessingError
from app.separators.model_cache import ModelManifest, download_model, model_path, verify_model


class _Response:
    def __init__(self, chunks: list[bytes]):
        self.chunks = iter(chunks)

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        return next(self.chunks, b"")


def _manifest(payload: bytes) -> ModelManifest:
    return ModelManifest(
        model_id="fake-model",
        download_url="https://example.invalid/fake.ckpt",
        expected_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        relative_path=Path("fake") / "model.ckpt",
    )


def test_model_cache_downloads_atomically_and_reuses_verified_file(tmp_path: Path) -> None:
    payload = b"small fake checkpoint"
    manifest = _manifest(payload)
    calls = 0

    def opener(*args: object, **kwargs: object) -> _Response:
        nonlocal calls
        calls += 1
        return _Response([payload[:4], payload[4:]])

    progress: list[tuple[int, int]] = []
    path = download_model(
        manifest,
        models_dir=tmp_path,
        opener=opener,
        progress=lambda downloaded, total: progress.append((downloaded, total)),
    )
    assert path.read_bytes() == payload
    assert not path.with_name(path.name + ".part").exists()
    assert verify_model(path, manifest)
    assert progress[0] == (0, len(payload))
    assert progress[-1] == (len(payload), len(payload))

    reused_progress: list[tuple[int, int]] = []
    assert download_model(
        manifest,
        models_dir=tmp_path,
        opener=opener,
        progress=lambda downloaded, total: reused_progress.append((downloaded, total)),
    ) == path
    assert calls == 1
    assert reused_progress == []


def test_model_cache_throttles_intermediate_progress_but_keeps_initial_and_final(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import app.separators.model_cache as cache

    payload = b"12345678"
    manifest = _manifest(payload)
    ticks = iter((0.0, 0.1, 0.2, 0.3))
    monkeypatch.setattr(cache.time, "monotonic", lambda: next(ticks))
    events: list[tuple[int, int]] = []
    download_model(
        manifest,
        models_dir=tmp_path,
        opener=lambda *args, **kwargs: _Response([payload[:4], payload[4:]]),
        progress=lambda downloaded, total: events.append((downloaded, total)),
    )
    assert events == [(0, len(payload)), (len(payload), len(payload))]


@pytest.mark.parametrize(
    ("bad_payload", "message"),
    [(b"wrong", "unexpected size"), (b"xpected!", "checksum")],
)
def test_model_cache_removes_wrong_cached_file_and_rejects_bad_download(
    tmp_path: Path, bad_payload: bytes, message: str
) -> None:
    payload = b"expected"
    manifest = _manifest(payload)
    path = model_path(tmp_path, manifest)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"wrong")

    def opener(*args: object, **kwargs: object) -> _Response:
        return _Response([bad_payload])

    with pytest.raises(Exception, match=message):
        download_model(manifest, models_dir=tmp_path, opener=opener)
    assert not path.exists()
    assert not path.with_name(path.name + ".part").exists()


def test_model_cache_cleans_partial_download_on_interruption(tmp_path: Path) -> None:
    payload = b"expected payload"
    manifest = _manifest(payload)

    class InterruptedResponse(_Response):
        def read(self, size: int) -> bytes:
            raise OSError("connection interrupted")

    def opener(*args: object, **kwargs: object) -> InterruptedResponse:
        return InterruptedResponse([])

    with pytest.raises(Exception, match="could not be downloaded"):
        download_model(manifest, models_dir=tmp_path, opener=opener)
    assert not model_path(tmp_path, manifest).with_name("model.ckpt.part").exists()


def test_model_cache_preserves_final_file_when_verification_has_io_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import app.separators.model_cache as cache

    payload = b"verified cached model"
    manifest = _manifest(payload)
    path = model_path(tmp_path, manifest)
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)

    def unreadable(path: Path) -> tuple[int, str]:
        raise OSError("temporary read failure")

    monkeypatch.setattr(cache, "_sha256_file", unreadable)

    def unexpected_opener(*args: object, **kwargs: object) -> object:
        raise AssertionError("verification I/O failure must not trigger a download")

    with pytest.raises(ProcessingError, match="could not be verified"):
        cache.download_model(manifest, models_dir=tmp_path, opener=unexpected_opener)
    assert path.read_bytes() == payload
    assert not path.with_name(path.name + ".part").exists()


def test_vendored_attention_is_cpu_only_without_gpu_hardware() -> None:
    from app.separators.vendor.attend import Attend

    query = torch.randn(1, 1, 2, 4)
    output = Attend(flash=False)(query, query, query)
    assert output.device.type == "cpu"

    non_cpu = torch.empty((1, 1, 2, 4), device="meta")
    with pytest.raises(RuntimeError, match="CPU-only"):
        Attend()(non_cpu, non_cpu, non_cpu)


def test_worker_writes_stereo_44100_float32_wav_header(tmp_path: Path) -> None:
    _, _, _, _ = _optional_melband_modules()
    import numpy as np
    from app.separators.worker import _write_float_wav

    path = tmp_path / "stereo.wav"
    _write_float_wav(path, np.zeros((2, 8), dtype=np.float32))
    payload = path.read_bytes()
    assert payload[:4] == b"RIFF"
    assert payload[8:12] == b"WAVE"
    chunk_id, chunk_size, audio_format, channels, sample_rate, byte_rate, block_align, bits = struct.unpack_from(
        "<4sIHHIIHH", payload, 12
    )
    assert chunk_id == b"fmt "
    assert chunk_size == 16
    assert audio_format == 3
    assert channels == 2
    assert sample_rate == 44100
    assert byte_rate == 44100 * 2 * 4
    assert block_align == 2 * 4
    assert bits == 32
    data_id, data_size = struct.unpack_from("<4sI", payload, 36)
    assert data_id == b"data"
    assert data_size == 8 * 2 * 4


def test_separator_worker_command_uses_development_python(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.runtime as runtime

    monkeypatch.setattr(runtime, "is_frozen", lambda: False)
    command = separator_worker_command()
    assert command[1:] == ["-u", "-m", "app.separators.worker"]


def test_separator_worker_command_uses_frozen_private_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.runtime as runtime

    monkeypatch.setattr(runtime, "is_frozen", lambda: True)
    command = separator_worker_command()
    assert command == [runtime.sys.executable, "--internal-separator"]
    assert separator_worker_cwd() is None


def test_separator_worker_cwd_is_backend_import_root(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.runtime as runtime

    monkeypatch.setattr(runtime, "is_frozen", lambda: False)
    assert separator_worker_cwd() == Path(__file__).resolve().parents[1]


def _optional_melband_modules():
    pytest.importorskip("beartype")
    pytest.importorskip("rotary_embedding_torch")
    from app.separators import melband
    from app.separators.worker import CHUNK_SIZE, STEP_SIZE, separate_chunks

    return melband, CHUNK_SIZE, STEP_SIZE, separate_chunks


def test_melband_progress_parser_and_short_array_residual() -> None:
    melband, _, _, separate_chunks = _optional_melband_modules()

    tracker = melband.MelBandProgressTracker()
    assert tracker.feed("KARAOKE_PROGRESS {\"completed\": 0, \"total\": 2}", now=10)
    progress = tracker.feed("KARAOKE_PROGRESS {\"completed\": 1, \"total\": 2}", now=12)
    assert progress is not None and progress.fraction == 0.5 and progress.eta_seconds == 2

    class FakeModel:
        def __call__(self, batch):
            # Return the first channel as a stereo predicted vocal tensor.
            return batch * 0.25

    import numpy as np

    mix = np.ones((2, 100), dtype=np.float32) * 0.8
    vocals, instrumental = separate_chunks(FakeModel(), mix)
    assert vocals.shape == mix.shape
    assert instrumental.shape == mix.shape
    assert np.allclose(vocals, 0.2, atol=1e-5)
    assert np.allclose(instrumental, 0.6, atol=1e-5)


def test_fake_model_uses_multiple_chunks_and_final_padding() -> None:
    _, chunk_size, step_size, separate_chunks = _optional_melband_modules()
    import numpy as np

    shapes: list[tuple[int, ...]] = []

    class FakeModel:
        def __call__(self, batch):
            shapes.append(tuple(batch.shape))
            return batch * 0.25

    mix = np.ones((2, step_size + 100), dtype=np.float32) * 0.8
    progress: list[tuple[int, int]] = []
    vocals, instrumental = separate_chunks(
        FakeModel(), mix, lambda completed, total: progress.append((completed, total))
    )
    assert shapes == [(1, 2, chunk_size), (1, 2, chunk_size)]
    assert progress == [(1, 2), (2, 2)]
    assert np.allclose(vocals, 0.2, atol=1e-5)
    assert np.allclose(instrumental, 0.6, atol=1e-5)


def test_melband_adapter_streams_popen_and_maps_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    melband, _, _, _ = _optional_melband_modules()
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    fake_model = tmp_path / "MelBandRoformer.ckpt"
    fake_model.write_bytes(b"verified-placeholder")
    updates: list[dict[str, object]] = []
    run_commands: list[list[str]] = []
    popen_commands: list[list[str]] = []
    popen_kwargs: list[dict[str, object]] = []

    monkeypatch.setattr(melband, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(melband, "ensure_model", lambda *args, **kwargs: fake_model)
    monkeypatch.setattr(melband, "resolve_tool", lambda name: "/tools/ffmpeg")

    def fake_run(command, **kwargs):
        run_commands.append(command)
        input_path = Path(command[-1])
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_bytes(b"\x00" * 16)
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    class FakeProcess:
        stdout = iter(
            [
                "worker diagnostic\n",
                'KARAOKE_PROGRESS {"completed": 0, "total": 2}\n',
                'KARAOKE_PROGRESS {"completed": 1, "total": 2}\n',
                'KARAOKE_PROGRESS {"completed": 2, "total": 2}\n',
            ]
        )

        def wait(self) -> int:
            return 0

    def fake_popen(command, **kwargs):
        popen_commands.append(command)
        popen_kwargs.append(kwargs)
        output_dir = Path(command[command.index("--output-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "instrumental.wav").write_bytes(b"instrumental")
        (output_dir / "vocals.wav").write_bytes(b"vocals")
        return FakeProcess()

    monkeypatch.setattr(melband.subprocess, "run", fake_run)
    monkeypatch.setattr(melband.subprocess, "Popen", fake_popen)
    adapter = melband.MelBandAdapter()
    adapter.prepare(
        job_dir=tmp_path,
        source=source,
        update=lambda **changes: updates.append(changes),
        quality="preserve",
        model="kimberley_melband_roformer_v1",
    )
    stems = adapter.separate(
        job_dir=tmp_path,
        source=source,
        update=lambda **changes: updates.append(changes),
        quality="preserve",
        model="kimberley_melband_roformer_v1",
    )

    assert len(run_commands) == 1
    assert len(popen_commands) == 1
    command = popen_commands[0]
    assert command[0:4] == [melband.separator_worker_command()[0], "-u", "-m", "app.separators.worker"]
    assert command[command.index("--model-path") + 1] == str(fake_model)
    assert command[command.index("--model-id") + 1] == "kimberley_melband_roformer_v1"
    assert popen_kwargs[0]["cwd"] == separator_worker_cwd()
    assert stems.instrumental.read_bytes() == b"instrumental"
    assert stems.vocals.read_bytes() == b"vocals"
    log = (tmp_path / "melband-roformer.log").read_text()
    assert "worker diagnostic" in log and "KARAOKE_PROGRESS" in log
    assert any(update.get("status") == "preparing" for update in updates)
    assert any(update.get("status") == "separating" and update.get("progress") == 100 for update in updates)
    assert not any(update.get("message", "").startswith("Downloading") for update in updates)


def test_melband_adapter_reports_download_only_for_real_cache_miss(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    melband, _, _, _ = _optional_melband_modules()
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    fake_model = tmp_path / "MelBandRoformer.ckpt"
    fake_model.write_bytes(b"verified-placeholder")
    monkeypatch.setattr(melband, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(melband, "resolve_tool", lambda name: "/tools/ffmpeg")

    def fake_run(command, **kwargs):
        input_path = Path(command[-1])
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_bytes(b"\x00" * 16)
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(melband.subprocess, "run", fake_run)
    updates: list[dict[str, object]] = []

    def download_ensure(*args, **kwargs):
        callback = kwargs["progress"]
        callback(0, 100)
        callback(100, 100)
        return fake_model

    monkeypatch.setattr(melband, "ensure_model", download_ensure)
    melband.MelBandAdapter().prepare(
        job_dir=tmp_path,
        source=source,
        update=lambda **changes: updates.append(changes),
        quality="preserve",
        model="kimberley_melband_roformer_v1",
    )
    messages = [str(update.get("message")) for update in updates]
    assert messages[0] == "Verifying the MelBand RoFormer model"
    assert "Downloading the MelBand RoFormer model" in messages
