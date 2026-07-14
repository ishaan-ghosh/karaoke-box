# Windows Desktop Target

The primary distribution target is a self-contained Windows x64 desktop application. macOS remains a supported development environment, but Windows artifacts must be built and smoke-tested on Windows.

## Recommended stack

```text
Karaoke Box.exe
  |-- pywebview native window (Edge WebView2)
  |-- compiled React/Vite assets
  |-- FastAPI on a random loopback port
  |-- local job worker process
  |-- pinned yt-dlp YouTube ingest
  |-- FFmpeg/ffprobe executables
  |-- Demucs default + optional experimental MelBand RoFormer + CPU-only PyTorch
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
5. The selected separator runs in a separate child process so inference cannot freeze the UI. In development, the MelBand child keeps `python -u -m app.separators.worker` and runs with the repository's `backend` directory as cwd; this is required because Uvicorn's `--app-dir backend` import path does not propagate to child interpreters.
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
    melband-roformer.log
    yt-dlp.log
    instrumental.wav
    vocals.wav
  logs\
```

Per-job JSON stores metadata, progress, and history. Audio remains ordinary files so FFmpeg and the selected separator can stream it efficiently.

There is no automatic media expiration in the desktop application. Sources, results, and models remain until the user explicitly deletes an individual job or uses a future **Clear local data** setting. Temporary separator working directories are still removed after each successful job. Before accepting a job, the app should verify that sufficient disk space is available.

## Packaging strategy

### Python application

Use PyInstaller in **onedir** mode:

- avoids extracting the large PyTorch runtime on every launch,
- makes DLL and model troubleshooting easier,
- allows the installer to update individual packaged files,
- starts faster than one-file mode.

The packaged launcher needs special worker entry points. In a frozen app, `sys.executable -m demucs` and `sys.executable -m yt_dlp` do not work because `sys.executable` points to `Karaoke Box.exe`. The executable supports private commands such as:

```text
Karaoke Box.exe --internal-demucs <demucs arguments>
Karaoke Box.exe --internal-ytdlp <yt-dlp arguments>
Karaoke Box.exe --internal-separator <separator-worker arguments>
```

Development continues to use Python module commands. The MelBand adapter keeps `python -u -m app.separators.worker` and supplies `<repo>/backend` as cwd so the child can import `app` under the documented repository-root Uvicorn launch. Frozen mode uses the private separator command above. The generic separator entry point is reserved for the narrow CPU-only MelBand worker; existing Demucs and yt-dlp dispatch paths remain unchanged.

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

- Include enough metadata to show engine/model name, size, availability, and expected CPU cost.
- Download selected separator weights on first use with visible progress.
- Store weights under the application model directory (`KARAOKE_MODEL_DIR`), using engine-specific cache subdirectories.
- Verify expected byte size and full SHA-256 before atomic installation.
- Retain valid cached models until explicit deletion.
- Offer a settings action to remove cached models in a later batch.
- The Phase 1C checkpoint is never bundled; the packaged artifact includes only the pinned YAML, provenance, and MIT notice.
- The no-weight/no-network separator probe runs during desktop smoke and does not download or infer.
- Optionally bundle a default model later only if offline installation becomes a requirement.

Phase 1C implements the explicitly MIT-licensed Kimberley Jensen MelBand RoFormer checkpoint as an optional experimental engine. Store it at:

```text
%LOCALAPPDATA%\Karaoke Box\models\melband-roformer\kimberley_melband_roformer_v1\MelBandRoformer.ckpt
```

The expected file is 913106900 bytes with SHA-256 `87201f4d31afb5bc79993230fc49446918425574db48c01c405e44f365c7559e`. The installer must not contain the checkpoint. Do not add the broad `audio-separator` package; use only the narrow pinned MIT runtime described in `docs/SEPARATOR_UPGRADE.md`, because the package adds unnecessary dependencies including CC BY-NC code.

Demucs remains the default faster/current engine and all existing profile semantics remain unchanged. Do not add CUDA, MPS, or DirectML. Current Best Quality already uses multiple Demucs weights and significantly increases download size and CPU runtime.

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

A Windows machine must still test the implementation before release:

- clean install and uninstall,
- startup without developer tools or Python installed,
- WebView2 detection,
- MP3/WAV/FLAC input and an individual YouTube URL,
- paths containing spaces and non-ASCII characters,
- progress and ETA,
- window close during processing,
- sleep/wake behavior,
- explicit job deletion and locked-file error handling,
- Windows Defender/SmartScreen behavior,
- CPU usage, peak RAM, scratch disk, and runtime for each separator engine/profile.

MelBand remains experimental and is not production-ready. Release gates are permitted-fixture A/B listening; 3-, 10-, and 20-minute CPU-time and peak-RAM measurements; frozen Windows x64 worker/package validation; a real permitted song on the target Windows PC; and verification that packaged third-party notices are present.

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
10. Phase 1C implements the frozen generic separator worker/probe and optional verified MelBand model cache without bundling its weights; frozen Windows validation remains pending.

## Optional hosted future

The desktop architecture does not prevent a hosted version later. Keep job, storage, and worker interfaces separate so JSON/local files can eventually be replaced with PostgreSQL/object storage/remote workers. The Cloudflare/VPS plan remains documented separately but is not required for the Windows application.
