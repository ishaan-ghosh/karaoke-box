# Selectable Separator Upgrade — Implementation Handoff

## Status

Phase 1C implementation is locally complete and routine validation passes. The implementation exposes **Kimberley Jensen MelBand RoFormer** as an optional experimental high-quality engine while all existing Demucs profiles remain unchanged and Demucs remains the default faster/current path.

The candidate was selected because it was the strongest CPU-capable option with an explicit model-weight license and a pinned, reproducible source. It is not production-ready or ready for Windows release until permitted-fixture listening tests, 3/10/20-minute CPU and peak-RAM measurements, frozen Windows x64 worker/package validation, a real permitted song on the target Windows PC, and packaged third-party-notice verification pass.

Do not replace Demucs, change the meaning of `preserve`, `best`, or `standard`, enable a GPU path, or bundle the model in the installer. Do not dispatch Windows packaging without explicit approval.

Verified local checks for this implementation are 54 backend tests, frontend lint/build, and desktop smoke. Routine checks do not download the checkpoint or run full model inference; the desktop smoke separator probe is no-weight/no-network.

## Recorded research

Benchmarks were run on 2026-07-14 with a self-created 30-second stereo WAV on an Apple M3 Max with 36 GiB RAM, Python 3.10.11, and CPU forced. Candidate runs used Torch 2.6.0 and `audio-separator` 0.44.3 only as an isolated research harness. Peak memory came from `/usr/bin/time -l`.

| Candidate | Published median quality | CPU inference | Model load | Peak RAM | Download | Decision |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Kimberley Jensen MelBand RoFormer | vocals SDR 12.60, SIR 25.58, SAR 13.44 | 32.2 s; 64.5 s/audio-minute | 17.6 s | 3.54 GiB | 870.8 MiB | Implement as experimental high-quality engine |
| BS-RoFormer Viperx 1297 | vocals SDR 11.77; instrumental SDR 16.45 | 39.6 s; 79.1 s/audio-minute | 2.9 s | 3.16 GiB | 609.7 MiB | Reject: checkpoint host has no explicit weight license |
| MDX23C InstVoc HQ | vocals SDR 10.56; instrumental SDR 15.83 | 169.6 s; 339.1 s/audio-minute | 0.5 s | 6.76 GiB | 427.3 MiB | Reject: too slow/heavy and checkpoint license unclear |
| MDX-Net Kim Vocal 2 ONNX | vocals SDR 10.18; instrumental SDR 15.36 | 22.2 s; 44.3 s/audio-minute | 20.5 s | 2.46 GiB | 63.7 MiB | Reject: not a convincing quality upgrade and checkpoint license unclear |
| MDX-Net Inst HQ 5 ONNX | instrumental SDR 15.30; vocals SDR 8.69 | Same lightweight family; not separately timed | — | expected near Kim Vocal 2 | 56.3 MiB | Reject: quality and license gates not met |

Current Demucs reference on the same fixture:

| Existing profile | Total CPU time | Peak RAM |
| --- | ---: | ---: |
| `standard` | 16.3 s | 1.86 GiB |
| `preserve` | 22.1 s | 1.85 GiB |
| `best` (`htdemucs_ft`, four passes) | 58.2 s | 2.45 GiB |

These timings are development-machine measurements, not Windows promises. The MelBand implementation keeps full-track result/counter arrays in memory, so a 10- or 20-minute benchmark is required before setting a minimum-RAM recommendation.

## Pinned model and license record

Application identifiers:

- Engine ID: `melband_roformer`
- Model ID: `kimberley_melband_roformer_v1`
- User-facing name: `High quality (MelBand RoFormer)`

Checkpoint:

- Repository: `https://huggingface.co/KimberleyJSN/melbandroformer`
- Immutable revision: `ac9b0614ab3cd7f77219e18ba494dfd93956c348`
- Download URL: `https://huggingface.co/KimberleyJSN/melbandroformer/resolve/ac9b0614ab3cd7f77219e18ba494dfd93956c348/MelBandRoformer.ckpt?download=true`
- Expected size: `913106900` bytes
- SHA-256: `87201f4d31afb5bc79993230fc49446918425574db48c01c405e44f365c7559e`
- Model-card license: MIT

Pinned configuration provenance:

- Upstream reference filename: `config_vocals_mel_band_roformer_kj.yaml`
- Immutable reference source: `https://raw.githubusercontent.com/ZFTurbo/Music-Source-Separation-Training/83d495dfc81b2ede9bc62f4209619f8bdfd14995/configs/KimberleyJensen/config_vocals_mel_band_roformer_kj.yaml`
- Reference SHA-256: `f63f38eb1e6e40a7db0dade714a5ae257555dd8748f4e774eae8679275a81926`
- Research-harness inference config: `https://github.com/nomadkaraoke/python-audio-separator/releases/download/model-configs/vocals_mel_band_roformer.yaml`
- Research-harness config SHA-256: `b958b29c8f7195f0d86bee6759a33980db675c4ecaf2fcaa80fa125828e6cd38`
- Runtime parameters proven by the benchmark: stereo, 44.1 kHz, one target vocal stem, model dimension 384, depth 6, 60 mel bands, STFT 2048/hop 441, inference `dim_t=1101`, and an 8-second/352800-sample step.

Check both small configuration artifacts into `backend/app/separators/models/` with source/license metadata. Use the reference file for model architecture provenance and the research-harness file for the exact benchmark inference settings; do not fetch either at runtime.

Runtime source selected for the narrow worker:

- Proven implementation: `python-audio-separator` 0.44.3, commit `ee1fcee90963919fe13a146fe71f57f29c2e9bbc`, MIT.
- Vendor only the required RoFormer implementation (`attend.py` and `mel_band_roformer.py`) with provenance comments and the upstream MIT license.
- Replace the single `librosa.filters.mel` dependency with a small fixed Slaney mel-filter helper for the pinned 44.1 kHz/2048 FFT configuration. Keep all other vendored model behavior aligned with the proven implementation.
- Add only direct permissive dependencies needed by those files: `beartype>=0.18.5,<0.19`, `einops>=0.8,<0.9`, and `rotary-embedding-torch>=0.6.5,<0.7`.

Do **not** add `audio-separator`, `diffq`, `diffq-fixed`, `librosa`, ONNX Runtime, CUDA, DirectML, or MPS support. `audio-separator` was useful for research but is unsuitable as an application dependency: it forces a Torch/NumPy migration, includes CC BY-NC `diffq` dependencies, and pulls broad native/runtime code not needed for this model.

## Exact domain and persistence design

### Selection fields

Keep `quality: "preserve" | "best" | "standard"` for compatibility. Add:

```text
separator_engine: "demucs" | "melband_roformer"
separator_model: string
```

New jobs must always persist both fields.

- Demucs jobs persist `separator_engine="demucs"` and the profile's resolved model (`htdemucs`, `htdemucs_ft`, or configured override) in `separator_model`.
- New high-quality jobs persist `separator_engine="melband_roformer"` and `separator_model="kimberley_melband_roformer_v1"`.
- Existing `job.json` files without the new fields load as Demucs. A Pydantic `model_validator(mode="before")` must derive the model from the stored `quality`.
- For the new engine, only `quality="preserve"` is valid. It represents the existing residual/subtractive accompaniment contract. Reject `best` or `standard` combined with `melband_roformer` rather than silently ignoring them.
- API request schemas default `separator_engine` to `demucs`, preserving old clients and the current default behavior.

### Job status

Add `preparing` to `JobStatus` and `ACTIVE_STATUSES` for model verification/download and RoFormer input preparation. Keep progress stage-local: model download may reach 100%, then separation starts again at 0% under `separating`.

### Adapter boundary

The implementation uses `backend/app/separators/` with this responsibility split:

```text
base.py          shared types/protocol, streamed-process helper, progress/ETA snapshot
catalog.py       engine/model IDs, selection validation, user-neutral metadata
registry.py      maps engine ID to one adapter
model_cache.py   atomic pinned download and SHA-256 verification
worker.py        private CPU-only RoFormer subprocess entry point
demucs.py        current Demucs command/progress/output behavior moved intact
melband.py       model preparation, input conversion, worker command, progress/output mapping
vendor/          pinned MIT RoFormer model code, fixed mel helper, license/provenance
models/          checked-in pinned YAML configuration and license metadata
```

`backend/app/processor.py` remains the source-neutral orchestrator:

1. Verify ffmpeg/ffprobe and probe the local source.
2. Resolve one adapter through the registry from persisted engine/model/quality.
3. Ask the adapter to prepare required model/input state.
4. Ask the adapter to run separation with streamed progress.
5. Receive a `SeparatedStems(instrumental: Path, vocals: Path)` result.
6. Move those files to stable `instrumental.wav` and `vocals.wav`, clean successful scratch output, and complete the job.

Do not put `if engine == ...` branches in API routes or `JobManager`. The registry and adapters own engine-specific behavior.

Move current Demucs behavior without semantic changes:

- Preserve `DemucsProgressTracker` behavior, including bag pass aggregation and ETA start at the first 0% inference line.
- Preserve `--device cpu`, `--jobs 1`, profile model/method, `minus_vocals.wav` versus `no_vocals.wav`, `demucs.log`, and frozen `--internal-demucs` dispatch.
- Existing processor tests may import compatibility re-exports, but new engine tests should target adapter modules directly.

## Exact model-cache behavior

The implementation adds `MODELS_DIR` to configuration:

- Browser development default: `<KARAOKE_DATA_DIR>/models`
- Desktop: the existing platform model directory; set `KARAOKE_MODEL_DIR` in `_configure_desktop_environment`.

The checkpoint path is:

```text
<models>/melband-roformer/kimberley_melband_roformer_v1/MelBandRoformer.ckpt
```

Rules:

1. If the final file exists, stream SHA-256 verification before every use. Reuse it only when size and hash match.
2. If invalid, remove it and download again.
3. Download to a sibling `.part` file using the immutable URL.
4. Enforce the expected byte count and compute SHA-256 while streaming.
5. Throttle job JSON writes similarly to inference progress.
6. On success, atomically replace the final path.
7. On failure, delete the partial file and raise a sanitized `ProcessingError`.
8. Never automatically delete a valid model.
9. Do not delegate downloading to Torch, Hugging Face Hub, or `audio-separator`.

## Exact RoFormer worker behavior

Development command:

```text
python -u -m app.separators.worker ...
```

Frozen command:

```text
KaraokeBox.exe --internal-separator ...
```

`backend/app/runtime.py` provides `separator_worker_command()` and `separator_worker_cwd()`, and `backend/app/desktop.py` dispatches `--internal-separator`. Preserve the existing private Demucs and yt-dlp commands. Development keeps `python -u -m app.separators.worker`; because the documented API starts from the repository root with Uvicorn `--app-dir backend`, the runtime supplies `<repo>/backend` as the child cwd so `app` is importable. Frozen mode uses `KaraokeBox.exe --internal-separator`.

The worker must:

- Set `CUDA_VISIBLE_DEVICES=""` before importing Torch and always use `torch.device("cpu")`.
- Never select MPS, DirectML, or CUDA.
- Load the checkpoint with `map_location="cpu"` and `weights_only=True` where supported.
- Accept only fixed server-produced arguments: model path, normalized input path, output directory, and model ID.
- Read a server-created raw stereo float32/44.1 kHz input file.
- Scale input only when its absolute peak exceeds 1.0, so already valid float audio is unchanged.
- Process 485100-sample chunks with a 352800-sample step and Hamming overlap-add; handle short/final chunks through explicit padding and trimming.
- Predict the vocal stem, then compute `instrumental = normalized_mix - vocals`.
- Scale each output independently only when its absolute peak exceeds 1.0.
- Write stereo `pcm_f32le` WAV files in scratch output.
- Emit line-oriented records prefixed with `KARAOKE_PROGRESS ` containing JSON with completed/total chunks. Do not rely on parsing generic tqdm formatting.
- Write ordinary diagnostics to merged stdout/stderr so the parent can retain `melband-roformer.log`.

The MelBand adapter prepares input with bundled FFmpeg:

```text
ffmpeg -v error -y -i <source> -vn -ac 2 -ar 44100 -f f32le <scratch>/input.f32le
```

FFmpeg conversion may use `subprocess.run`; model inference must use `Popen` and stream output line by line.

## API and frontend contract

Both creation routes accept `separator_engine`, defaulting to `demucs`.

Frontend types:

```text
SeparatorEngine = "demucs" | "melband_roformer"
SeparationQuality = "preserve" | "best" | "standard"
```

UI behavior:

1. Add an engine selector before the existing profile selector.
2. Keep `Demucs — current/faster` selected by default.
3. The Demucs card shows the existing three profile choices with unchanged labels and copy.
4. Add `High quality — MelBand RoFormer` with `~871 MB first download`, `Experimental`, and CPU-only wording.
5. When MelBand is selected, hide the three Demucs profile cards and submit `quality="preserve"` plus `separator_engine="melband_roformer"`.
6. Progress includes a `Prepare model` stage for `preparing` and distinguishes download verification/setup from inference.
7. History and active progress display the persisted engine/model, with graceful fallback for old jobs.
8. Reset returns to Demucs/`preserve`, preserving current default behavior.
9. Do not claim perfect removal or promise a fixed runtime on Windows.

## Packaging requirements

