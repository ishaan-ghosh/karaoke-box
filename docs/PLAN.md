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

The product supports two ways to provide a source recording:

- Upload an MP3, WAV, M4A, FLAC, OGG, AAC, or Opus file.
- Paste the URL of an individual YouTube video. The local API uses `yt-dlp` to fetch the best available audio source, preferring audio-only formats and falling back to an audio-containing format when necessary; it does not force an additional MP3 transcode before validation.

Both paths create a local source asset and then enter the same validation and separation pipeline. URL ingest is limited to individual YouTube videos; playlist/channel URLs without an explicit video, live streams, arbitrary web URLs, cookies, and access-control bypasses are out of scope. Queue parameters are ignored when a URL explicitly identifies one video.

A video being publicly reachable on YouTube does not mean that the user may download, adapt, or export it. `yt-dlp` is only a transfer mechanism: using it grants no license, transfers no rights, and does not make the source or resulting stems copyright-free.

### Source attestation

Before an upload is accepted or a URL fetch begins, require the same source-neutral attestation:

> I confirm that I own this source recording or am authorized to use it, including downloading it when I provide a URL, and that I am permitted to process and export it.

Store the attestation text/version, confirmation timestamp, and source type with the job. The attestation records the user's representation; it is not proof of ownership and does not replace a license.

### Lyrics

The current local Lyric Lab uses a fixed-host LRCLIB client and requires explicit user selection of synchronized results. It stores provider provenance and states that Karaoke Box makes no license claim for returned lyrics; it does not add a second lyrics-rights checkbox. User-authored/licensed, public-domain, or licensed-provider enforcement and a durable lyrics license field remain release work.

### Exports

The current local karaoke MP4 stores the selected lyric provenance with the project but does not yet emit the future rights manifest. A later licensed-catalog/release gate must identify the composition, source recording, lyric source, licenses, attribution, and user attestation. For a file upload, record the original filename and user-supplied provenance. For YouTube ingest, also record the canonical URL, YouTube video ID, title, uploader/channel name and ID when available, and fetch timestamp. Uploader metadata establishes provenance only; it does not establish that the uploader or user owns the necessary rights.

Do not label outputs “copyright-free” unless their rights actually establish that. Do not promise that YouTube, Instagram, or another platform will accept an upload without a claim.

> Product guidance only, not legal advice. Before a public launch or licensed catalog integration, have the intended workflow and terms reviewed by an appropriate copyright lawyer.

## 3. MVP user flow

1. **Choose a source**
   - Upload a supported audio file or paste an individual YouTube video URL.
2. **Confirm rights**
   - Make the source-neutral attestation before the application stores an upload or fetches a URL.
3. **Ingest and validate**
   - Stream an uploaded file into the job directory, or use `yt-dlp` to fetch the YouTube video's best available audio source, preferring audio-only formats.
   - Validate either source with `ffprobe`, then normalize it with FFmpeg.
4. **Separate audio**
   - Run source separation to produce vocal and instrumental stems.
   - Let the user preview and adjust stem levels.
5. **Prepare karaoke video**
   - Search the fixed LRCLIB service and explicitly select synchronized lyrics.
   - Edit line text/timestamps and visual settings; user `.lrc` import, untimed alignment, manual per-word timing, and waveform editing remain deferred.
6. **Preview and render**
   - Preview synchronized lyrics against the instrumental with an optional vocal guide.
   - Render a local instrumental-audio karaoke MP4 while retaining lyric provenance in the versioned project.
7. **Perform, mix, and broaden export (future)**
   - Add microphone setup, latency calibration, and separate take recording.
   - Add performance mixing, additional release-approved exports, and a rights/attribution manifest.

## 4. Recommended architecture

### Frontend

- **React + TypeScript + Vite** for the local browser UI.
- The Vite development server proxies `/api` to the Python service.
- Native audio elements provide synchronized stem preview and volume control.

### Local API and processing

