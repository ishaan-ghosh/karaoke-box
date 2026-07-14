# Karaoke Box

A local karaoke-stem studio for source recordings you own or are allowed to use. Choose an audio-file upload or paste an individual YouTube video URL; Karaoke Box validates the local source, separates it into instrumental and vocal stems with the selected CPU engine, and lets you preview the mix and download the instrumental as WAV.

Removing vocals does **not** remove copyright or guarantee that a platform will accept an upload without a claim. Fetching media with `yt-dlp` is only a technical ingest step: it grants no license or other rights to download, adapt, or export that media.

> **Rights note:** YouTube availability and successful `yt-dlp` ingest do not establish authorization to download, adapt, or export a recording.

## Current scope

- React + TypeScript + Vite UI
- Local FastAPI service bound to `127.0.0.1`
- FFmpeg/ffprobe media validation
- CPU-only two-stem separation with Demucs (default faster/current engine) or optional experimental MelBand RoFormer
- Natural, fine-tuned, and strong-removal Demucs separation profiles
- Local filesystem storage under `data/`
- MP3, WAV, M4A, FLAC, OGG, AAC, and Opus uploads
- Individual HTTPS YouTube video URL ingest through pinned `yt-dlp`
- 250 MB and a 10-minute default source-duration limit; an intentional `KARAOKE_MAX_DURATION_SECONDS` operator override can raise it
- Live upload/YouTube ingest progress, Demucs model progress, and estimated time remaining
- Reload-safe active-job restoration and local recent-results history
- Synchronized instrumental/vocal preview
- Instrumental WAV export
- pywebview desktop runtime and Windows x64 packaging pipeline
- CPU-only PyTorch/Demucs packaging plus the optional MelBand runtime; no CUDA build

## Phase 1C separator status

The selectable Phase 1C implementation is locally complete but remains an **experimental, not production-ready** feature. **Demucs** remains the default faster/current engine with all three existing profiles unchanged. **Kimberley Jensen MelBand RoFormer** is an optional high-quality CPU engine selected by the user. Candidate research found it was the strongest screened option with an explicit MIT checkpoint license and reproducible immutable source. See `docs/SEPARATOR_UPGRADE.md` for measured CPU/RAM results, rejected alternatives, pinned hashes, implementation details, and release gates.

All separator paths remain permanently CPU-only. On first use, the roughly 871 MiB optional checkpoint downloads into the local model cache and is verified against its pinned size and SHA-256; it remains until explicit deletion. The checkpoint is not bundled in the installer. Routine tests mock the engine and downloader rather than fetching weights or performing full inference. The user completed full permitted real-song/fixture A/B listening with same-song comparisons against all three Demucs profiles: MelBand was preferred on every test, vocal residual was negligible with faint static still audible, instrument damage was effectively imperceptible, and karaoke usefulness was substantially better. Release remains blocked pending frozen Windows x64 worker/package validation and performance checks, real permitted-song processing on the target Windows PC, and packaged third-party-notice verification. The default supported source-duration range is 10 minutes; an operator can intentionally raise it with `KARAOKE_MAX_DURATION_SECONDS` when local policy and hardware permit.

## Source inputs and rights

The source path accepts MP3, WAV, M4A, FLAC, OGG, AAC, and Opus uploads. The YouTube path accepts one individual HTTPS video URL, fetches the best available audio source with pinned `yt-dlp` (preferring audio-only formats), validates the fetched file with `ffprobe`, and then uses the same CPU separation pipeline as an upload. Playlist/channel URLs without a specific video, live streams, arbitrary hosts, cookies, and client-supplied `yt-dlp` options are rejected. If a watch URL contains both `v=` and queue parameters such as `list=RD...`, Karaoke Box processes only the explicit video.

Both paths require this source-neutral attestation before bytes are stored or a URL fetch begins:

> I confirm that I own this source recording or am authorized to use it, including downloading it when I provide a URL, and that I am permitted to process and export it.

The server stores the attestation version, text, and confirmation timestamp. This records the user’s representation; it does not grant rights or replace a license.

The job metadata records YouTube provenance for the future `rights-manifest.json`: canonical URL, video ID, title, uploader/channel name and ID when available, extractor, and fetch timestamp. Those metadata identify the source but are not proof of rights.

