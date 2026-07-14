# Phase 1C — Exact Sub-Agent Prompts

Use this file with `docs/SEPARATOR_UPGRADE.md`. These are implementation tasks, not invitations to redesign the feature.

## Invocation rules

Use the installed `pi-subagents` package directly. Do not launch nested `pi` subprocesses.

The packaged `worker` and `reviewer` currently default to `thinking: high`. Implementation/writer workers use Luna; review/reviewer agents use Sol. Before implementation or review, add equivalent user- or project-scope overrides:

```json
{
  "subagents": {
    "agentOverrides": {
      "worker": {
        "model": "openai-codex/gpt-5.6-luna",
        "thinking": "xhigh"
      },
      "reviewer": {
        "model": "openai-codex/gpt-5.6-sol",
        "thinking": "xhigh"
      }
    }
  }
}
```

Run one writer at a time because all workers share the active working tree. For each of workers 1–4, pass the exact task block below to the parent-only tool:

```typescript
subagent({
  agent: "worker",
  task: "<exact worker prompt below>",
  model: "openai-codex/gpt-5.6-luna",
  async: true,
  acceptance: "checked"
})
```

Continue coordinator-only inspection or validation preparation while the child runs; do not edit the same files. When no independent work remains, call `wait({ id: "<run-id>" })`. Before the next worker, inspect `git status`, the completed worker's diff, and its focused test evidence.

Run reviewer 5 as a fresh-context read-only Sol review:

```typescript
subagent({
  agent: "reviewer",
  task: "<exact reviewer prompt below>",
  model: "openai-codex/gpt-5.6-sol",
  context: "fresh",
  async: true,
  output: false
})
```

Every child must preserve all pre-existing user changes, especially handoff documents; must not commit or push; must not download the 870.8 MiB checkpoint; must not dispatch CI or Windows packaging; and must not add CUDA, MPS, or DirectML. Children must not launch their own sub-agents.

## Worker 1 — backend adapter and persistence

```text
Implement only the Phase 1C backend adapter and persistence foundation. Read AGENTS.md and docs/SEPARATOR_UPGRADE.md completely first. Follow that specification exactly; do not propose a different architecture.

Allowed production files: backend/app/processor.py, backend/app/profiles.py, backend/app/jobs.py, backend/app/main.py, and new backend/app/separators/{__init__.py,base.py,catalog.py,registry.py,demucs.py}. Allowed tests: backend/tests/test_processor.py, backend/tests/test_api.py, and new focused separator tests. Do not touch frontend, desktop.py, runtime.py, dependencies, packaging, workflows, or documentation.

Implement exactly:
1. Add engine IDs demucs and melband_roformer, model ID kimberley_melband_roformer_v1, a resolved selection dataclass, and validation that MelBand only pairs with quality=preserve.
2. Add separator_engine and separator_model to Job. New jobs always persist exact values. Add a Pydantic model_validator(mode="before") so old JSON lacking the fields loads as Demucs and derives the resolved Demucs model from quality.
3. Add preparing to JobStatus and ACTIVE_STATUSES.
4. Add separator_engine with default demucs to both upload and YouTube creation schemas. Resolve/validate before JobStore.create. Do not put model-specific processing branches in routes or JobManager.
5. Create a separator adapter protocol/result type and registry. Move the current Demucs command, progress tracker, output mapping, Popen stream, ETA behavior, and demucs.log handling into DemucsAdapter without changing preserve/best/standard behavior.
6. Keep processor.py source-neutral: common tool check/probe, adapter lookup/call, stable finalization to instrumental.wav and vocals.wav, and successful scratch cleanup. JobManager passes persisted engine/model/quality.
7. Preserve compatibility exports if old tests import DemucsProgressTracker from processor.
8. Add tests for old-job migration, exact fields, API default, invalid MelBand/profile combinations, Demucs command/output parity, and preparing as active. No downloads or real inference.

The MelBand adapter itself belongs to worker 2. A registry placeholder or explicit unavailable error is acceptable only until worker 2 fills it; do not invent model behavior.

Run backend pytest and git diff --check. End with exact files changed, tests run/results, and any concrete blocker. Do not commit.
```

## Worker 2 — pinned runtime and model cache

