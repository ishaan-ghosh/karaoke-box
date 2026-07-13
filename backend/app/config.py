from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("KARAOKE_DATA_DIR", REPO_ROOT / "data")).resolve()
JOBS_DIR = DATA_DIR / "jobs"

MAX_UPLOAD_BYTES = int(os.environ.get("KARAOKE_MAX_UPLOAD_BYTES", 250 * 1024 * 1024))
MAX_DURATION_SECONDS = float(os.environ.get("KARAOKE_MAX_DURATION_SECONDS", 20 * 60))
DEMUCS_MODEL = os.environ.get("KARAOKE_DEMUCS_MODEL", "htdemucs")
DEMUCS_BEST_MODEL = os.environ.get("KARAOKE_DEMUCS_BEST_MODEL", "htdemucs_ft")

ALLOWED_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}
