"""Pinned, atomic model download and verification for separator engines."""

from __future__ import annotations

import hashlib
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config import MODELS_DIR
from .base import ProcessingError
from .catalog import MELBAND_ROFORMER_MODEL

MODEL_REVISION = "ac9b0614ab3cd7f77219e18ba494dfd93956c348"
MODEL_DOWNLOAD_URL = (
    "https://huggingface.co/KimberleyJSN/melbandroformer/resolve/"
    f"{MODEL_REVISION}/MelBandRoformer.ckpt?download=true"
)
MODEL_EXPECTED_SIZE = 913106900
MODEL_SHA256 = "87201f4d31afb5bc79993230fc49446918425574db48c01c405e44f365c7559e"
# Compatibility names for callers that prefer descriptive manifest constants.
MODEL_URL = MODEL_DOWNLOAD_URL
EXPECTED_MODEL_BYTES = MODEL_EXPECTED_SIZE
MODEL_CHECKSUM = MODEL_SHA256
MODEL_RELATIVE_PATH = Path(
    "melband-roformer"
) / MELBAND_ROFORMER_MODEL / "MelBandRoformer.ckpt"

ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class ModelManifest:
    model_id: str
    download_url: str
    expected_size: int
    sha256: str
    relative_path: Path = MODEL_RELATIVE_PATH

    @property
    def url(self) -> str:
        return self.download_url

    @property
    def expected_bytes(self) -> int:
        return self.expected_size

    @property
    def checksum(self) -> str:
        return self.sha256


MELBAND_MODEL_MANIFEST = ModelManifest(
    model_id=MELBAND_ROFORMER_MODEL,
    download_url=MODEL_DOWNLOAD_URL,
    expected_size=MODEL_EXPECTED_SIZE,
    sha256=MODEL_SHA256,
)

# Friendly aliases for callers and focused tests.
MELBAND_MANIFEST = MELBAND_MODEL_MANIFEST


def model_path(
    models_dir: Path = MODELS_DIR,
    manifest: ModelManifest = MELBAND_MODEL_MANIFEST,
) -> Path:
    return Path(models_dir) / manifest.relative_path


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def verify_model(path: Path, manifest: ModelManifest = MELBAND_MODEL_MANIFEST) -> bool:
    """Stream-verify a cached model before every use.

    A completed read returns ``False`` for a confirmed size/hash mismatch. An
    unreadable file is different: callers must retain it and surface a
    sanitized I/O error rather than treating a transient failure as corruption.
    """

    try:
        size, digest = _sha256_file(path)
    except OSError as exc:
        raise ProcessingError("The cached separator model could not be verified.") from exc
    return size == manifest.expected_size and digest == manifest.sha256


def _emit_progress(
    callback: ProgressCallback | None,
    downloaded: int,
    total: int,
    state: dict[str, float | int],
    *,
    force: bool = False,
) -> None:
    if callback is None:
        return
    now = time.monotonic()
    if not force:
        if now - float(state.get("at", 0.0)) < 0.4 and downloaded != 0:
            return
        if downloaded == int(state.get("downloaded", -1)):
            return
    state["at"] = now
    state["downloaded"] = downloaded
    callback(downloaded, total)


def download_model(
    manifest: ModelManifest = MELBAND_MODEL_MANIFEST,
    *,
    models_dir: Path = MODELS_DIR,
    progress: ProgressCallback | None = None,
    progress_callback: ProgressCallback | None = None,
    opener: Callable[..., object] | None = None,
    chunk_size: int = 1024 * 1024,
) -> Path:
    """Download and atomically install one immutable checkpoint.

    ``opener`` is injectable for routine tests; production uses standard-library
    urllib only. No URL or response body detail is included in user-facing errors.
    """

    if progress is None:
        progress = progress_callback
    final_path = model_path(models_dir, manifest)
    partial_path = final_path.with_name(final_path.name + ".part")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    state: dict[str, float | int] = {}

    if final_path.is_file():
        if verify_model(final_path, manifest):
            # Verification is deliberately silent for progress callbacks. The
            # adapter can keep its "Verifying" message for a cache hit.
            return final_path
        try:
            final_path.unlink()
        except OSError as exc:
            raise ProcessingError("The cached separator model is invalid and could not be replaced.") from exc

    partial_path.unlink(missing_ok=True)
    open_url = opener or urllib.request.urlopen
    # A zero event marks a real download. Valid-cache reuse above emits no
    # progress event, allowing callers to keep their verification message.
    _emit_progress(progress, 0, manifest.expected_size, state, force=True)
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with open_url(manifest.download_url, timeout=60) as response:  # type: ignore[arg-type]
            with partial_path.open("wb") as destination:
                while chunk := response.read(chunk_size):  # type: ignore[union-attr]
                    downloaded += len(chunk)
                    if downloaded > manifest.expected_size:
                        raise ProcessingError("The separator model download exceeded its expected size.")
                    destination.write(chunk)
                    digest.update(chunk)
                    _emit_progress(progress, downloaded, manifest.expected_size, state)
                destination.flush()
                os.fsync(destination.fileno())

        if downloaded != manifest.expected_size:
            raise ProcessingError("The separator model download has an unexpected size.")
        if digest.hexdigest() != manifest.sha256:
            raise ProcessingError("The separator model checksum did not match the pinned value.")
        _emit_progress(progress, downloaded, manifest.expected_size, state, force=True)
        os.replace(partial_path, final_path)
        return final_path
    except ProcessingError:
        partial_path.unlink(missing_ok=True)
        raise
    except (OSError, urllib.error.URLError, ValueError) as exc:
        partial_path.unlink(missing_ok=True)
        raise ProcessingError("The separator model could not be downloaded or verified.") from exc
    except Exception as exc:
        partial_path.unlink(missing_ok=True)
        raise ProcessingError("The separator model could not be downloaded or verified.") from exc


def ensure_model(
    manifest: ModelManifest = MELBAND_MODEL_MANIFEST,
    *,
    models_dir: Path = MODELS_DIR,
    progress: ProgressCallback | None = None,
    progress_callback: ProgressCallback | None = None,
    opener: Callable[..., object] | None = None,
) -> Path:
    return download_model(
        manifest,
        models_dir=models_dir,
        progress=progress,
        progress_callback=progress_callback,
        opener=opener,
    )


# Explicit names make the cache contract easy to test and package.
verify_checkpoint = verify_model
verify_cached_model = verify_model
checkpoint_path = model_path
get_model_path = model_path


__all__ = [
    "MELBAND_MANIFEST",
    "MELBAND_MODEL_MANIFEST",
    "MODEL_CHECKSUM",
    "MODEL_DOWNLOAD_URL",
    "MODEL_EXPECTED_SIZE",
    "MODEL_URL",
    "EXPECTED_MODEL_BYTES",
    "MODEL_RELATIVE_PATH",
    "MODEL_REVISION",
    "MODEL_SHA256",
    "ModelManifest",
    "checkpoint_path",
    "download_model",
    "get_model_path",
    "ensure_model",
    "model_path",
    "verify_cached_model",
    "verify_checkpoint",
    "verify_model",
]