```text
Implement only the pinned MelBand RoFormer runtime/cache against worker 1's established interfaces. Read AGENTS.md and docs/SEPARATOR_UPGRADE.md completely first. Inspect the current diff; do not undo or redesign worker 1.

Allowed production files: backend/app/config.py, backend/app/runtime.py, new files under backend/app/separators/ including model_cache.py, melband.py, worker.py, vendor/, and models/, plus the smallest registry/base changes required to register the documented adapter. Allowed tests: new backend tests for model cache, MelBand adapter/progress, worker math/probe, and runtime command. Do not touch API route behavior, Job persistence shape, frontend, desktop launcher dispatch, dependency files, PyInstaller, workflows, or documentation.

Implement exactly:
1. Add MODELS_DIR with browser-development default <DATA_DIR>/models and environment override KARAOKE_MODEL_DIR.
2. Add the immutable manifest from docs/SEPARATOR_UPGRADE.md: model ID, URL/revision, expected 913106900 bytes, SHA-256 87201f4d31afb5bc79993230fc49446918425574db48c01c405e44f365c7559e, and target cache path.
3. Implement streaming SHA-256 verification before each reuse; invalid-final removal; sibling .part download; byte-count/hash enforcement; throttled progress callback; atomic os.replace; partial cleanup and sanitized ProcessingError. Use standard-library HTTP. No Hugging Face client and no model download in tests.
4. Check in both pinned small configuration files and verify their recorded hashes/provenance: upstream MSST reference SHA f63f38eb1e6e40a7db0dade714a5ae257555dd8748f4e774eae8679275a81926 and benchmark inference config SHA b958b29c8f7195f0d86bee6759a33980db675c4ecaf2fcaa80fa125828e6cd38. Vendor only the required MIT attend.py and mel_band_roformer.py from python-audio-separator 0.44.3 commit ee1fcee90963919fe13a146fe71f57f29c2e9bbc, with provenance and upstream MIT license. Replace only its librosa mel-filter call with the documented fixed Slaney helper. Do not vendor or depend on audio-separator, diffq, librosa, or ONNX.
5. Implement separator_worker_command(): development python -u -m app.separators.worker; frozen executable --internal-separator. Preserve Demucs and yt-dlp commands.
6. Implement a CPU-only worker: clear CUDA_VISIBLE_DEVICES before Torch import; torch.device("cpu") only; fixed model/config validation; safe CPU checkpoint load; raw stereo float32/44.1 kHz input; scale only when absolute peak exceeds 1.0; exact 485100 chunk, 352800 step, Hamming overlap-add, short/final padding; vocals prediction; instrumental=residual; scale each output independently only above absolute peak 1.0; stereo float32 WAV output.
7. Emit KARAOKE_PROGRESS plus one JSON object per progress line. Implement --probe that validates imports/catalog/config and CPU mode without model weights or inference.
8. Implement MelBandAdapter preparation: verified model, bundled FFmpeg conversion to raw stereo f32le, streamed Popen worker output, parsed chunk progress/ETA, melband-roformer.log, and SeparatedStems return. No subprocess.run for inference.
9. Register the adapter without engine branches in routes/JobManager.
10. Tests use tiny fake byte streams, mocked URL responses, fake Popen/model, and short self-created NumPy arrays. Cover cache success/reuse/wrong size/hash/interruption, commands in dev/frozen mode, progress parser, chunk padding/overlap/residual, probe, and output mapping. Never download the real checkpoint or run the real model.

If exact upstream source cannot be recovered from the recorded commit, stop and report that blocker instead of substituting another implementation. Run focused backend pytest and git diff --check. End with exact files changed and tests/results. Do not commit.
```

## Worker 3 — frontend selection and restoration

```text
Implement only the Phase 1C React UI against the API/data fields already present. Read AGENTS.md and the API/frontend section of docs/SEPARATOR_UPGRADE.md. Inspect existing backend fields; do not change backend architecture.

Allowed files: web/src/App.tsx, web/src/App.css, and existing/new frontend tests or test config only if the project already has that test mechanism. Do not touch Python, dependency lockfiles unless a pre-existing frontend test requires it, packaging, workflows, or documentation.

Implement exactly:
1. Add SeparatorEngine = "demucs" | "melband_roformer" and add separator_engine/separator_model/preparing to frontend job/status types with graceful fallback for legacy payloads.
2. Add an engine selector before quality profiles. Demucs — current/faster remains selected by default. Preserve all three existing profile labels/copy and behavior unchanged.
3. Add High quality — MelBand RoFormer, marked Experimental, CPU-only, and ~871 MB first download. Do not promise perfect removal or a Windows runtime.
4. Show Demucs quality cards only for Demucs. For MelBand submit separator_engine=melband_roformer and quality=preserve for both upload and YouTube. Demucs submits selected current quality and separator_engine=demucs.
5. Add Prepare model for preparing progress and make it active, distinguishing setup/download from separating. Handle stage-local progress reset.
6. Active jobs/history/results show a human-readable persisted engine/model label and old jobs fall back to their Demucs quality/model.
7. Reset/Process another track returns to Demucs preserve. Do not change deletion, source rights, polling, player synchronization, or session behavior.
8. Match current responsive/accessibility style: real form controls, labels, keyboard focus, no hard-to-read disabled state.

Run frontend lint and build (and existing frontend tests if available), then git diff --check. End with exact files changed and test results. Do not commit.
```

