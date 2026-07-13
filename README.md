# Karaoke Box

A local karaoke-stem studio for source recordings you own or are allowed to use. Choose an audio-file upload or paste an individual YouTube video URL; Karaoke Box validates the local source, separates it into instrumental and vocal stems with Demucs on CPU, and lets you preview the mix and download the instrumental as WAV.

Removing vocals does **not** remove copyright or guarantee that a platform will accept an upload without a claim. Fetching media with `yt-dlp` is only a technical ingest step: it grants no license or other rights to download, adapt, or export that media.

> **Rights note:** YouTube availability and successful `yt-dlp` ingest do not establish authorization to download, adapt, or export a recording.

## Current scope

- React + TypeScript + Vite UI
- Local FastAPI service bound to `127.0.0.1`
- FFmpeg/ffprobe media validation
- CPU-only Demucs two-stem separation
- Natural, fine-tuned, and strong-removal separation profiles
- Local filesystem storage under `data/`
- MP3, WAV, M4A, FLAC, OGG, AAC, and Opus uploads
- Individual HTTPS YouTube video URL ingest through pinned `yt-dlp`
- 250 MB and 20-minute defaults
- Live upload/YouTube ingest progress, Demucs model progress, and estimated time remaining
- Reload-safe active-job restoration and local recent-results history
- Synchronized instrumental/vocal preview
- Instrumental WAV export
- pywebview desktop runtime and Windows x64 packaging pipeline
- CPU-only PyTorch/Demucs packaging; no CUDA build

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

The first separation downloads the configured Demucs model weights. After that model download, ingested source audio and generated stems remain on this computer. Keep the API terminal open until a job completes. Closing or reloading the browser does not stop a job; closing the API does.

### Desktop development mode

Build the frontend and open it in a native pywebview window:

```bash
npm run desktop
```

Run the desktop server/session startup check without opening a window:

```bash
npm run desktop:smoke
```

Desktop mode stores jobs and model caches in the operating system's application-data directory. The Windows installer is built by `.github/workflows/windows-desktop.yml`; see `packaging/windows/README.md`.

## Test

```bash
npm test
```

The test command runs the Python tests, frontend linter, TypeScript compiler, and Vite production build. It does not run a full Demucs model inference.

## Local data

Each job is stored in:

```text
data/jobs/<job-id>/
  job.json
  source.<extension>
  demucs.log
  yt-dlp.log        # YouTube jobs only
  instrumental.wav
  vocals.wav
```

Using **Process another source** keeps the completed result in **Recent tracks**. Results can be reopened, downloaded, or explicitly deleted there. You can delete all browser-development audio manually by stopping the API and removing `data/`.

The desktop app stores the equivalent structure under `%LOCALAPPDATA%\Karaoke Box` on Windows (and the platform application-data directory during macOS development). Desktop files do not expire automatically; they remain until explicitly deleted.

## Reloads and job persistence

The browser stores the selected job ID locally, while the API treats `data/jobs/*/job.json` as the source of truth. On reload, the UI restores that job and resumes one-second status polling. If browser storage was cleared, the UI can still discover an active job and list up to 100 recent jobs from the API.

Processing is independent of the browser, but it is currently hosted inside the local API process. Stopping or restarting the API interrupts Demucs; the interrupted job is marked failed on the next startup because Demucs cannot resume from a mid-song checkpoint. Completed results remain available until explicitly deleted.

## Configuration

Environment variables for the API:

| Variable | Default | Purpose |
| --- | --- | --- |
| `KARAOKE_DATA_DIR` | `<repo>/data` | Local job directory |
| `KARAOKE_MAX_UPLOAD_BYTES` | `262144000` | Upload limit in bytes |
| `KARAOKE_MAX_DURATION_SECONDS` | `1200` | Duration limit |
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

### Separation is slow

The MVP deliberately uses CPU processing. Runtime varies by model, track length, and machine; a full song can take several minutes. The Best Quality profile runs a bag of fine-tuned models and can take several times longer.

The UI combines Demucs's processed-audio counters across every model pass. ETA appears once the first audio segment completes and is recalculated from observed CPU speed. It can move up or down as later segments run. A first-time model download happens before measurable inference, so no reliable ETA is shown during that setup.

### The instrumental sounds muddy or watery

Try **Natural backing** first. It subtracts the predicted vocal from the original mix, preserving more instrument detail than summing generated instrument stems. It can leave faint vocal ambience or reverb.

Try **Best quality** when Natural backing is still poor. It uses the slower `htdemucs_ft` model. **Strong removal** is the original summed-stems method; it may suppress more vocal residue but can sound more processed.

Use the least-compressed source you are authorized to process. For file uploads, prefer WAV or FLAC over audio that has already been repeatedly encoded. The YouTube path fetches the best available audio source, preferring audio-only formats; the fallback may already be lossily encoded. No separation model can fully restore instruments that occupy the same time/frequency space as the vocal.

### Processing fails

The UI displays the final error. More detail is retained in the job's `demucs.log` file under `data/jobs/<job-id>/` in browser-development mode or the platform application-data directory in desktop mode.

## Repository layout

```text
backend/              FastAPI, Demucs processor, and desktop launcher
web/                  React + TypeScript + Vite frontend
packaging/windows/    PyInstaller and Inno Setup configuration
docs/PLAN.md          Product and implementation roadmap
docs/DESKTOP.md       Primary Windows packaging architecture
docs/DEPLOYMENT.md    Optional hosted architecture
data/                 Generated local files (gitignored)
```