- **FastAPI** accepts multipart file uploads and YouTube URL submissions, and exposes job status/assets.
- **yt-dlp** fetches a submitted YouTube video's best available audio source, preferring audio-only formats, into controlled job storage.
- **FFmpeg/ffprobe** validates either kind of source and reads its duration.
- **Demucs** remains the default faster/current two-stem engine with `--device cpu`; the optional experimental MelBand RoFormer engine uses the same CPU-only boundary.
- A single-thread executor serializes source ingest and expensive CPU jobs.
- Source files, provenance metadata, logs, and WAV stems are stored under local `data/jobs/`.

### Local deployment shape

```text
Browser --> Vite (127.0.0.1:5173) -- /api proxy --> FastAPI (127.0.0.1:8000)
                                                       |
                                                       +--> multipart upload ------+
                                                       +--> YouTube URL --> yt-dlp +--> job source
                                                       +--> ffprobe + Demucs CPU
                                                       +--> data/jobs/<job-id>/
```

The local MVP has no account, database, Redis, Docker, cloud storage, or GPU worker. Processing and persistence stay local, although URL ingest necessarily makes an outbound request to YouTube.

### Primary distribution target — Windows desktop

```text
Karaoke Box.exe
  |-- pywebview window --> compiled React/Vite assets
  |-- loopback FastAPI --> JSON job metadata
  +-- selected separator subprocess --> local media/model directories
```

- **pywebview** provides a native Windows window backed by Edge WebView2.
- **FastAPI** serves both the compiled frontend and local API on a random loopback port protected by a per-launch token.
- **JSON job files** store durable local job history, source provenance, and attestations without adding a database dependency.
- **Local files** under `%LOCALAPPDATA%\Karaoke Box` store uploaded or fetched sources, stems, logs, and model weights.
- **yt-dlp** performs a controlled network fetch for YouTube jobs; the selected separator then runs in a separate child process with one CPU job at a time. Demucs is the default faster/current engine; MelBand RoFormer is optional and experimental.
- Jobs and model files persist until the user explicitly deletes them.
- **PyInstaller onedir + Inno Setup** produces the Windows x64 installer through a Windows GitHub Actions runner.

See `docs/DESKTOP.md` for packaging and lifecycle details.

### Optional hosted target

A hosted version can later use Cloudflare DNS/proxy, a VPS/container origin, PostgreSQL, object storage, and external workers. Repository, media-storage, and worker interfaces should keep that migration possible, but hosted infrastructure is not required for the desktop release. See `docs/DEPLOYMENT.md`.

## 5. Local job model

Each job has a UUID directory and a `job.json` file containing:

- source type (`upload` or `youtube`) and the internal source filename,
- the original filename for an upload, or the canonical URL, video ID, title, uploader/channel name and ID, and extractor metadata for YouTube,
- byte size and `ffprobe`-detected duration,
- the rights-attestation text/version and confirmation timestamp,
- ingest/separation status, progress, and user-facing message,
- error details when ingest or processing fails,
- creation, fetch, and update timestamps as applicable.

Job directories retain the uploaded or fetched source. Completed jobs also contain `instrumental.wav`, `vocals.wav`, and the engine-specific `demucs.log` or `melband-roformer.log`; URL jobs may additionally retain a sanitized `yt-dlp` diagnostic log. Verified MelBand weights live under the platform model directory (`KARAOKE_MODEL_DIR` in desktop mode), not in a job directory.

For the Windows application, the same domain model moves behind repository/storage interfaces:

- Per-job JSON files store metadata, source provenance, attestation, progress, and history.
- `%LOCALAPPDATA%\Karaoke Box\jobs` stores uploaded or fetched source media and generated assets until explicit deletion.
- A separate worker serializes URL fetches and separation jobs.
- Local JSON/filesystem implementations remain available during migration and tests.

The interfaces can later gain PostgreSQL/object-storage/remote-worker adapters if a hosted version is revived.

## 6. API outline

- `GET /api/health`
- `GET /api/jobs` — reload-safe local history and active-job discovery
- `POST /api/jobs` — attested multipart file upload and queued separation
- `POST /api/jobs/youtube` — attested YouTube video URL and queued `yt-dlp` ingest/separation
- `GET /api/jobs/:id` — ingest/separation status polling, including source provenance
- `GET /api/jobs/:id/assets/:stem` — inline preview or WAV download
- `DELETE /api/jobs/:id` — remove a completed/failed local job and its uploaded or fetched source

