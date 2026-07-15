# Karaoke Box — Agent Handoff Guide

Read this file before changing the repository. Also read `README.md` and the relevant design documents: `docs/DESKTOP.md` for the primary product, `docs/PLAN.md` for the roadmap, and `docs/SEPARATOR_UPGRADE.md` for the current implementation batch.

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
- **Audio:** FFmpeg/ffprobe + CPU-only Demucs/PyTorch with optional MelBand RoFormer runtime
- **Persistence:** per-job JSON and ordinary local media files
- **Automatic retention:** none; jobs/models remain until explicitly deleted

Do not introduce CUDA. The processor passes `--device cpu`, desktop startup clears `CUDA_VISIBLE_DEVICES`, and Windows CI reinstalls PyTorch from the CPU wheel index.

## Current architecture

### Browser-development mode

```text
Vite 127.0.0.1:5173 -- /api proxy --> FastAPI 127.0.0.1:8000
                                               |
                                               +--> job.json + media under data/jobs
                                               +--> yt-dlp / selected separator subprocess
```

### Desktop mode

```text
pywebview window
      |
random 127.0.0.1 port + per-launch HttpOnly session cookie
      |
FastAPI serves web/dist and /api
      |
JSON job store + yt-dlp/selected-separator child process + bundled FFmpeg tools
```

Desktop data is resolved with `platformdirs`:

```text
%LOCALAPPDATA%\Karaoke Box\
  jobs\<job-id>\job.json
  jobs\<job-id>\source.<extension>
  jobs\<job-id>\instrumental.wav
  jobs\<job-id>\vocals.wav
  jobs\<job-id>\demucs.log
  jobs\<job-id>\melband-roformer.log # MelBand jobs only
  jobs\<job-id>\yt-dlp.log       # YouTube jobs only
  models\
    melband-roformer\kimberley_melband_roformer_v1\MelBandRoformer.ckpt
  logs\desktop.log
```

On macOS desktop-development mode, the equivalent platform application-data directory is used.

## Implemented user features

- MP3/WAV/M4A/FLAC/OGG/AAC/Opus upload
- Individual HTTPS YouTube video ingest through pinned `yt-dlp`
- Source-neutral, versioned rights attestation for uploads and URL ingest
- 250 MB and a 10-minute default source-duration limit; an intentional `KARAOKE_MAX_DURATION_SECONDS` operator override can raise it
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
- Selectable CPU separator engines: Demucs remains the default faster/current path; optional MelBand RoFormer is implemented as an experimental high-quality path
- Post-separation Lyric Lab: user-selected synchronized LRCLIB lyrics, line timing edits, and local 1080p karaoke MP4 rendering; untimed alignment and per-word editing remain deferred

## Important implementation details

### Progress

`backend/app/processor.py` streams merged Demucs output through `subprocess.Popen`. `DemucsProgressTracker` parses processed audio-seconds and combines multiple model passes. Do not replace this with `subprocess.run`, which would buffer all progress until completion.

The ETA clock begins at Demucs’s first 0% audio progress line so model download/loading time is not incorrectly treated as recurring inference work.

### Quality profiles

Profiles are defined in `backend/app/profiles.py`. Output filenames differ by method:

- subtractive: `minus_vocals.wav`
- summed stems: `no_vocals.wav`

Keep the output-path mapping aligned with Demucs CLI behavior.

### Current feature batch: selectable MelBand RoFormer engine

Phase 1C implementation is locally complete. **Kimberley Jensen MelBand RoFormer** is available as an optional experimental high-quality engine while the current Demucs implementation remains the default faster/current option. It is not production-ready: the exact design, benchmark record, immutable model source/checksum, license record, file layout, API fields, worker protocol, test requirements, and pending release gates are recorded in `docs/SEPARATOR_UPGRADE.md`. Preserve that specification rather than inventing a different architecture.

Pinned selection:

- Engine ID: `melband_roformer`
- Model ID: `kimberley_melband_roformer_v1`
- Checkpoint revision: `ac9b0614ab3cd7f77219e18ba494dfd93956c348`
- Expected size: `913106900` bytes
- SHA-256: `87201f4d31afb5bc79993230fc49446918425574db48c01c405e44f365c7559e`
- Model weight and selected runtime source: MIT

Non-negotiable implementation boundaries:

- CPU-only on macOS development and Windows x64; never select CUDA, MPS, or DirectML.
- Do not add the `audio-separator` package. Vendor only the pinned MIT RoFormer implementation described in the design document and keep NumPy below 2.
- Do not silently replace, remove, rename, or change existing `preserve`, `best`, and `standard` behavior. Demucs/`preserve` remains the default.
- Preserve stable `instrumental.wav` and `vocals.wav` assets and existing job history.
- Persist `separator_engine` and exact `separator_model` in `job.json`; old jobs without them restore as Demucs.
- Put all engine invocation/model resolution behind the adapter registry. Do not add engine branches to API routes or `JobManager`.
- Stream child inference with `subprocess.Popen` and the specified progress protocol. Never buffer model inference with `subprocess.run`.
- Download the checkpoint into the application model directory with an atomic partial file, expected-size check, and full SHA-256 verification. Keep valid weights until explicit deletion.
- Routine tests must use mocks, fake models, and short self-created arrays; they must not download the checkpoint or run full inference.
- Run `npm test` and `npm run desktop:smoke` before considering implementation complete. Do not dispatch Windows packaging.

### Current feature batch: Karaoke Video Studio

The Phase 1D line-timed Karaoke Video Studio is complete in the local working tree. After stem separation, the user can explicitly select synchronized LRCLIB lyrics, edit line timing and visual settings, preview against synchronized instrumental/vocal audio, and render a local karaoke MP4. `docs/KARAOKE_VIDEO.md` is the authoritative implementation and validation handoff.

Important boundaries:

- LRCLIB access is fixed to `https://lrclib.net`, bounded, redirect-restricted, and type-strict. Traditional synchronized LRC and valid version `1.0` `lyricsfile` YAML are accepted; YAML aliases, excessive depth/node counts, malformed timing, non-finite/oversized numeric values, and invalid provider records are rejected. Invalid provider word timing falls back to valid line timing.
- Karaoke project, job-state, and optional canonical PNG background changes use revision-checked compare-and-commit under the job-store lock. A stale revision or active render is rejected; handled write failures restore the prior project/job/background state and remove staging files.
- Separation and rendering share the existing single-worker executor. Render queueing is duplicate-safe and rolls back if submission fails. FFmpeg is streamed with `subprocess.Popen`; failure preserves the prior `karaoke.mp4`, terminates/reaps the child when needed, and removes partial/scratch output. Startup marks interrupted renders failed, and active rendering blocks deletion and normal desktop closure.
- The renderer uses bundled, provenance-recorded OFL fonts rather than system fonts. Selected Latin faces have Noto fallback coverage for non-ASCII text and a checked symbol set; do not claim universal-script coverage. Font sources, package/release identities, checksums, embedded copyright notices, and OFL mapping are in `backend/app/karaoke_assets/PROVENANCE.md`.
- The editor marks unsaved changes and the prior MP4 stale immediately, warns before browser unload or leaving the studio, saves before background upload/render, restores and polls active renders, and keeps instrumental/vocal preview seeking and playback synchronized with an adjustable vocal guide.
- Untimed alignment, user `.lrc` import, manual per-word editing, a waveform editor, microphone/performance recording, mixed-performance exports, rights manifests, durable lyrics-license enforcement, and broader glyph coverage remain deferred.
- Current evidence is local macOS development evidence only. The Karaoke Video Studio has not been built or smoke-tested in a Windows package, and historical run `29303479616` validates Phase 1C only. Do not claim production readiness, legal licensing, manual browser/accessibility validation, or Windows renderer validation.

### Required delegation for Phase 1C and future sessions

Phase 1C implementation is locally complete; do not reopen its architecture or ask agents to redesign it. For any bounded future planning/planner work or review/reviewer work, use the installed `pi-subagents` package with `openai-codex/gpt-5.6-sol` at `xhigh` reasoning. For any implementation/writer/fix work, use `openai-codex/gpt-5.6-luna` at `xhigh` reasoning. Configure the builtin `planner`, `reviewer`, and `worker` overrides to those model/reasoning levels before starting; their packaged defaults use `high`.

Do not launch nested `pi` subprocesses. Do not ask sub-agents to produce a fresh architecture or give them open-ended discretion. Use the exact Phase 1C implementation prompts and file boundaries in `docs/SEPARATOR_SUBAGENT_PROMPTS.md`; inspect each diff and focused test result before launching the next worker. Workers share the current working tree, so keep one implementation writer at a time. Preserve fresh-context Sol review behavior; only Luna agents implement changes.

### Desktop session security

`backend/app/desktop.py` generates a random `KARAOKE_SESSION_TOKEN`. `/desktop/start` exchanges the URL token for an HttpOnly, SameSite=Strict cookie. When the token is configured, middleware protects `/api/*`.

Do not expose the desktop API on `0.0.0.0`, use a fixed unauthenticated port, or remove the session check.

### Frozen worker execution

A PyInstaller executable cannot run `sys.executable -m demucs`, `sys.executable -m yt_dlp`, or a new module worker because `sys.executable` points back to `KaraokeBox.exe`. `backend/app/runtime.py` returns:

- development: `python -u -m demucs`, `python -u -m yt_dlp`, and `python -u -m app.separators.worker`
- frozen build: `KaraokeBox.exe --internal-demucs`, `KaraokeBox.exe --internal-ytdlp`, and `KaraokeBox.exe --internal-separator`

The documented browser API starts from the repository root with Uvicorn's `--app-dir backend`. That setting adjusts only the API process import path; it does not propagate to child interpreters. The development separator adapter therefore launches the unchanged module command with `<repo>/backend` as its child working directory. `backend/desktop_entry.py` dispatches frozen private commands through `app.desktop`. Preserve the existing Demucs and yt-dlp adapters and the frozen separator dispatch.

### Windowed logging

Windowed PyInstaller has `sys.stdout`/`sys.stderr` set to `None`. Desktop Uvicorn must use `log_config=None`; otherwise Uvicorn calls `stderr.isatty()` and crashes. Desktop phases/errors are written to `KARAOKE_DESKTOP_LOG` or the platform log directory.

### Local storage

There is deliberately no 24/48-hour cleanup. Only temporary separator working output is removed after a successful job. Source files, results, history, and model weights persist until explicit deletion.

## Key paths

- `web/src/App.tsx` — current single-page UI, API calls, restoration/history, player
- `web/src/App.css` — application styling
- `web/vite.config.ts` — local `/api` proxy
- `backend/app/main.py` — FastAPI routes, session middleware, static frontend mount
- `backend/app/jobs.py` — JSON job model/store and single-worker manager
- `backend/app/processor.py` — ffprobe, source-neutral adapter orchestration, progress/ETA, output finalization
- `backend/app/youtube.py` — YouTube URL validation, metadata preflight, controlled `yt-dlp` ingest
- `backend/app/lyrics.py`, `backend/app/karaoke.py`, `backend/app/karaoke_renderer.py` — fixed-host LRCLIB lookup, versioned lyric projects, and local Pillow/FFmpeg karaoke rendering
- `backend/app/rights.py` — shared source attestation text/version
- `backend/app/profiles.py` — model/method/profile definitions
- `backend/app/runtime.py` — frozen resources, bundled tools, Demucs/yt-dlp/separator command adapters and development worker cwd
- `backend/app/desktop.py` — desktop environment, API lifecycle, pywebview, smoke test
- `backend/desktop_entry.py` — PyInstaller entry point
- `packaging/windows/KaraokeBox.spec` — PyInstaller onedir definition
- `packaging/windows/KaraokeBox.iss` — Inno Setup installer
- `.github/workflows/windows-desktop.yml` — Windows build/test/package workflow
- `docs/DESKTOP.md` — detailed desktop architecture
- `docs/SEPARATOR_UPGRADE.md` — exact current Phase 1C implementation design and handoff
- `docs/SEPARATOR_SUBAGENT_PROMPTS.md` — bounded Luna xhigh worker prompts for Phase 1C
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

Historical packaged baseline:

- Commit: `a9bd865`
- Successful run: `29280123857`
- Run URL: `https://github.com/ishaan-ghosh/karaoke-box/actions/runs/29280123857`
- Artifact: `KaraokeBox-Windows-x64` (roughly 374 MB compressed)

Current Phase 1C Windows checkpoint:

- Pushed commit: `1c5bfb2db59868ec20bff02be0ba41c323041afc` on `main`
- Successful run: `29303479616`
- Run URL: `https://github.com/ishaan-ghosh/karaoke-box/actions/runs/29303479616`
- Artifact: `KaraokeBox-Windows-x64`, 383324580 compressed bytes
- The run passed 61 backend tests plus frontend checks, the CPU-only Torch reinstall, PyInstaller onedir build, packaged authenticated startup/health and no-weight/no-network internal separator probe, Inno Setup installer build, and artifact upload.
- The artifact includes the portable onedir app and installer. The MelBand checkpoint remains unbundled by design.

The executable is not standalone; the entire `dist/KaraokeBox` directory must remain together.

## Testing status

Current verified local working-tree state:

