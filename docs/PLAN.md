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

The MVP has no authentication, database, Redis, Docker, cloud storage, or GPU worker.

## 5. Local job model

Each job has a UUID directory and a `job.json` file containing:

- original and internal source filenames,
- byte size and detected duration,
- status, progress, and user-facing message,
- error details when processing fails,
- creation and update timestamps.

Completed job directories also contain `instrumental.wav`, `vocals.wav`, and `demucs.log`. A database-backed project, lyrics, and recording model can be introduced when those features are implemented.

## 6. API outline

- `GET /api/health`
- `POST /api/jobs` — authorized multipart upload and queued separation
- `GET /api/jobs/:id` — status polling
- `GET /api/jobs/:id/assets/:stem` — inline preview or WAV download
- `DELETE /api/jobs/:id` — remove a completed/failed local job

The upload route enforces extension, size, duration, audio-stream, and rights-confirmation checks.

## 7. Processing pipeline

1. Enforce an extension allowlist and a 250 MB streaming upload limit.
2. Validate the file with `ffprobe`; require an audio stream and a duration no longer than 20 minutes.
3. Run the selected Demucs profile on CPU: subtractive `htdemucs`, subtractive fine-tuned `htdemucs_ft`, or summed-stem `htdemucs`.
4. Move full-quality `vocals.wav` and the selected accompaniment result into stable job assets.
5. Preview both stems in sync and offer the instrumental as a WAV download.
6. Retain a local Demucs log for troubleshooting.

Separation quality will vary. Backing vocals, reverb, and centered instruments may leak between stems. The UI should present this as an assistive tool, not perfect removal.

## 8. Security and abuse controls

- Bind both development services to loopback addresses.
- Validate all files server-side; never construct shell commands from user strings.
- Enforce file-size, duration, and single-job CPU concurrency limits.
- Keep generated data out of Git and provide explicit local deletion.
- Add authentication, isolation, quotas, audit events, retention rules, and takedown handling before any public deployment.
- Do not add “anti-detection,” fingerprint alteration, metadata spoofing, or automated dispute features.

## 9. Delivery phases

### Phase 0 — local foundation (implemented)

- Create the React + TypeScript + Vite application.
- Add the FastAPI local job service and filesystem store.
- Add linting, compilation, backend tests, setup docs, and Make targets.

### Phase 1 — authorized upload and separation (implemented)

- Implement local multipart uploads and rights confirmation.
- Run FFprobe validation and CPU-only Demucs separation.
- Add job polling, progress UI, selectable quality/accompaniment profiles, synchronized stem playback, volume controls, and instrumental WAV download.

**MVP checkpoint:** an authorized local audio file becomes playable vocal/instrumental stems.

### Phase 2 — lyrics and performance

- Add `.lrc` import, manual editing, and timestamp controls.
- Build the karaoke player.
- Add microphone setup, latency calibration, and separate take recording.

### Phase 3 — mixing and export

- Add mix controls and worker-side audio rendering.
- Add simple lyric-video rendering.
- Generate rights and attribution manifests.

### Phase 4 — optional deployment polish

- Add authentication, quotas, observability, retention controls, and takedown tooling if the app stops being local-only.
- Consider licensed catalog or platform upload integrations only after rights review; never promise claim-free uploads.

## 10. Testing strategy

- Unit-test FFprobe metadata handling and rights confirmation.
- Integration-test multipart uploads, status transitions, duration/size rejection, and local cleanup.
- Keep short, self-created audio fixtures for deterministic processing smoke tests.
- Add browser tests for upload, polling, playback synchronization, and deletion.
- Test Chromium, Firefox, and Safari because media playback and future recording support differ.

## 11. Decisions recorded

1. macOS/Apple Silicon CPU processing first.
2. Single-user and local-only.
3. Audio-only export.
4. User-uploaded source files only.
5. React + TypeScript + Vite frontend with a Python/FastAPI processing service.

## 12. Current implementation checkpoint

The first vertical slice is implemented: authorized local upload, FFprobe validation, selectable subtractive/fine-tuned/summed-stem CPU Demucs separation, polling, synchronized stem playback, level controls, local cleanup, and instrumental WAV download.

The next quality-sensitive checkpoint is to test several user-owned songs end to end, record separation runtime and memory use, and decide whether the default model offers acceptable CPU quality before implementing lyrics or microphone recording.