Both creation routes require `rights_confirmed=true`, a separation profile, and the same versioned attestation. The server records the attestation text and timestamp rather than treating the boolean as a license.

The file route enforces the extension and streaming byte limit before queueing the existing validation/separation work. Desktop mode may use the native file picker and copy the selected source into the application job directory while retaining the same job semantics.

The YouTube route accepts JSON containing one HTTPS video URL. It creates a job before the fetch so the client can poll an `ingesting` state; the worker then resolves metadata and downloads audio with `yt-dlp`. The route must reject non-YouTube hosts, playlist/channel URLs without an explicit video, unsupported video types, and any client-supplied `yt-dlp` arguments. When a watch URL contains `v=` plus queue context such as `list=RD...`, the server canonicalizes it to that one video and still passes `--no-playlist`. The browser sends only the URL—the local API performs the fetch directly into job scratch storage.

## 7. Processing pipeline

1. Require and persist the source-neutral rights attestation before accepting source bytes or starting a network fetch.
2. Ingest one source:
   - **File:** enforce the upload extension allowlist and 250 MB streaming limit while writing to the job directory.
   - **YouTube:** validate an individual video URL, use `yt-dlp` to resolve the canonical video ID/uploader metadata, and fetch the best available audio source—preferring audio-only formats—into controlled scratch storage. Apply metadata preflight checks when available and abort a download that exceeds the byte limit.
3. Validate the resulting local media with `ffprobe`; require an audio stream and a measured duration no longer than the 10-minute default supported range. An operator can intentionally raise that limit with `KARAOKE_MAX_DURATION_SECONDS` when local policy and hardware permit. `yt-dlp` metadata is provenance and preflight data, not a substitute for this validation.
4. Feed the validated source through the same source-neutral adapter pipeline regardless of origin. Run the selected CPU engine: Demucs profiles are subtractive `htdemucs`, subtractive fine-tuned `htdemucs_ft`, or summed-stem `htdemucs`; optional MelBand RoFormer is a preserve/residual experimental path.
5. Move full-quality `vocals.wav` and the selected accompaniment result into stable job assets.
6. Preview both stems in sync and offer the instrumental as a WAV download.
7. Retain local selected-separator and sanitized ingest diagnostics for troubleshooting, plus the provenance needed by the future rights manifest.

Separation quality will vary. Backing vocals, reverb, and centered instruments may leak between stems. YouTube's available audio may already be lossily encoded. The UI should present separation as an assistive tool, not perfect removal, and must not imply that successful ingest changes the source's rights status.

## 8. Security and abuse controls

- Bind the desktop API only to a random loopback port and require a per-launch session token.
- Validate selected files and YouTube URLs in the backend; pass fixed argument arrays to subprocesses and never construct shell commands from user strings.
- Allow only `yt-dlp`'s YouTube video extractor and a server-owned output template. Do not accept arbitrary URLs, client options, browser cookies, credentials, playlist-only URLs, or access-control/DRM bypasses.
- Enforce file-size, duration, download timeout, disk-space, and single-worker concurrency limits for both uploaded and fetched sources.
- Resolve application data with `platformdirs`; do not write beside the installed executable.
- Isolate the `yt-dlp` and Demucs child processes, cap runtime/resources where practical, sanitize diagnostics, and clean scratch files after every job.
- Never delete active jobs; make all user-data deletion explicit and retry files temporarily locked by Windows.
- Verify first-run model downloads, pin and deliberately update the `yt-dlp` dependency, and keep model/media paths separate.
- Sign public Windows installers to reduce SmartScreen and antivirus warnings.
- Add hosted authentication, ownership, quotas, and takedown handling only if remote multi-user access returns.
- Do not add “anti-detection,” fingerprint alteration, metadata spoofing, automated dispute, or source-access circumvention features.

## 9. Delivery phases

### Phase 0 — local foundation (implemented)