- 124 backend tests pass.
- 8 Vitest tests pass, followed by oxlint, TypeScript compilation, and the Vite production build.
- `npm --prefix web ci --offline --ignore-scripts` passes from the lockfile. The resolved frontend validation toolchain is Vite 8.1.4 and Vitest 4.1.9; the explicit `tinyexec` override resolves to 1.2.4.
- Desktop development smoke passes, including authenticated startup/health and the no-weight/no-network separator worker probe.
- The accepted self-created final render fixture at `/tmp/karaoke-box-render-accepted-ci9Va9/karaoke.mp4` was 50,547 bytes and probed as H.264, 1920×1080, 30 fps, yuv420p video plus AAC audio with a duration of 1.000000 seconds. Fixture inspection confirmed smart punctuation and a verified symbol glyph, with no surviving partial MP4, render scratch directory, or local-path disclosure.
- Final fresh-context Sol backend and frontend review gates returned `ACCEPT`.
- Routine validation remained offline/mock-based: it did not contact LRCLIB, download separator weights, run full separator inference, package Windows, or dispatch CI.
- No manual browser matrix or assistive-technology validation was performed. These checks are local macOS development evidence, not Windows package evidence or production-readiness evidence.
- The protected Phase 1C listening, Windows run, artifact, and target-laptop stem-audio facts below remain unchanged.

Historical packaged Windows baseline `a9bd865`:

- 11 backend tests passed at that commit.
- Packaged startup/session/health smoke test passed.
- Inno Setup build and artifact upload passed.
- That historical baseline predated the Phase 1C MelBand package and target-PC inference test; do not use it as evidence for the current separator.

## Known limitations and deferred work

- Karaoke Video Studio is complete only as a locally validated, line-timed MVP. Untimed alignment, user `.lrc` import, manual per-word editing, waveform editing, microphone/performance recording, mixed-performance export, rights manifests, durable lyrics-license enforcement, and broader glyph coverage remain deferred.
- Deferred application hardening includes cooperative cancellation and reaping of a running FFmpeg render during forced/abnormal shutdown, global UUID canonicalization of job IDs at the API/JobStore boundary, and ASGI-level request-body limits that reject oversized multipart bodies before parsing. Current upload limits are enforced while reading the parsed `UploadFile`.
- Windows packaging for the renderer, bundled fonts/Pillow/PyYAML, and the libx264/AAC render path remains unverified. Packaged notice/license verification, clean-Windows renderer testing, and manual browser/accessibility testing are outstanding; historical run `29303479616` must not be cited as MP4-renderer evidence.
- The current Windows run validates the frozen package and no-weight/no-network worker probe, and the target laptop completed one real packaged MelBand inference. A cached performance check covering the default 10-minute range, with target hardware, elapsed time, peak RAM/disk, and an explicit acceptability decision, remains outstanding.
- Current Demucs separation can leave phasey/static-like vocal residue or damage overlapping instruments; the optional MelBand RoFormer engine is experimental and may have different artifacts.
- MelBand RoFormer is not production-ready. The full permitted real-song/fixture A/B listening gate is complete: in same-song comparisons against all three Demucs profiles, the user preferred MelBand on every test; vocal residual was negligible with faint static still audible, instrument damage was effectively imperceptible, and karaoke usefulness was substantially better. Frozen Windows build/smoke and one target-PC real-song full inference are complete. Remaining release gates are packaged third-party-notice verification and a cached performance check covering the default 10-minute range with target hardware, elapsed time, peak RAM/disk, and an explicit acceptability decision. Broader clean-Windows release-matrix testing and signing remain separate release work. The default supported source-duration range is 10 minutes; operators can intentionally raise it with `KARAOKE_MAX_DURATION_SECONDS` when local policy and hardware permit.
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
- The packaged Windows runtime currently uses Python 3.10; move the next Windows package to Python 3.11 to remove the nonfatal yt-dlp 2026.7.4 deprecation output.
- One initial YouTube media transfer selected format 251 and failed with HTTP 403 after metadata succeeded; another YouTube video subsequently worked end to end. Treat this as transient/video- or route-specific evidence, not a fixed bug. Change yt-dlp retry/actionable diagnostics only from reproducible evidence.
- `processor.py` can briefly publish `separating` before MelBand changes to `preparing`; this is cosmetic deferred maintenance.
- A macOS PyInstaller build reached final bootloader conversion but was blocked by the development machine’s unaccepted Xcode license; Windows CI is authoritative.

## Git and workflow practices

- Inspect `git status` before editing; do not overwrite user changes.
- Keep changes focused and update tests/docs when behavior changes.
- Run tests before committing.
- Use `gh run list`, `gh run view --log-failed`, and diagnostic artifacts to investigate Windows CI rather than asking the user to copy logs manually.
- Do not commit or push unless the user asks.
- Do not dispatch long CI builds unnecessarily; local tests and `desktop:smoke` should pass first.
- The next session must inspect and preserve the current working tree, which contains the locally complete but uncommitted Phase 1D implementation, rather than resuming from only the pushed Phase 1C checkpoint. Keep Phase 1C architecture frozen, preserve Demucs as the default faster/current engine, and preserve the permanent CPU-only boundary: do not add CUDA, MPS, or DirectML.
