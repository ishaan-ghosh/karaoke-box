# Karaoke Box — Agent Handoff Guide

Read this file before changing the repository. Also read `README.md` and the relevant design document (`docs/DESKTOP.md` for the primary product, `docs/PLAN.md` for the roadmap).

## Product purpose and boundaries

Karaoke Box is a single-user desktop application that separates music files into vocal and instrumental stems for karaoke practice and recording.

Hard boundaries:

- The primary product is a local Windows desktop application, not a hosted service.

## Primary target

- **Runtime:** Windows 10/11 x64
- **Development host:** currently macOS Apple Silicon
- **Compute:** CPU only, permanently
- **Distribution:** PyInstaller `onedir` plus Inno Setup installer
- **Window shell:** pywebview using Edge WebView2 on Windows
- **Frontend:** React 19 + TypeScript + Vite
- **Local API:** FastAPI + Uvicorn on a random loopback port
- **Audio:** FFmpeg/ffprobe + Demucs/PyTorch
- **Persistence:** per-job JSON and ordinary local media files
- **Automatic retention:** none; jobs/models remain until explicitly deleted

Do not introduce CUDA. The processor passes `--device cpu`, desktop startup clears `CUDA_VISIBLE_DEVICES`, and Windows CI reinstalls PyTorch from the CPU wheel index.

## Current architecture

### Browser-development mode

```text
Vite 127.0.0.1:5173 -- /api proxy --> FastAPI 127.0.0.1:8000
                                               |
                                               +--> job.json + media under data/jobs
                                               +--> yt-dlp / Demucs subprocess
```

### Desktop mode

```text
pywebview window
      |
random 127.0.0.1 port + per-launch HttpOnly session cookie
      |
FastAPI serves web/dist and /api
      |
JSON job store + yt-dlp/Demucs child process + bundled FFmpeg tools
```

Desktop data is resolved with `platformdirs`:

```text
%LOCALAPPDATA%\Karaoke Box\
  jobs\<job-id>\job.json
  jobs\<job-id>\source.<extension>
  jobs\<job-id>\instrumental.wav
  jobs\<job-id>\vocals.wav
  jobs\<job-id>\demucs.log
  jobs\<job-id>\yt-dlp.log       # YouTube jobs only
  models\
  logs\desktop.log
```

On macOS desktop-development mode, the equivalent platform application-data directory is used.

## Implemented user features

- MP3/WAV/M4A/FLAC/OGG/AAC/Opus upload
- Individual HTTPS YouTube video ingest through pinned `yt-dlp`
- Source-neutral, versioned rights attestation for uploads and URL ingest
- 250 MB and 20-minute defaults
- Three profiles:
  - `preserve`: `htdemucs`, original minus predicted vocals; default
  - `best`: `htdemucs_ft`, subtractive, four model passes; slower
  - `standard`: `htdemucs`, summed instrument stems
- CPU-only processing
- Exact browser upload percentage via XHR
- Live YouTube ingest progress, audio-format fallback, and sanitized `yt-dlp` diagnostics
- Live Demucs progress parsed from tqdm output
- Multi-pass aggregate progress and estimated time remaining
- Synchronized vocal/instrumental preview and level controls
- Instrumental WAV download
- Persistent recent-job history
- Browser reload restoration through local storage plus `GET /api/jobs`
- Explicit job deletion; “Process another track” does not delete prior results
- Desktop window refuses to close while a job is active

## Important implementation details

### Progress

`backend/app/processor.py` streams merged Demucs output through `subprocess.Popen`. `DemucsProgressTracker` parses processed audio-seconds and combines multiple model passes. Do not replace this with `subprocess.run`, which would buffer all progress until completion.

The ETA clock begins at Demucs’s first 0% audio progress line so model download/loading time is not incorrectly treated as recurring inference work.

### Quality profiles

Profiles are defined in `backend/app/profiles.py`. Output filenames differ by method:

- subtractive: `minus_vocals.wav`
- summed stems: `no_vocals.wav`

Keep the output-path mapping aligned with Demucs CLI behavior.

### Desktop session security

`backend/app/desktop.py` generates a random `KARAOKE_SESSION_TOKEN`. `/desktop/start` exchanges the URL token for an HttpOnly, SameSite=Strict cookie. When the token is configured, middleware protects `/api/*`.

Do not expose the desktop API on `0.0.0.0`, use a fixed unauthenticated port, or remove the session check.

### Frozen Demucs execution

A PyInstaller executable cannot run `sys.executable -m demucs` or `sys.executable -m yt_dlp`, because `sys.executable` points back to `KaraokeBox.exe`. `backend/app/runtime.py` therefore returns:

- development: `python -u -m demucs` and `python -u -m yt_dlp`
- frozen build: `KaraokeBox.exe --internal-demucs` and `KaraokeBox.exe --internal-ytdlp`

`backend/desktop_entry.py` dispatches those private commands through `app.desktop`. Preserve these adapters when changing process startup.

### Windowed logging