- Create the React + TypeScript + Vite application.
- Add the FastAPI local job service and filesystem store.
- Add linting, compilation, backend tests, setup docs, and Make targets.

### Phase 1A — attested file upload and separation (implemented)

- Implement local multipart uploads and rights confirmation.
- Run FFprobe validation and CPU-only Demucs separation.
- Add job polling, streamed Demucs pass progress and ETA, upload byte progress, selectable quality/accompaniment profiles, synchronized stem playback, volume controls, and instrumental WAV download.

**File-ingest checkpoint:** an attested audio-file source becomes playable vocal/instrumental stems.

### Phase 1B — attested YouTube URL ingest (implemented)

- Replace file-specific confirmation copy with the source-neutral, versioned attestation used by both source paths.
- Add a YouTube source choice and `POST /api/jobs/youtube` URL submission with an `ingesting` progress state.
- Invoke pinned `yt-dlp` with fixed options to resolve metadata and fetch the best available audio source, preferring audio-only formats, into the job directory.
- Persist the canonical URL, video ID, title, uploader/channel metadata, fetch timestamp, and attestation for the rights manifest.
- Apply download byte/time limits, run authoritative `ffprobe` validation, and hand the result to the existing CPU separation pipeline.
- Add mocked API/worker tests and packaged-runtime checks; do not make CI depend on a live third-party YouTube video.

**YouTube-ingest checkpoint:** an attested individual YouTube video URL becomes a bounded, provenance-recorded local source and enters the existing validated CPU separation pipeline. Live third-party media is not part of routine CI.

**Source-ingest MVP checkpoint:** a user-attested file upload or YouTube video URL becomes playable vocal/instrumental stems through the same validated separation pipeline.

### Phase 1C — selectable MelBand RoFormer separator (locally implemented, experimental)

Research, implementation, and routine local validation are complete. Kimberley Jensen MelBand RoFormer is available as an optional experimental high-quality engine because it was the strongest screened candidate with an explicit MIT checkpoint license and immutable source/checksum. Demucs remains the default faster/current engine and all existing profiles remain unchanged. BS-RoFormer Viperx and the screened MDX/MDX23C checkpoints were rejected for unclear weight licensing, insufficient quality improvement, or unacceptable CPU/RAM cost. The full record, implementation contract, and pending release gates are in `docs/SEPARATOR_UPGRADE.md`.

Implementation scope completed:

- Retain Demucs as the default clearly labeled faster/current engine and do not change `preserve`, `best`, or `standard` semantics.
- Implement the exact engine/model fields, adapter registry, narrow pinned CPU worker, verified atomic model cache, progress protocol, API validation, UI engine selector, and backward-compatible job restoration specified in the design document.
- Vendor only the required MIT RoFormer implementation. Do not add `audio-separator`, `diffq`, `librosa`, ONNX Runtime, CUDA, MPS, or DirectML.
- Preserve the stable `instrumental.wav`/`vocals.wav` contract, single-worker serialization, loopback/session security, and existing frozen Demucs/yt-dlp adapters.
- Store the optional 913106900-byte checkpoint under the platform model directory, verify SHA-256 `87201f4d31afb5bc79993230fc49446918425574db48c01c405e44f365c7559e`, and retain it until explicit deletion.
- Add mocked engine/API/cache/progress/worker tests and short self-created array tests. Routine CI must not download the checkpoint or run full inference.
- Run `npm test` and `npm run desktop:smoke`. Do not dispatch Windows packaging without explicit user approval.

