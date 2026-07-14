from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("KARAOKE_DATA_DIR", REPO_ROOT / "data")).resolve()
JOBS_DIR = DATA_DIR / "jobs"
MODELS_DIR = Path(os.environ.get("KARAOKE_MODEL_DIR", DATA_DIR / "models")).resolve()

MAX_UPLOAD_BYTES = int(os.environ.get("KARAOKE_MAX_UPLOAD_BYTES", 250 * 1024 * 1024))
MAX_DURATION_SECONDS = float(os.environ.get("KARAOKE_MAX_DURATION_SECONDS", 10 * 60))
YOUTUBE_METADATA_TIMEOUT_SECONDS = float(
    os.environ.get("KARAOKE_YOUTUBE_METADATA_TIMEOUT_SECONDS", 60)
)
YOUTUBE_DOWNLOAD_TIMEOUT_SECONDS = float(
    os.environ.get("KARAOKE_YOUTUBE_DOWNLOAD_TIMEOUT_SECONDS", 15 * 60)
)
YOUTUBE_SOCKET_TIMEOUT_SECONDS = float(
    os.environ.get("KARAOKE_YOUTUBE_SOCKET_TIMEOUT_SECONDS", 30)
)
DEMUCS_MODEL = os.environ.get("KARAOKE_DEMUCS_MODEL", "htdemucs")
DEMUCS_BEST_MODEL = os.environ.get("KARAOKE_DEMUCS_BEST_MODEL", "htdemucs_ft")
SESSION_TOKEN = os.environ.get("KARAOKE_SESSION_TOKEN")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "KARAOKE_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

ALLOWED_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}
