# Windows packaging

The desktop artifact is built on Windows because PyInstaller does not cross-compile from macOS.

Run the **Windows desktop build** workflow manually in GitHub Actions. It produces:

- an unpacked PyInstaller onedir application,
- an Inno Setup per-user installer.

The workflow explicitly reinstalls the CPU-only PyTorch wheel and bundles `ffmpeg.exe`/`ffprobe.exe`. No CUDA runtime is included, and the application always passes `--device cpu` to Demucs.

For a manual Windows build from the repository root:

```powershell
npm ci --prefix web
uv sync --project backend --extra desktop
npm test
uv sync --project backend --extra desktop
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

Public releases should be Authenticode-signed before distribution.