## Prerequisites

- Node.js 20.19+ or 22.12+
- Python 3.10–3.12
- [`uv`](https://docs.astral.sh/uv/)
- FFmpeg and ffprobe

On macOS:

```bash
brew install ffmpeg uv
```

## Install

```bash
npm run setup
```

This installs the frontend packages and creates `backend/.venv`. PyTorch and Demucs are large dependencies, so the first installation can take a while.

## Run

Open two terminals from the repository root.

Terminal 1:

```bash
npm run api
```

Terminal 2:

```bash
npm run web
```

Then open <http://127.0.0.1:5173>.

The first separation with a selected engine downloads its configured model weights. In browser development, model files default to `<KARAOKE_DATA_DIR>/models`; desktop mode sets `KARAOKE_MODEL_DIR` to the platform application model directory. After a model download, ingested source audio, generated stems, and valid model weights remain on this computer. Keep the API terminal open until a job completes. Closing or reloading the browser does not stop a job; closing the API does.

### Desktop development mode

Build the frontend and open it in a native pywebview window:

```bash
npm run desktop
```

Run the desktop server/session startup check without opening a window:

```bash
npm run desktop:smoke
```

Desktop mode stores jobs and model caches in the operating system's application-data directory and sets `KARAOKE_MODEL_DIR` to its `models` directory. The Windows installer is built by `.github/workflows/windows-desktop.yml`; see `packaging/windows/README.md`. The desktop smoke test also launches the separator `--probe` without network access, weights, or inference.

## Test

```bash
npm test
```

The test command runs the Python tests, frontend linter, TypeScript compiler, and Vite production build. It does not run a full separator-model inference.

## Local data

Each job is stored in:

```text
data/jobs/<job-id>/
  job.json
  source.<extension>
  demucs.log                 # Demucs jobs
  melband-roformer.log       # MelBand jobs
  yt-dlp.log                 # YouTube jobs only
  instrumental.wav
  vocals.wav

data/models/melband-roformer/kimberley_melband_roformer_v1/
  MelBandRoformer.ckpt       # valid pinned checkpoint, never auto-deleted
```

Using **Process another source** keeps the completed result in **Recent tracks**. Results can be reopened, downloaded, or explicitly deleted there. You can delete all browser-development audio manually by stopping the API and removing `data/`.

The desktop app stores the equivalent structure under `%LOCALAPPDATA%\Karaoke Box` on Windows (and the platform application-data directory during macOS development). Desktop files do not expire automatically; they remain until explicitly deleted.

## Reloads and job persistence

The browser stores the selected job ID locally, while the API treats `data/jobs/*/job.json` as the source of truth. On reload, the UI restores that job and resumes one-second status polling. If browser storage was cleared, the UI can still discover an active job and list up to 100 recent jobs from the API.

Processing is independent of the browser, but it is currently hosted inside the local API process. Stopping or restarting the API interrupts the selected separator; the interrupted job is marked failed on the next startup because separator inference cannot resume from a mid-song checkpoint. Completed results remain available until explicitly deleted.

## Configuration

Environment variables for the API:

| Variable | Default | Purpose |
| --- | --- | --- |
| `KARAOKE_DATA_DIR` | `<repo>/data` | Local job directory |
| `KARAOKE_MODEL_DIR` | `<KARAOKE_DATA_DIR>/models` in browser mode; platform model directory in desktop mode | Verified separator model cache |
| `KARAOKE_MAX_UPLOAD_BYTES` | `262144000` | Upload limit in bytes |
| `KARAOKE_MAX_DURATION_SECONDS` | `600` | Default 10-minute duration limit; intentionally raise for an operator-approved local policy |
| `KARAOKE_DEMUCS_MODEL` | `htdemucs` | Model for Natural and Strong Removal profiles |
| `KARAOKE_DEMUCS_BEST_MODEL` | `htdemucs_ft` | Model for the Best Quality profile |
| `KARAOKE_CORS_ORIGINS` | local Vite origins | Comma-separated allowed frontend origins |
| `KARAOKE_YOUTUBE_METADATA_TIMEOUT_SECONDS` | `60` | Metadata lookup timeout |
| `KARAOKE_YOUTUBE_DOWNLOAD_TIMEOUT_SECONDS` | `900` | YouTube audio download timeout |
| `KARAOKE_YOUTUBE_SOCKET_TIMEOUT_SECONDS` | `30` | yt-dlp network socket timeout |

The Vite build accepts `VITE_API_BASE_URL`. Leave it empty for the local proxy and desktop app; set it only when a separately hosted API is used. See `web/.env.example`.

Example:

```bash
KARAOKE_DEMUCS_MODEL=htdemucs npm run api
```

## Troubleshooting

### “The local API is offline”

Run `npm run api` and confirm <http://127.0.0.1:8000/api/health> responds.

### Missing Demucs or yt-dlp

Run `npm run setup`, then start the API through `npm run api` so it uses `backend/.venv` rather than a global Python installation.

### MelBand model or worker problems

MelBand uses the pinned `kimberley_melband_roformer_v1` checkpoint under `KARAOKE_MODEL_DIR/melband-roformer/`. A final checkpoint is reused only after size and SHA-256 verification; valid weights are not automatically deleted. If separation fails, inspect the job's `melband-roformer.log` for sanitized child diagnostics. The model worker is launched with `python -u -m app.separators.worker`; when the API is started from the repository root with Uvicorn `--app-dir backend`, the runtime supplies `<repo>/backend` as the child working directory because Uvicorn's import path does not propagate to child interpreters. Frozen desktop mode uses `KaraokeBox.exe --internal-separator`.

To run the no-weight/no-network worker probe directly, use:

```bash
(cd backend && uv run --project backend python -u -m app.separators.worker --probe)
```

The same probe runs as part of `npm run desktop:smoke`. The probe validates the pinned runtime/configuration and CPU mode without downloading the checkpoint or running inference.

### Separation is slow

The MVP deliberately uses CPU processing. Runtime varies by engine, model, track length, and machine; a full song can take several minutes. Demucs Best Quality runs a bag of fine-tuned models and can take several times longer. The default supported source-duration range is 10 minutes, while an operator can intentionally raise it with `KARAOKE_MAX_DURATION_SECONDS`. MelBand is experimental and still requires frozen Windows, target-PC, and packaged-notice gates. In completed full-matrix same-song A/B testing against all three Demucs profiles, the user preferred MelBand on every test; vocal residual was negligible with faint static still audible, instrument damage was effectively imperceptible, and karaoke usefulness was substantially better.

The UI combines Demucs's processed-audio counters across every model pass. ETA appears once the first audio segment completes and is recalculated from observed CPU speed. It can move up or down as later segments run. A first-time model download happens before measurable inference, so no reliable ETA is shown during that setup.

### The instrumental sounds muddy or watery

Try **Natural backing** first. It subtracts the predicted vocal from the original mix, preserving more instrument detail than summing generated instrument stems. It can leave faint vocal ambience or reverb.

Try **Best quality** when Natural backing is still poor. It uses the slower `htdemucs_ft` model. **Strong removal** is the original summed-stems method; it may suppress more vocal residue but can sound more processed.

Use the least-compressed source you are authorized to process. For file uploads, prefer WAV or FLAC over audio that has already been repeatedly encoded. The YouTube path fetches the best available audio source, preferring audio-only formats; the fallback may already be lossily encoded. No separation model can fully restore instruments that occupy the same time/frequency space as the vocal.

### Processing fails

The UI displays the final error. Demucs details are retained in `demucs.log`; MelBand details are retained in `melband-roformer.log`; YouTube diagnostics are retained in `yt-dlp.log`. These files are under `data/jobs/<job-id>/` in browser-development mode or the platform application-data directory in desktop mode. A model-cache verification or download error is sanitized before it reaches the UI.

## Repository layout

```text
backend/              FastAPI, Demucs processor, and desktop launcher
web/                  React + TypeScript + Vite frontend
packaging/windows/    PyInstaller and Inno Setup configuration
docs/PLAN.md               Product and implementation roadmap
docs/DESKTOP.md            Primary Windows packaging architecture
docs/SEPARATOR_UPGRADE.md          Current separator implementation design and research
docs/SEPARATOR_SUBAGENT_PROMPTS.md  Directed implementation worker prompts
docs/DEPLOYMENT.md                 Optional hosted architecture
data/                 Generated local files (gitignored)
```
