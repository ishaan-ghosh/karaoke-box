# Karaoke Box — Product and Technical Plan

## 1. Product goal

Create a browser-based karaoke studio where a user can:

1. Choose an audio source they are allowed to adapt.
2. Separate vocals from accompaniment.
3. Correct timing and add licensed or user-supplied lyrics.
4. Sing and record in the browser.
5. Export a mixed performance together with a rights/attribution manifest.

The product must not promise that vocal removal, re-recording, pitch changes, or other transformations make copyrighted music copyright-free or prevent Content ID claims.

## 2. Rights-safe boundaries

### Supported inputs

The local MVP accepts audio files uploaded by a user who owns the recording or has permission to adapt it. This can include the user's own recording, a suitably licensed recording, or a public-domain composition paired with a newly made or properly licensed recording.

There is no URL ingestion, YouTube integration, downloader, or third-party source catalog.

### Lyrics

Do not scrape lyrics. Accept user-authored/licensed lyrics, public-domain lyrics, or lyrics from a licensed provider. Store provenance and license information.

### Exports

Every export should include a rights manifest identifying the composition, source recording, lyric source, licenses, attribution, and user attestation. Do not label outputs “copyright-free” unless their rights actually establish that. Do not promise that YouTube, Instagram, or another platform will accept an upload without a claim.

> Product guidance only, not legal advice. Before a public launch or licensed catalog integration, have the intended workflow and terms reviewed by an appropriate copyright lawyer.

## 3. MVP user flow

1. **Choose a file**
   - Upload an authorized MP3, WAV, M4A, FLAC, OGG, AAC, or Opus file.
2. **Confirm rights**
   - Confirm ownership, permission, or a license that permits processing.
3. **Process audio**
   - Normalize media with FFmpeg.
   - Run source separation to produce vocal and instrumental stems.
   - Let the user preview and adjust stem levels.
4. **Prepare karaoke view**
   - Import user-provided `.lrc` lyrics or enter lyrics manually.
   - Edit line timestamps in a waveform-based editor.
5. **Perform**
   - Check microphone permissions and latency.
   - Play the instrumental and synchronized lyrics.
   - Record the microphone as a separate take.
6. **Mix and export**
   - Adjust backing/vocal levels and optional reverb/compression.
   - Render WAV/M4A and optionally MP4 with a simple lyric background.
   - Generate `rights-manifest.json` and an attribution text file.

## 4. Recommended architecture

### Frontend

- **React + TypeScript + Vite** for the local browser UI.
- The Vite development server proxies `/api` to the Python service.
- Native audio elements provide synchronized stem preview and volume control.

### Local API and processing

- **FastAPI** accepts multipart uploads and exposes job status/assets.
- **Demucs** performs two-stem separation with `--device cpu`.
- **FFmpeg/ffprobe** validates the source and reads its duration.
- A single-thread executor serializes expensive CPU jobs.
- Source files, metadata, logs, and WAV stems are stored under local `data/jobs/`.

### Local deployment shape

```text
Browser --> Vite (127.0.0.1:5173) -- /api proxy --> FastAPI (127.0.0.1:8000)
                                                       |
                                                       +--> FFprobe + Demucs CPU
                                                       +--> data/jobs/<job-id>/
```

The local MVP has no authentication, database, Redis, Docker, cloud storage, or GPU worker.

### Primary distribution target — Windows desktop

```text
Karaoke Box.exe
  |-- pywebview window --> compiled React/Vite assets
  |-- loopback FastAPI --> JSON job metadata
  +-- Demucs subprocess --> local media/model directories
```

- **pywebview** provides a native Windows window backed by Edge WebView2.
- **FastAPI** serves both the compiled frontend and local API on a random loopback port protected by a per-launch token.
- **JSON job files** store durable local job history without adding a database dependency.
- **Local files** under `%LOCALAPPDATA%\Karaoke Box` store sources, stems, logs, and model weights.
- **Demucs** runs in a separate child process with one CPU job at a time.
- Jobs and model files persist until the user explicitly deletes them.
- **PyInstaller onedir + Inno Setup** produces the Windows x64 installer through a Windows GitHub Actions runner.

See `docs/DESKTOP.md` for packaging and lifecycle details.

### Optional hosted target

A hosted version can later use Cloudflare DNS/proxy, a VPS/container origin, PostgreSQL, object storage, and external workers. Repository, media-storage, and worker interfaces should keep that migration possible, but hosted infrastructure is not required for the desktop release. See `docs/DEPLOYMENT.md`.

## 5. Local job model

Each job has a UUID directory and a `job.json` file containing:

- original and internal source filenames,
- byte size and detected duration,
- status, progress, and user-facing message,
- error details when processing fails,
- creation and update timestamps.

Completed job directories also contain `instrumental.wav`, `vocals.wav`, and `demucs.log`.

For the Windows application, the same domain model moves behind repository/storage interfaces:

- Per-job JSON files store metadata, progress, and history.
- `%LOCALAPPDATA%\Karaoke Box\jobs` stores source and generated media until explicit deletion.
- A separate child process executes one job at a time.
- Local JSON/filesystem implementations remain available during migration and tests.

The interfaces can later gain PostgreSQL/object-storage/remote-worker adapters if a hosted version is revived.

## 6. API outline

- `GET /api/health`
- `GET /api/jobs` — reload-safe local history and active-job discovery
- `POST /api/jobs` — authorized multipart upload and queued separation (local adapter)
- `GET /api/jobs/:id` — status polling
- `GET /api/jobs/:id/assets/:stem` — inline preview or WAV download
- `DELETE /api/jobs/:id` — remove a completed/failed local job

