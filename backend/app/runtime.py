from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return Path(__file__).resolve().parents[2]


def web_dist_dir() -> Path:
    return resource_root() / "web" / "dist"


def resolve_tool(name: str) -> str | None:
    env_name = f"KARAOKE_{name.upper()}_PATH"
    if configured := os.environ.get(env_name):
        path = Path(configured).expanduser().resolve()
        return str(path) if path.is_file() else None

    executable_name = f"{name}.exe" if sys.platform == "win32" else name
    bundled = resource_root() / "tools" / executable_name
    if bundled.is_file():
        return str(bundled)
    return shutil.which(name)


def demucs_command() -> list[str]:
    # A frozen executable cannot use `sys.executable -m demucs` because
    # sys.executable points back to KaraokeBox.exe. Re-enter the launcher with
    # a private command that dispatches to demucs.separate.main instead.
    if is_frozen():
        return [sys.executable, "--internal-demucs"]
    return [sys.executable, "-u", "-m", "demucs"]


def ytdlp_command() -> list[str]:
    # Keep YouTube ingest on the same frozen-runtime adapter as Demucs. The
    # packaged executable dispatches this private command to yt-dlp's Python
    # entry point instead of trying to execute `KaraokeBox.exe -m yt_dlp`.
    if is_frozen():
        return [sys.executable, "--internal-ytdlp"]
    return [sys.executable, "-u", "-m", "yt_dlp"]
