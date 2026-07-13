# Windows Desktop Target

The primary distribution target is a self-contained Windows x64 desktop application. macOS remains a supported development environment, but Windows artifacts must be built and smoke-tested on Windows.

## Recommended stack

```text
Karaoke Box.exe
  |-- pywebview native window (Edge WebView2)
  |-- compiled React/Vite assets
  |-- FastAPI on a random loopback port
  |-- local job worker process
  |-- FFmpeg/ffprobe executables
  |-- Demucs + CPU-only PyTorch
  |-- JSON job metadata
  +-- persistent files in %LOCALAPPDATA%\Karaoke Box\
```

Use pywebview first because Python already owns the expensive audio stack. Tauri would improve native lifecycle/installer integration, but it would still need a packaged Python/PyTorch sidecar and adds Rust/build complexity without reducing the large ML runtime.

## Windows support baseline

Initial target:

- Windows 10/11 x64
- CPU-only processing
- one concurrent separation job
- Edge WebView2 runtime
- local NTFS storage
- no administrator privileges during normal use

The application is permanently CPU-only. It always invokes Demucs with `--device cpu`, hides CUDA devices at runtime, and packages the CPU-only PyTorch wheel. No CUDA distribution is planned.

## Application lifecycle

1. The executable chooses an unused loopback port and generates an in-memory session token.
2. It starts FastAPI in the background, bound only to `127.0.0.1`.
3. It opens a pywebview window pointing at the local application URL.
4. The React application uses the existing HTTP job API and polling.
5. Demucs runs in a separate child process so inference cannot freeze the UI.
6. Closing the window prompts when processing is active. The first version may either cancel/mark interrupted or remain in the system tray.
7. On a clean exit, the API and its child process tree shut down.

The random port and per-launch token prevent unrelated websites or local processes from casually invoking the media API. CORS alone is not sufficient protection for a localhost service.

## Local data layout

Use `platformdirs` rather than repository-relative paths.

```text
%LOCALAPPDATA%\Karaoke Box\
  config\
  models\
  jobs\<job-id>\
    job.json
    source.<extension>
    demucs.log
    instrumental.wav
    vocals.wav
  logs\
```

Per-job JSON stores metadata, progress, and history. Audio remains ordinary files so FFmpeg and Demucs can stream it efficiently.

There is no automatic media expiration in the desktop application. Sources, results, and models remain until the user explicitly deletes an individual job or uses a future **Clear local data** setting. Temporary Demucs working directories are still removed after each successful job. Before accepting a job, the app should verify that sufficient disk space is available.

## Packaging strategy

### Python application

Use PyInstaller in **onedir** mode:

- avoids extracting the large PyTorch runtime on every launch,
- makes DLL and model troubleshooting easier,
- allows the installer to update individual packaged files,
- starts faster than one-file mode.

The packaged launcher needs a special worker entry point. In a frozen app, `sys.executable -m demucs` does not work because `sys.executable` points to `Karaoke Box.exe`. The executable should support an internal command such as:

```text
Karaoke Box.exe --internal-demucs <demucs arguments>
```

Development continues to use `python -m demucs`; the processor chooses the command through a runtime adapter.

### Frontend

Run `npm ci` and `npm run build`, then include `web/dist` as PyInstaller application resources. FastAPI serves those assets to pywebview. Vite and Node are build-time dependencies only and are not installed on the user's machine.

### FFmpeg

Bundle Windows x64 `ffmpeg.exe` and `ffprobe.exe` in the application directory and resolve them through a tool-path adapter rather than relying on system `PATH`. Record and comply with the license/configuration of the selected FFmpeg distribution.

### Installer

Use Inno Setup to create a per-user installer:

- installs under the user's local application directory,
- creates Start Menu/Desktop shortcuts,
- installs or bootstraps WebView2 when missing,
- registers an uninstaller,
- does not delete user results/models during ordinary upgrades.

Public distribution eventually needs Authenticode code signing. Unsigned PyInstaller applications can trigger Windows SmartScreen or antivirus false positives.

## Model handling

Do not embed every model in the initial installer.

- Include enough metadata to show model size and availability.
- Download the selected Demucs weights on first use with visible progress.
- Store weights under the application model directory by setting `TORCH_HOME`/related cache configuration.
- Verify expected file checksum after download.
- Offer a settings action to remove cached models.
- Optionally bundle the default model later if offline installation is required.

The Best Quality profile uses multiple model weights and significantly increases both download size and CPU runtime.

## Windows build pipeline

Windows artifacts cannot be produced reliably from macOS. Add a GitHub Actions workflow using `windows-latest`:

1. Check out the repository.
2. Install the pinned Node and Python versions.
3. Install frontend dependencies and build Vite.
4. Install Python dependencies from the lock file.
5. Run backend tests, frontend lint, and frontend build.
6. Build the PyInstaller onedir application from a checked-in `.spec` file.
7. Run a packaged health/startup smoke test.
8. Build the Inno Setup installer.
9. Upload both the unpacked application and installer as workflow artifacts.

A Windows machine should then test:

- clean install and uninstall,
- startup without developer tools or Python installed,
- WebView2 detection,
- MP3/WAV/FLAC input,
- paths containing spaces and non-ASCII characters,
- progress and ETA,
- window close during processing,
- sleep/wake behavior,
- explicit job deletion and locked-file error handling,
- Windows Defender/SmartScreen behavior,
- CPU usage, peak RAM, scratch disk, and runtime for each quality profile.

## Migration from the current app

1. Serve `web/dist` from FastAPI in production/desktop mode.
2. Add a desktop launcher that owns FastAPI and pywebview lifecycle.
3. Keep JSON metadata behind a repository interface so storage can change later.
4. Move data/model paths behind a `platformdirs` configuration.
5. Add the frozen-runtime Demucs command adapter and bundled FFmpeg resolver.
6. Add disk-space admission checks and an explicit clear-data setting.
7. Add session-token protection for the loopback API.
8. Create the PyInstaller spec and GitHub Actions Windows build.
9. Create the Inno Setup installer and test it on clean Windows.

## Optional hosted future

The desktop architecture does not prevent a hosted version later. Keep job, storage, and worker interfaces separate so JSON/local files can eventually be replaced with PostgreSQL/object storage/remote workers. The Cloudflare/VPS plan remains documented separately but is not required for the Windows application.