The upload route enforces extension, size, duration, audio-stream, and rights-confirmation checks. Desktop mode will use the native file picker and copy an authorized source into the application job directory, avoiding network upload limits while retaining the same job API semantics.

## 7. Processing pipeline

1. Enforce an extension allowlist and a 250 MB streaming upload limit.
2. Validate the file with `ffprobe`; require an audio stream and a duration no longer than 20 minutes.
3. Run the selected Demucs profile on CPU: subtractive `htdemucs`, subtractive fine-tuned `htdemucs_ft`, or summed-stem `htdemucs`.
4. Move full-quality `vocals.wav` and the selected accompaniment result into stable job assets.
5. Preview both stems in sync and offer the instrumental as a WAV download.
6. Retain a local Demucs log for troubleshooting.

Separation quality will vary. Backing vocals, reverb, and centered instruments may leak between stems. The UI should present this as an assistive tool, not perfect removal.

## 8. Security and abuse controls

- Bind the desktop API only to a random loopback port and require a per-launch session token.
- Validate selected files in the backend; never construct shell commands from user strings.
- Enforce file-size, duration, disk-space, and single-worker concurrency limits.
- Resolve application data with `platformdirs`; do not write beside the installed executable.
- Isolate the Demucs child process, cap runtime/resources where practical, and clean scratch files after every job.
- Never delete active jobs; make all user-data deletion explicit and retry files temporarily locked by Windows.
- Verify first-run model downloads and keep model/media paths separate.
- Sign public Windows installers to reduce SmartScreen and antivirus warnings.
- Add hosted authentication, ownership, quotas, and takedown handling only if remote multi-user access returns.
- Do not add “anti-detection,” fingerprint alteration, metadata spoofing, or automated dispute features.

## 9. Delivery phases

### Phase 0 — local foundation (implemented)

- Create the React + TypeScript + Vite application.
- Add the FastAPI local job service and filesystem store.
- Add linting, compilation, backend tests, setup docs, and Make targets.

### Phase 1 — authorized upload and separation (implemented)

- Implement local multipart uploads and rights confirmation.
- Run FFprobe validation and CPU-only Demucs separation.
- Add job polling, streamed Demucs pass progress and ETA, upload byte progress, selectable quality/accompaniment profiles, synchronized stem playback, volume controls, and instrumental WAV download.

**MVP checkpoint:** an authorized local audio file becomes playable vocal/instrumental stems.

### Phase 2 — desktop runtime

- Serve the compiled Vite build from FastAPI.
- Add a pywebview launcher with random-port/session-token lifecycle handling.
- Introduce repository, media-path, and Demucs-command interfaces.
- Add `platformdirs`, bundled-tool resolution, explicit deletion, and disk-space admission checks.
- Handle active processing on window close and graceful child-process shutdown.

### Phase 3 — Windows package

- Add a PyInstaller onedir spec with CPU-only PyTorch, Demucs, frontend assets, and bundled FFmpeg tools.
- Add a GitHub Actions Windows build and packaged startup smoke test.
- Create an Inno Setup per-user installer with WebView2 detection/bootstrap.
- Test on clean Windows 10/11 x64, including Unicode paths, Defender behavior, sleep/wake, and uninstall/upgrade.
- Add Authenticode signing before broad public distribution.

### Phase 4 — lyrics and performance

- Add `.lrc` import, manual editing, and timestamp controls.
- Build the karaoke player.
- Add microphone setup, latency calibration, and separate take recording.

### Phase 5 — mixing and export

- Add mix controls and worker-side audio rendering.
- Add simple lyric-video rendering.
- Generate rights and attribution manifests.
- Consider licensed catalog or platform upload integrations only after rights review; never promise claim-free uploads.

## 10. Testing strategy

- Unit-test FFprobe metadata handling and rights confirmation.
- Integration-test multipart uploads, status transitions, duration/size rejection, and local cleanup.
- Keep short, self-created audio fixtures for deterministic processing smoke tests.
- Add browser tests for upload, polling, playback synchronization, and deletion.
- Test Chromium, Firefox, and Safari because media playback and future recording support differ.

## 11. Decisions recorded

1. macOS/Apple Silicon remains the development environment.
2. Windows 10/11 x64 is the primary packaged runtime and must be built/tested on Windows.
3. Single-user desktop application; no hosted authentication is required initially.
4. Audio-only export for the initial product.
5. User-selected local source files only.
6. React + TypeScript + Vite UI with Python/FastAPI, pywebview, JSON job metadata, and a separate Demucs child process.
7. CPU-only PyTorch permanently; no CUDA distribution.
8. PyInstaller onedir plus Inno Setup, built by GitHub Actions on Windows.

## 12. Current implementation checkpoint

The first vertical slice is implemented: authorized local upload with byte progress, FFprobe validation, selectable subtractive/fine-tuned/summed-stem CPU Demucs separation with live pass progress and ETA, reload-safe polling and active-job restoration, local result history, synchronized stem playback, level controls, explicit cleanup, and instrumental WAV download.

The next quality-sensitive checkpoint is to test several user-owned songs end to end and record runtime/memory on the target Windows hardware. The next architecture checkpoint is Phase 2: create the desktop launcher and separate persistence, paths, and frozen-runtime execution behind interfaces before implementing lyrics or microphone recording.
