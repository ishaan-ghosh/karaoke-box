# Karaoke Box

A local karaoke-stem studio for audio you own or are allowed to adapt. Upload a music file in the browser, separate it into instrumental and vocal stems with Demucs on CPU, preview the mix, and download the instrumental as WAV.

Removing vocals does **not** remove the underlying composition's copyright or guarantee that a platform will accept an upload without a claim.

## Current scope

- React + TypeScript + Vite UI
- Local FastAPI service bound to `127.0.0.1`
- FFmpeg/ffprobe media validation
- CPU-only Demucs two-stem separation
- Natural, fine-tuned, and strong-removal separation profiles
- Local filesystem storage under `data/`
- MP3, WAV, M4A, FLAC, OGG, AAC, and Opus uploads
- 250 MB and 20-minute defaults
- Synchronized instrumental/vocal preview
- Instrumental WAV export

There is no YouTube integration, cloud upload, account, database, or telemetry.

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

The first separation downloads the configured Demucs model weights. After that model download, uploaded audio and generated stems remain on this computer. Keep the API terminal open until a job completes.

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
  instrumental.wav
  vocals.wav
```

Using **Process another track** deletes the completed or failed job currently shown. You can delete all local audio manually by stopping the API and removing `data/`.

## Configuration

Environment variables for the API:

| Variable | Default | Purpose |
| --- | --- | --- |
| `KARAOKE_DATA_DIR` | `<repo>/data` | Local job directory |
| `KARAOKE_MAX_UPLOAD_BYTES` | `262144000` | Upload limit in bytes |
| `KARAOKE_MAX_DURATION_SECONDS` | `1200` | Duration limit |
| `KARAOKE_DEMUCS_MODEL` | `htdemucs` | Model for Natural and Strong Removal profiles |
| `KARAOKE_DEMUCS_BEST_MODEL` | `htdemucs_ft` | Model for the Best Quality profile |

Example:

```bash
KARAOKE_DEMUCS_MODEL=htdemucs npm run api
```

## Troubleshooting

### “The local API is offline”

Run `npm run api` and confirm <http://127.0.0.1:8000/api/health> responds.

### Missing Demucs

Run `npm run setup`, then start the API through `npm run api` so it uses `backend/.venv` rather than a global Python installation.

### Separation is slow

The MVP deliberately uses CPU processing. Runtime varies by model, track length, and machine; a full song can take several minutes. The Best Quality profile runs a bag of fine-tuned models and can take several times longer. Progress stays on the separation stage while Demucs runs.

### The instrumental sounds muddy or watery

Try **Natural backing** first. It subtracts the predicted vocal from the original mix, preserving more instrument detail than summing generated instrument stems. It can leave faint vocal ambience or reverb.

Try **Best quality** when Natural backing is still poor. It uses the slower `htdemucs_ft` model. **Strong removal** is the original summed-stems method; it may suppress more vocal residue but can sound more processed.

Use the least-compressed authorized source available—prefer WAV or FLAC over an audio file that has already been repeatedly encoded. No separation model can fully restore instruments that occupy the same time/frequency space as the vocal.

### Processing fails

The UI displays the final error. More detail is retained in the job's `demucs.log` file under `data/jobs/<job-id>/`.

## Repository layout

```text
backend/        FastAPI job service and Demucs processor
web/            React + TypeScript + Vite frontend
docs/PLAN.md    Product and implementation roadmap
data/           Generated local files (gitignored)
```
