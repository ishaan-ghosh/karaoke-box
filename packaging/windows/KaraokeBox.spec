from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

repo_root = Path(SPECPATH).resolve().parents[1]
frontend = repo_root / "web" / "dist"
if not frontend.is_dir():
    raise SystemExit("web/dist is missing; build the Vite frontend first")

datas = [(str(frontend), "web/dist")]
binaries = []
hiddenimports = []

for package in ("demucs", "julius", "sphn", "webview"):
    hiddenimports += collect_submodules(package)
    datas += collect_data_files(package)

for package in ("demucs", "pywebview", "platformdirs"):
    try:
        datas += copy_metadata(package)
    except Exception:
        pass

tool_dir = os.environ.get("KARAOKE_BUILD_TOOLS_DIR")
if tool_dir:
    tool_root = Path(tool_dir)
    for filename in ("ffmpeg.exe", "ffprobe.exe"):
        tool = tool_root / filename
        if not tool.is_file():
            raise SystemExit(f"Missing bundled tool: {tool}")
        binaries.append((str(tool), "tools"))

analysis = Analysis(
    [str(repo_root / "backend" / "desktop_entry.py")],
    pathex=[str(repo_root / "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["_pytest", "matplotlib", "notebook", "pytest", "tensorboard", "tkinter"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="KaraokeBox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="KaraokeBox",
)