- Do not bundle the 870.8 MiB checkpoint.
- The packaging spec includes hidden imports/data only for the narrow vendored worker and its permissive dependencies.
- The spec includes the pinned YAML, upstream MIT license, and provenance notice; it does not include the checkpoint.
- Keep CPU-only Torch enforcement in the Windows workflow. Do not change to a CUDA index.
- The packaged `--internal-separator --probe` mode imports the worker, validates the pinned configuration/catalog, confirms CPU mode, and exits without a model file or inference.
- Desktop smoke exercises that probe without network access, weights, or inference.
- Do not dispatch the Windows workflow until the user explicitly asks.

## Required tests

Routine tests must use tiny byte fixtures, fake processes/models, and mocked downloads. They must not download the checkpoint or run full RoFormer inference.

Backend coverage:

- Existing Demucs command/output/progress tests remain green.
- Selection validation and exact persisted engine/model fields.
- Loading old `job.json` without new fields.
- Atomic cache success, cached verification, wrong size/hash, interrupted download cleanup, and progress throttling.
- Worker command selection in development and frozen modes.
- RoFormer progress protocol parsing and ETA.
- Fake-model chunk overlap/padding and residual stem mapping using short self-created arrays.
- Stable final `instrumental.wav`/`vocals.wav` paths.
- API defaults to Demucs and rejects invalid MelBand/profile combinations.
- Health/probe behavior without model weights.

Frontend validation:

- Types compile and lint.
- Demucs remains default.
- Engine switching shows/hides the correct options and submits the exact fields.
- Restored/history jobs show engine/model labels.
- `preparing` renders as an active stage.

Required final local commands:

```bash
npm test
npm run desktop:smoke
```

A cached manual inference smoke may be run separately and documented, but it is not part of `npm test`. Research artifacts may still exist under `/tmp/kb-separator-bench`; treat them as disposable and never add them to the repository.

## Directed sub-agent execution

Implementation/writer workers use the installed `pi-subagents` package with **GPT-5.6 Luna** (`openai-codex/gpt-5.6-luna`) in **xhigh** reasoning mode. Fresh-context review/reviewer agents use **GPT-5.6 Sol** (`openai-codex/gpt-5.6-sol`) in **xhigh** reasoning mode. Configure `subagents.agentOverrides.worker` and `subagents.agentOverrides.reviewer` with those model/reasoning pairs in user or project settings. The packaged defaults use `high`.

Launch each implementation milestone as an async Luna `worker` through the `subagent` tool; do not launch nested `pi` subprocesses. Use `wait` when the coordinator has no independent inspection or validation preparation left. Run writer agents sequentially because they share one working tree. Use a fresh-context, read-only Sol reviewer for integration review; only Luna workers implement changes. Do not ask children to redesign or broadly plan the feature. Use the bounded prompts in `docs/SEPARATOR_SUBAGENT_PROMPTS.md`; the coordinator must inspect each diff and run its focused checks before starting the next worker.

Worker sequence:

1. **Backend adapter and persistence worker** — create the adapter/catalog/registry shape, move Demucs intact, add persisted fields/status/API validation, and update focused tests. It must not implement RoFormer math or touch frontend/packaging.
2. **RoFormer runtime and cache worker** — implement only the pinned cache, vendored runtime, worker protocol, MelBand adapter, runtime command, and focused tests against the interfaces from worker 1. It must not redesign the API or touch frontend.
3. **Frontend worker** — implement only engine selection, job types, progress/history labels, and styling against the established API. It must not change backend architecture.
4. **Packaging and integration worker** — update desktop internal dispatch, PyInstaller data/hidden imports, probe smoke, dependency lock, and cross-layer tests. It must not dispatch CI or alter model behavior.
5. **Fresh-context Sol reviewer** — review the complete diff for CPU-only enforcement, adapter boundaries, backward compatibility, model verification, streamed progress, security, test gaps, and accidental dependency/license regressions. It reports concrete fixes; only a Luna worker applies approved implementation fixes.

All workers must preserve the pre-existing documentation and implementation edits, must not commit or push, and must not dispatch Windows packaging.

## Release gates still pending

The engine remains experimental and is not production-ready. Before calling it production-ready:

1. Complete A/B listening on permitted fixtures covering reverb, backing vocals, centered guitar/sax/synth, quiet vocals, dense mixes, lossless uploads, and compressed YouTube ingest.
2. Record perceived vocal residue, instrument damage, and preference against all three Demucs profiles.
3. Benchmark 3-, 10-, and 20-minute fixtures for CPU time and peak RAM.
4. Build and smoke the frozen separator worker/package on Windows x64.
5. Manually process a real permitted song on the target Windows PC.
6. Confirm third-party notices are present in the packaged artifact.
