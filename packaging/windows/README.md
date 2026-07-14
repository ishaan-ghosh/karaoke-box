# Windows packaging

The desktop artifact is built on Windows because PyInstaller does not cross-compile from macOS.

Run the **Windows desktop build** workflow manually in GitHub Actions. It produces:

- an unpacked PyInstaller onedir application,
- an Inno Setup per-user installer.

The workflow explicitly reinstalls the CPU-only PyTorch wheel and bundles `ffmpeg.exe`/`ffprobe.exe`. No CUDA runtime is included, and the application always forces CPU execution for Demucs and the optional experimental MelBand worker. The roughly 871 MiB MelBand checkpoint is downloaded only on first use into `KARAOKE_MODEL_DIR` and is never bundled.

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

The packaged smoke test exercises startup/session/health and the no-weight/no-network separator probe; it does not download the MelBand checkpoint or run full inference. A successful local build is not Windows validation. Before production release, complete permitted-fixture A/B listening, 3/10/20-minute CPU and peak-RAM measurements, frozen Windows x64 worker/package validation, a real permitted song on the target Windows PC, and packaged third-party-notice verification.

Public releases should be Authenticode-signed before distribution.