The full permitted real-song/fixture A/B listening gate is complete. The user made same-song comparisons against all three Demucs profiles and preferred MelBand on every test; vocal residual was negligible with faint static still audible, instrument damage was effectively imperceptible, and karaoke usefulness was substantially better. Frozen Windows build/smoke and one target-PC real-song full inference are also complete: pushed commit `1c5bfb2db59868ec20bff02be0ba41c323041afc`, workflow run `29303479616`, passed 61 backend tests plus frontend checks, CPU-only Torch reinstall, PyInstaller onedir build, packaged authenticated startup/health and no-weight/no-network internal separator probe, Inno Setup installer, and artifact upload. The user installed that artifact smoothly and completed one roughly 3-minute user-attested YouTube-to-karaoke-use MelBand conversion (stem separation producing instrumental/vocal audio, not this MP4 renderer) on an older Windows laptop in about 30–40 minutes. Hardware, peak RAM/disk, setup-versus-cached timing, and exact elapsed time were not recorded, so this is compatibility evidence rather than a performance promise or minimum specification. Remaining release gates are packaged third-party-notice verification and a cached performance check covering the default 10-minute range with target hardware, elapsed time, peak RAM/disk, and an explicit acceptability decision. Broader clean-Windows release-matrix testing and signing remain separate work. MelBand is not production-ready until the remaining gates pass. The default supported source-duration range is 10 minutes; an operator can intentionally raise it with `KARAOKE_MAX_DURATION_SECONDS` when local policy and hardware permit.

**Separator-upgrade checkpoint:** users can choose the existing faster Demucs engine or the experimental MelBand RoFormer engine, with durable exact model metadata and the same preview/download outputs.

### Phase 1D — local karaoke video studio (working-tree complete; line-timed MVP)

- Search LRCLIB through a bounded fixed-host client and require explicit synchronized-result selection.
- Persist versioned lyric projects and canonical custom backgrounds through revision-checked compare-and-commit with rollback on handled persistence failure.
- Provide dirty/stale state, line timing/style edits, synchronized instrumental/vocal-guide preview, and reload-safe active-render polling.
- Serialize rendering with separation and atomically produce local 1920×1080/30fps H.264/AAC karaoke MP4s while preserving prior output on failure and cleaning partial/scratch artifacts.
- Use bundled provenance-recorded OFL fonts with tested Basic Latin, smart-punctuation fallback, and a bounded symbol set.
- Local acceptance is 124 backend tests, 8 Vitest tests plus oxlint/TypeScript/Vite build, offline npm install, desktop development smoke, an accepted one-second generated MP4 fixture, and fresh Sol backend/frontend `ACCEPT` gates. See `docs/KARAOKE_VIDEO.md` for exact evidence and caveats.
- Untimed alignment, user `.lrc` import, manual per-word/waveform editing, performance recording/mixing, rights manifests, and Windows renderer packaging remain future work.

**Karaoke-video checkpoint:** a completed local stem job can become an explicitly selected, line-edited, locally rendered karaoke MP4 without claiming lyric licensing or Windows package validation.

### Phase 2 — desktop runtime

- Serve the compiled Vite build from FastAPI.
- Add a pywebview launcher with random-port/session-token lifecycle handling.
- Introduce repository, media-path, and subprocess-command interfaces for Demucs and `yt-dlp`.
- Add `platformdirs`, bundled-tool resolution, explicit deletion, and disk-space admission checks.
- Handle active ingest/processing on window close and graceful child-process shutdown.

### Phase 3 — Windows package

- Maintain the PyInstaller onedir spec with CPU-only PyTorch, Demucs, optional MelBand runtime, `yt-dlp`, frontend assets, and bundled FFmpeg tools; do not bundle the MelBand checkpoint.
- The current GitHub Actions Windows build and packaged startup smoke test passed at commit `1c5bfb2db59868ec20bff02be0ba41c323041afc` in run `29303479616`, including the no-weight/no-network separator probe; the artifact includes the portable onedir app and installer while leaving the MelBand checkpoint unbundled.
- Create an Inno Setup per-user installer with WebView2 detection/bootstrap.
- Continue the broader clean Windows 10/11 x64 release matrix separately, including Unicode paths, Defender behavior, network failures, sleep/wake, and uninstall/upgrade; one target older Windows laptop has already completed a real packaged MelBand inference.
- Add Authenticode signing before broad public distribution.

### Phase 4 — lyrics and performance

- Add user `.lrc` import, untimed alignment, manual per-word timing, and waveform editing beyond the implemented line-timing controls.
- Build a performance-mode karaoke player beyond the implemented editor preview.
- Add microphone setup, latency calibration, and separate take recording.