## Worker 4 — dependency, frozen dispatch, packaging probe, integration

```text
Complete only the Phase 1C dependency/frozen-worker/packaging-probe integration. Read AGENTS.md and docs/SEPARATOR_UPGRADE.md completely. Inspect all current changes and preserve established interfaces/model behavior.

Allowed production/config files: backend/pyproject.toml, backend/uv.lock, backend/app/desktop.py, backend/desktop_entry.py, packaging/windows/KaraokeBox.spec, packaging/windows/README.md, package scripts only if needed for the existing smoke command, and focused backend desktop/runtime tests. You may make only minimal corrective imports in worker-2 files needed for packaging. Do not change API/UI semantics, RoFormer math, model manifest, rights/session behavior, GitHub workflow triggers, or documentation. Do not dispatch CI or build Windows artifacts.

Implement exactly:
1. Add direct dependencies only: beartype>=0.18.5,<0.19, einops>=0.8,<0.9, rotary-embedding-torch>=0.6.5,<0.7. Keep existing Torch 2.2/CPU and NumPy<2 constraints. Regenerate uv.lock normally. Confirm audio-separator, diffq, librosa, ONNX Runtime, CUDA packages, and Hugging Face Hub are absent as new direct/transitive additions attributable to this feature.
2. Desktop environment sets KARAOKE_MODEL_DIR to the existing platform model root. Preserve TORCH/HF caches, CUDA clearing, random loopback port, session token, windowed logging, and close protection.
3. Dispatch KaraokeBox.exe --internal-separator to app.separators.worker. Preserve --internal-demucs, --internal-ytdlp, and ordinary desktop startup.
4. Extend desktop development smoke to invoke the worker --probe without network, weights, or inference.
5. Update PyInstaller spec to include only required submodules and the checked-in model YAML/provenance/MIT notice. Never bundle the checkpoint. Keep onedir, frontend/FFmpeg assets, and CPU-only Torch behavior.
6. Add focused tests for desktop dispatch, model-directory environment, development/frozen worker commands, and no-weight probe.
7. Run backend tests, npm test, and npm run desktop:smoke. Do not run PyInstaller locally unless the coordinator explicitly asks; do not dispatch Windows workflow.

If dependency resolution forces Torch/NumPy migration or a non-commercial dependency, stop and report the conflict; do not relax constraints. End with exact files changed, dependency audit, tests/results, and remaining Windows-only gates. Do not commit.
```

## Reviewer 5 — read-only integration review

```text
Perform a read-only Phase 1C integration review. Read AGENTS.md and docs/SEPARATOR_UPGRADE.md completely, inspect git diff/status, and review all changed implementation/tests. Do not edit files, commit, push, download weights, or dispatch CI.

Check specifically:
1. Demucs preserve/best/standard commands, methods, output mapping, progress aggregation, ETA start, and frozen dispatch are unchanged.
2. separator_engine/model persist exactly and old job JSON loads correctly.
3. API defaults to Demucs and rejects MelBand with best/standard; routes/JobManager contain no model-specific branches.
4. Every compute path forces CPU and cannot select CUDA/MPS/DirectML.
5. Model download uses immutable URL, expected size, exact SHA-256, atomic partial handling, sanitized errors, and no automatic valid-cache deletion.
6. Inference uses streamed Popen progress; no buffered subprocess.run around model work.
7. Worker chunking, overlap-add, normalization, residual instrumental, stereo 44.1 kHz output, and stable final filenames match the design.
8. No audio-separator/diffq/librosa/ONNX/Hugging Face dependency slipped in; MIT provenance/config/license files are packaged; checkpoint is not packaged.
9. Desktop loopback/session security, windowed logging, yt-dlp/Demucs private commands, and close handling remain intact.
10. Routine tests cannot download a large model or run full inference and cover documented failure paths.
11. UI defaults/restoration/progress/history submit/display exact fields and do not overclaim quality/runtime.

Report findings in severity order with file:line references and concrete minimal fixes. If no findings, say so and list residual Windows/listening/long-track gates. Do not provide a new architecture or speculative feature ideas.
```