Windowed PyInstaller has `sys.stdout`/`sys.stderr` set to `None`. Desktop Uvicorn must use `log_config=None`; otherwise Uvicorn calls `stderr.isatty()` and crashes. Desktop phases/errors are written to `KARAOKE_DESKTOP_LOG` or the platform log directory.

### Local storage

There is deliberately no 24/48-hour cleanup. Only temporary Demucs working output is removed after a successful job. Source files, results, history, and model weights persist until explicit deletion.

## Key paths

- `web/src/App.tsx` — current single-page UI, API calls, restoration/history, player
- `web/src/App.css` — application styling
- `web/vite.config.ts` — local `/api` proxy
- `backend/app/main.py` — FastAPI routes, session middleware, static frontend mount
- `backend/app/jobs.py` — JSON job model/store and single-worker manager
- `backend/app/processor.py` — ffprobe, Demucs invocation, progress/ETA, output finalization
- `backend/app/youtube.py` — YouTube URL validation, metadata preflight, controlled `yt-dlp` ingest
- `backend/app/rights.py` — shared source attestation text/version
- `backend/app/profiles.py` — model/method/profile definitions
- `backend/app/runtime.py` — frozen resources, bundled tools, Demucs command adapter
- `backend/app/desktop.py` — desktop environment, API lifecycle, pywebview, smoke test
- `backend/desktop_entry.py` — PyInstaller entry point
- `packaging/windows/KaraokeBox.spec` — PyInstaller onedir definition
- `packaging/windows/KaraokeBox.iss` — Inno Setup installer
- `.github/workflows/windows-desktop.yml` — Windows build/test/package workflow
- `docs/DESKTOP.md` — detailed desktop architecture
- `docs/DEPLOYMENT.md` — optional hosted architecture; not the current target

## Development commands

From the repository root:

```bash
npm run setup          # backend environment + frontend packages
npm run api            # FastAPI dev server
npm run web            # Vite dev server
npm test               # backend tests + frontend lint/build
npm run desktop        # build frontend and open pywebview app
npm run desktop:smoke  # desktop server/session smoke test without a window
```

Before committing, run at minimum:

```bash
npm test
npm run desktop:smoke
```

Do not commit:

- `data/`
- `build/` or `dist/`
- `web/dist/`
- `backend/.venv/` or `web/node_modules/`
- Windows executables/installers or model/audio files

## Windows packaging and CI

The Windows workflow is manually dispatchable and also runs for `v*` tags. It:

1. Installs Node/Python/uv dependencies.
2. Runs tests.
3. Reinstalls CPU-only Torch.
4. Installs and bundles FFmpeg/ffprobe.
5. Downloads the WebView2 bootstrapper.
6. Builds a PyInstaller onedir app.
7. Runs the packaged `--smoke-test` with a 60-second timeout and diagnostics.
8. Builds an Inno Setup installer.
9. Uploads `KaraokeBox-Windows-x64`.

Known-good baseline:

- Commit: `a9bd865`
- Successful run: `29280123857`
- Run URL: `https://github.com/ishaan-ghosh/karaoke-box/actions/runs/29280123857`
- Artifact: `KaraokeBox-Windows-x64` (roughly 374 MB compressed)

The artifact contains both the portable onedir app and installer. The executable is not standalone; the entire `dist/KaraokeBox` directory must remain together.

## Testing status

At the baseline above:

- 27 backend tests pass.
- Frontend lint and production build pass.
- Desktop development smoke test passes.
- Packaged Windows smoke test passes.
- Inno Setup build and artifact upload pass.
- The Windows app has **not yet been manually exercised with a real song on the target Windows PC**. The user wants to add more features before that manual test.

## Known limitations and deferred work

- No full packaged Demucs inference test in CI; CI only verifies packaged startup/session/health.
- Model weights download on first use and are not bundled.
- Installer and executable are unsigned, so SmartScreen may warn.
- No custom application icon yet.
- No “Clear all local data” settings action; jobs can be deleted individually.
- Job metadata remains JSON; this is intentional for current single-user scope.
- The active worker is an in-process single-thread executor that launches a child process.
- Closing the desktop app during processing is blocked rather than supporting tray/background mode.
- Portable and installer outputs are currently combined in one artifact; they could be split later.
- GitHub Actions emits a non-blocking Node runtime deprecation annotation for current action versions.
- Pytest emits a non-blocking Starlette/httpx deprecation warning.
- A macOS PyInstaller build reached final bootloader conversion but was blocked by the development machine’s unaccepted Xcode license; Windows CI is authoritative.

## Git and workflow practices

- Inspect `git status` before editing; do not overwrite user changes.
- Keep changes focused and update tests/docs when behavior changes.
- Run tests before committing.
- Use `gh run list`, `gh run view --log-failed`, and diagnostic artifacts to investigate Windows CI rather than asking the user to copy logs manually.
- Do not commit or push unless the user asks.
- Do not dispatch long CI builds unnecessarily; local tests and `desktop:smoke` should pass first.