### Phase 5 — mixing and export

- Add mix controls and worker-side audio rendering.
- Extend the implemented line-timed MP4 renderer with mixed-performance audio and additional release-approved export formats.
- Generate rights and attribution manifests, including source-specific provenance and the versioned user attestation.
- For YouTube sources, include the video ID and uploader/channel metadata without presenting those fields as proof of rights.
- Consider licensed catalog or platform upload integrations only after rights review; never promise claim-free uploads.

## 10. Testing strategy

- Unit-test FFprobe metadata handling, source-neutral attestation persistence, YouTube URL classification, and `yt-dlp` metadata mapping.
- Integration-test multipart uploads and mocked URL ingest, including status transitions, provenance, duration/size rejection, network/download failures, and local cleanup.
- Verify that both creation routes reject a missing attestation and that URL ingest cannot pass client-controlled extractor arguments or non-YouTube URLs.
- Keep short, self-created audio fixtures for deterministic processing smoke tests; do not rely on a third-party YouTube video in routine CI.
- Add browser tests for source switching, file upload, URL submission, polling, playback synchronization, and deletion.
- Test Chromium, Firefox, and Safari because media playback and future recording support differ.

## 11. Decisions recorded

1. macOS/Apple Silicon remains the development environment.
2. Windows 10/11 x64 is the primary packaged runtime and must be built/tested on Windows.
3. Single-user desktop application; no hosted authentication is required initially.
4. Instrumental WAV remains the stem export; Phase 1D adds local instrumental-audio karaoke MP4 rendering, while mixed-performance audio/video export remains deferred.
5. Supported source paths are an audio-file upload and an individual YouTube video fetched with `yt-dlp`; both require the same source-neutral rights attestation.
6. YouTube availability and successful `yt-dlp` ingest confer no rights and make no claim about permitted reuse.
7. React + TypeScript + Vite UI with Python/FastAPI, pywebview, JSON job metadata, and separate `yt-dlp`/Demucs child-process adapters.
8. CPU-only PyTorch permanently; no CUDA distribution.
9. PyInstaller onedir plus Inno Setup, built by GitHub Actions on Windows.
10. The optional Phase 1C implementation is the MIT-licensed Kimberley Jensen MelBand RoFormer checkpoint pinned in `docs/SEPARATOR_UPGRADE.md`; it remains experimental and Demucs remains the default faster/current choice.
11. Do not depend on the broad `audio-separator` package. Use a narrow pinned MIT worker so non-commercial and unnecessary runtime dependencies do not enter the desktop distribution.

## 12. Current implementation checkpoint

The file-upload and YouTube source vertical slices are implemented: both require the shared versioned attestation; YouTube jobs validate an individual HTTPS URL, resolve bounded provenance, preflight duration/size, fetch the best available audio source with fixed pinned `yt-dlp` options, retain sanitized diagnostics, and hand the source to the source-neutral FFprobe/selected-separator pipeline. Both paths include byte/status progress, reload-safe polling and active-job restoration, local result history, synchronized stem playback, level controls, explicit cleanup, and instrumental WAV download. The desktop runtime and Windows packaging adapters include the `yt-dlp` and generic separator worker entry points.

Phase 1C remains locally complete, frozen in architecture, experimental, and not production-ready. Its exact model/license record, historical 61-test Windows checkpoint, run `29303479616`, target-laptop stem-audio evidence, and pending packaged-notice/default-10-minute-performance gates remain recorded in `docs/SEPARATOR_UPGRADE.md` and must not be reinterpreted as Karaoke Video Studio evidence.

Phase 1D is complete in the local working tree as a line-timed MVP. The current whole-tree validation is 124 backend tests, 8 Vitest tests plus oxlint/TypeScript/Vite build, offline npm install, desktop development smoke, the accepted generated one-second H.264/AAC fixture, and final fresh Sol backend/frontend `ACCEPT` gates. Exact implementation behavior, fixture details, evidence limits, and deferred work are centralized in `docs/KARAOKE_VIDEO.md`. Windows renderer packaging and manual browser/accessibility validation remain outstanding.
