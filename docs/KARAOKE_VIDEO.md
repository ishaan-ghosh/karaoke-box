# Karaoke Video Studio

## Status and scope

The Phase 1D line-timed Karaoke Video Studio is complete in the local working tree. After a completed stem separation, Lyric Lab can search `https://lrclib.net`, require explicit selection of a synchronized result, edit line timing and visual settings, preview against the instrumental with an optional vocal guide, and render a local `karaoke.mp4`.

Traditional synchronized LRC and valid LRCLIB `lyricsfile` version `1.0` records are accepted. Valid provider word timing can drive preview/render highlighting, but editing remains line-level; changing line text deliberately clears provider word timing. Untimed alignment, user `.lrc` import, and manual per-word editing remain deferred.

## Privacy, parsing, and provenance

Only title, artist, album, and search text are sent to LRCLIB. The client uses a fixed HTTPS host, fixed user agent, 10-second timeout, same-host HTTPS-only redirects, and a 512 KiB response limit; it accepts no client-supplied provider URL or credentials. JSON numeric tokens and constants are bounded/finite, provider fields are type-strict, and malformed, deeply nested, oversized, instrumental, or unsynchronized records are rejected.

`lyricsfile` uses a bounded `yaml.SafeLoader`: aliases are forbidden, depth and node counts are limited, version must be exactly `1.0`, and line/word timing must be integral, finite, ordered, and within render bounds. Malformed word timing falls back to otherwise valid line timing; a malformed record does not become a project.

The selected LRCLIB record ID and displayed metadata are retained in versioned `karaoke-project.json`. Karaoke Box does not claim that LRCLIB lyrics are licensed and does not add a second lyrics-rights checkbox. A durable lyrics-license field, licensed-provider enforcement, rights manifest, and legal review remain release work.

## Persistence and concurrency

Project selection, edits, and optional custom backgrounds use application-level compare-and-commit under the `JobStore` lock. Expensive provider/image work happens before the lock; commit then rechecks that rendering is inactive and that the prepared project revision still matches the persisted revision. Stale revisions and active-render mutations return conflicts instead of overwriting newer state.

A custom background is streamed to a bounded staging file, decoded with Pillow, dimension/pixel checked, canonicalized to PNG, and installed with the project revision. On a handled write failure, the commit restores the prior `job.json`, project, and background bytes and removes temporary files. Invalid/oversized uploads also remove their staging files.

Rendering is queued atomically and duplicate requests are rejected. If executor submission fails, the queued state rolls back to a retryable draft. Separation and rendering share the existing single-worker executor. Active rendering blocks project/background edits, job deletion, and normal desktop closure; startup marks an interrupted queued/rendering job failed for explicit retry.

## Editor and playback behavior

The editor supports line text/start edits, playhead capture, ±100 ms nudges, global offset, add/delete, title/subtitle, DECK-01 background presets, solid/gradient/custom-image backgrounds, bundled sans/display/mono typography, inactive/highlight colors, and top/center/bottom lyric placement.

Unsaved edits immediately mark the prior MP4 stale. Browser unload and leaving Lyric Lab warn before discarding dirty changes; background upload and rendering save dirty project data first. Active render state is restored and polled at one-second intervals, while the application history/VFD also reflects video queued/rendering/failed/stale/ready state.

Instrumental and vocal-guide audio are separate synchronized elements. Play aligns the guide to the instrumental, seeking updates both, vocal-guide level is adjustable, and playback errors/end/unmount pause or reset both. Preview timing and styling follow the renderer’s line/word interval semantics, including gaps and global offsets.

## Renderer lifecycle and output

Rendering probes FFmpeg for `libx264`, reads authoritative instrumental duration with ffprobe, enforces project/event and free-disk budgets, and generates one full background plus transparent event-state overlays. The concat manifest contains relative scratch filenames with `-safe 1`; the instrumental is copied into scratch so FFmpeg command/log output does not disclose the original local media path.

FFmpeg runs through streamed `subprocess.Popen` progress. A callback or render failure terminates and reaps the child when necessary, retains bounded/sanitized local diagnostics, preserves any prior stable MP4, and removes `.karaoke-render.partial.mp4` plus `karaoke-render-*` scratch in `finally`. Only a successful partial output atomically replaces `karaoke.mp4`.

The stable output contract is 1920×1080, 30 fps, H.264/libx264, yuv420p, AAC 192 kbps, instrumental audio only, and `+faststart`. Validated source duration is respected, including an intentional operator duration override.

## Fonts and coverage

The renderer uses checked-in fonts only. Archivo, Doto, and Spline Sans Mono Latin variable faces provide the selectable families; Noto Sans regular/bold handles non-ASCII fallback runs, and Noto Sans Symbols2 handles the explicit `★`, `☆`, `✓`, and `▶` set. Tests verify real Basic Latin glyphs, fallback selection for smart punctuation/non-ASCII text, and real glyphs for the supported symbols. This is bounded coverage, not a universal-script claim.

Exact package/release identities, resolved sources, SHA-256 values, embedded copyright notices, and SIL Open Font License 1.1 mapping are recorded in `backend/app/karaoke_assets/PROVENANCE.md`. The Noto upstream URLs are mutable paths; the checked-in hashes are the authoritative local identities.

## Final local validation

Final accepted local evidence:

- 124 backend tests passed.
- 8 Vitest tests passed, followed by oxlint, TypeScript compilation, and the Vite production build.
- `npm --prefix web ci --offline --ignore-scripts` passed. The resolved validation toolchain was Vite 8.1.4, Vitest 4.1.9, and the explicit `tinyexec` 1.2.4 override.
- Desktop development smoke passed, including authenticated startup/health and the no-weight/no-network separator probe.
- `/tmp/karaoke-box-render-accepted-ci9Va9/karaoke.mp4` was a 50,547-byte self-created final fixture: H.264 1920×1080 30 fps yuv420p video plus AAC audio, duration 1.000000 seconds. It contained smart punctuation and a verified symbol glyph, with no surviving partial output, scratch directory, or local-path disclosure.
- Final fresh-context Sol backend and frontend gates returned `ACCEPT`.

These are local macOS development checks. They are not manual browser/assistive-technology validation, legal/licensing approval, a production-readiness claim, or Windows package evidence. Routine tests are offline/mock-based and do not contact LRCLIB, download model weights, or run full separation inference.

## Deferred and release gates

Deferred product work includes untimed alignment, user `.lrc` import, manual per-word and waveform editing, microphone setup/latency/performance recording, mixed-performance audio/video exports, rights/attribution manifests, durable lyrics-license enforcement, and broader script/glyph coverage.

- Deferred application hardening includes cooperative cancellation and reaping of a running FFmpeg render during forced/abnormal shutdown, global UUID canonicalization of job IDs at the API/JobStore boundary, and ASGI-level request-body limits that reject oversized multipart bodies before parsing. Current upload limits are enforced while reading the parsed `UploadFile`.

Windows packaging of the renderer, Pillow/PyYAML, fonts, and the libx264/AAC path is still unverified. Packaged third-party notices and FFmpeg license/distribution, clean-Windows rendering, broader release-matrix behavior, and signing remain outstanding.

Historical Windows workflow run `29303479616` validates the Phase 1C separator package only. Its target-laptop real-song evidence is one roughly three-minute MelBand stem separation producing instrumental/vocal audio, not an MP4 render. Do not use that run or target-laptop result as Karaoke Video Studio validation.
