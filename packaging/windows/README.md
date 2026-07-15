# Windows packaging

The desktop artifact is built on Windows because PyInstaller does not cross-compile from macOS.

Run the **Windows desktop build** workflow manually in GitHub Actions. It produces:

- an unpacked PyInstaller onedir application,
- an Inno Setup per-user installer.

The workflow explicitly reinstalls the CPU-only PyTorch wheel and bundles `ffmpeg.exe`/`ffprobe.exe`. No CUDA runtime is included, and the application always forces CPU execution for Demucs and the optional experimental MelBand worker. The roughly 871 MiB MelBand checkpoint is downloaded only on first use into `KARAOKE_MODEL_DIR` and is never bundled. The pushed checkpoint `1c5bfb2db59868ec20bff02be0ba41c323041afc` and run `29303479616` validate Phase 1C only; they predate the uncommitted Karaoke Video Studio renderer. The current working-tree spec additionally describes Pillow/PyYAML and bundled OFL font assets, but this karaoke package has not been built or smoke-tested on Windows and must not be described as validated. The next Windows package should move its Python runtime from 3.10 to 3.11 to remove yt-dlp's nonfatal deprecation output.

For a manual Windows build from the repository root:

```powershell
npm ci --prefix web
uv sync --project backend --extra desktop
npm test
uv sync --project backend --extra desktop
# No-weight/no-network separator probe (also included in desktop smoke)
Push-Location backend
uv run --project backend python -u -m app.separators.worker --probe
Pop-Location
uv pip install --python backend/.venv/Scripts/python.exe --reinstall --no-deps --index-url https://download.pytorch.org/whl/cpu torch==2.2.2
choco install ffmpeg innosetup -y
mkdir packaging\windows\build-tools
$ffmpeg = Get-ChildItem "$env:ChocolateyInstall\lib" -Filter ffmpeg.exe -Recurse | Select-Object -First 1
$ffprobe = Get-ChildItem "$env:ChocolateyInstall\lib" -Filter ffprobe.exe -Recurse | Select-Object -First 1
copy $ffmpeg.FullName packaging\windows\build-tools\ffmpeg.exe
copy $ffprobe.FullName packaging\windows\build-tools\ffprobe.exe
Invoke-WebRequest "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile packaging\windows\build-tools\MicrosoftEdgeWebView2Setup.exe
$env:KARAOKE_BUILD_TOOLS_DIR = "$PWD\packaging\windows\build-tools"
uv run --project backend --no-sync pyinstaller --noconfirm --clean packaging/windows/KaraokeBox.spec
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" packaging/windows/KaraokeBox.iss
```

The packaged smoke test exercises startup/session/health and the no-weight/no-network separator probe; it does not download the MelBand checkpoint or run full inference. Workflow run [29303479616](https://github.com/ishaan-ghosh/karaoke-box/actions/runs/29303479616) succeeded at commit `1c5bfb2db59868ec20bff02be0ba41c323041afc` for the Phase 1C package: 61 backend tests plus frontend checks, CPU-only Torch reinstall, PyInstaller onedir build, packaged authenticated startup/health and no-weight/no-network internal separator probe, Inno Setup installer, and artifact upload all passed. That historical artifact is not validation of the current uncommitted Karaoke Video Studio renderer, fonts, Pillow resources, or libx264 render path. The prior run `29303065151` failed because Windows converted the LF-only pinned reference YAML to CRLF; commit `1c5bfb2` fixed `.gitattributes` and the succeeding run validates that fix.

The user installed the new installer smoothly on the target older Windows laptop and completed one roughly 3-minute user-attested YouTube-to-karaoke-use MelBand conversion (stem separation producing instrumental/vocal audio, not this MP4 renderer) in about 30–40 minutes. Hardware, peak RAM/disk, cached-versus-setup timing, and exact timing were not recorded, so this is compatibility evidence rather than a performance promise or minimum specification. One initial YouTube transfer selected format 251 and failed with HTTP 403 after metadata succeeded; a different YouTube video subsequently worked end to end. Do not claim the 403 is fixed; inspect reproducible `yt-dlp.log` evidence before changing retry/actionable diagnostics. The permanent CPU-only boundary remains; do not add CUDA, MPS, or DirectML despite NVIDIA hardware on the target laptop.

Before production release, verify packaged third-party notices and complete a cached performance check covering the default 10-minute range with target hardware, elapsed time, peak RAM/disk, and an explicit acceptability decision. Broader clean-Windows release-matrix testing and signing remain separate work. The default supported source-duration range is 10 minutes; an operator can intentionally raise it with `KARAOKE_MAX_DURATION_SECONDS` when local policy and hardware permit.

Public releases should be Authenticode-signed before distribution.
