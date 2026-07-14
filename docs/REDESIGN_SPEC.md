# Karaoke Box — "Neon Lounge" Redesign Spec

**This is the single source of truth for the frontend visual overhaul.** Implementation happens ONLY in this worktree (`karaoke-box-redesign`, branch `frontend-redesign`). Nothing outside `web/` changes.

---

## 1. Concept

Today the app looks like a competent developer tool. It should feel like **a private after-hours karaoke lounge**: a warm dark listening room, one neon sign glowing on the wall, gold VU meters on hardware, ticket stubs from past sets. Intimate, tactile, a little theatrical. The interface is the room; the user's track is the act.

Three moods map to the three app phases:

- **House lights low** (upload): calm, warm dark, inviting. The drop zone is the empty stage.
- **On air** (processing): the booth is working — meters dance, a neon ON AIR sign glows. Waiting minutes should feel like watching a soundcheck, not a loading bar.
- **Showtime** (result): the payoff — stage wash brightens gold for a beat, the mixer presents itself like a console.

What someone remembers: **the neon "karaoke." sign flickering on**, and **the equalizer bars that dance while their song is being pulled apart**.

## 2. Foundations

### 2.1 Color tokens (replace ALL ad-hoc hexes — everything goes through tokens)

```css
:root {
  /* room */
  --bg-0: #0f0b09;            /* page — warm black */
  --bg-glow-neon: rgba(255, 61, 99, 0.10);
  --bg-glow-gold: rgba(242, 177, 62, 0.05);

  /* surfaces (layered wood-dark panels) */
  --surface-1: #191310;       /* cards */
  --surface-2: #221a15;       /* raised wells, inputs */
  --surface-3: #2b211a;       /* hover / selected fills */
  --line-1: #33291f;          /* hairline */
  --line-2: #4d3d2e;          /* strong border / hover */

  /* ink */
  --ink: #f7efe3;
  --ink-muted: #a89a89;
  --ink-faint: #71655a;

  /* neon — primary accent (signage pink-red) */
  --neon: #ff3d63;
  --neon-hot: #ff6584;        /* hover */
  --neon-dim: rgba(255, 61, 99, 0.14);
  --neon-glow: rgba(255, 61, 99, 0.40);   /* for text-shadow / box-shadow blooms */
  --on-neon: #1c0910;         /* text on neon fills */

  /* gold — secondary accent (VU meters, "ready", completed) */
  --gold: #f2b13e;
  --gold-dim: rgba(242, 177, 62, 0.14);
  --gold-glow: rgba(242, 177, 62, 0.35);
  --on-gold: #201505;

  /* status */
  --led-green: #7cd992;       /* "Local only" hardware LED only */
  --danger: #e06055;
  --danger-dim: rgba(224, 96, 85, 0.13);
  --warn: #d9a05b;
  --warn-dim: rgba(217, 160, 91, 0.12);
}
```

Semantic mapping (bold, intentional): **completed = gold** (ready for the stage), **active/processing = neon pulse**, **failed = danger red**. Success icons are gold, not green — green exists only as the tiny "Local only" LED.

### 2.2 Typography (bundled, offline-safe — NO CDN)

Install via fontsource and import in `web/src/main.tsx`:

- **Display + body:** `@fontsource-variable/bricolage-grotesque` → `--font-display: 'Bricolage Grotesque Variable', system-ui, sans-serif`. Hero at weight 800, headings 600–700, body 400 at 15–16px.
- **Accent serif:** `@fontsource/instrument-serif` (400 + 400-italic) → `--font-serif: 'Instrument Serif', Georgia, serif`. Used italic for the neon hero word and small flourish words ("your stage", stem names' descriptors).
- **Mono:** `@fontsource-variable/spline-sans-mono` → `--font-mono: 'Spline Sans Mono Variable', ui-monospace, monospace`. Eyebrows, pills, timecodes, percentages, stage labels, footer.

> Verify exact package names with `npm view <pkg> version` before installing; if one is missing, closest substitutes: Hanken Grotesk Variable (display/body), Fraunces italic (serif), IBM Plex Mono (mono). Do not fall back to Inter/Roboto/Arial/Space Grotesk.

Type scale: hero `clamp(52px, 9vw, 92px)`, line-height 0.94, letter-spacing −0.045em; H2 24px/−0.02em w650; body 15px/1.7; labels 11px mono uppercase +0.14em; micro 9–10px mono uppercase.

### 2.3 Space, shape, elevation

- Spacing scale: 4 / 8 / 12 / 16 / 24 / 32 / 48 / 72 (`--space-*`).
- Radius: `--r-sm: 8px` (chips, inputs), `--r-md: 12px` (controls, wells), `--r-lg: 20px` (cards), `--r-pill: 999px`.
- Cards: `--surface-1`, 1px `--line-1`, radius `--r-lg`, `box-shadow: 0 30px 90px rgba(0,0,0,.45)`, plus the signature **top light-line** (inset 1px gradient highlight across the top edge).
- Wells (drop zone, transport, inputs): `--surface-2`, inset feel (`box-shadow: inset 0 1px 0 rgba(0,0,0,.4)` subtle).

### 2.4 Atmosphere (the "room")

A fixed, pointer-events-none background layer stack on `.app-shell`:
1. Base `--bg-0`.
2. Two huge radial gradients — neon wash upper right, gold wash mid left — **drifting very slowly** (a 90s alternating transform/opacity keyframe loop, barely perceptible).
3. **Grain**: SVG `feTurbulence` noise as a data-URI tile, `opacity: .05`, `mix-blend-mode: overlay`. Grain is static (no animation — cheap).

During processing, the neon wash intensifies slightly (add a class on the shell). On completion, a one-time **gold flash**: the gold wash blooms to ~2.5× opacity and settles over 1.2s.

### 2.5 Motion language

Add dependency: **`motion`** (v12, React 19 compatible), import from `motion/react`.

- Easings: `--ease-out: cubic-bezier(.16,1,.3,1)`; springs for anything touched (`{ type: 'spring', stiffness: 480, damping: 32 }` press, softer `{ stiffness: 220, damping: 26 }` for cards).
- Durations: fast 140ms (hover/press), medium 320ms (state changes), slow 600–800ms (view entrances).
- **Page load choreography** (once): header fades down (0ms) → hero eyebrow (80ms) → hero lines rise with clip-path/translateY stagger (120ms apart) → **neon word flickers on** (after 500ms: 3 rapid opacity stutters then steady bloom) → main card rises + settles with soft spring (650ms) → privacy strip/footer fade (900ms).
- **View transitions**: wrap the main card area in `AnimatePresence mode="wait"`; exit = fade + scale(.985) + y(−8), 200ms; enter = fade + y(16→0) spring. The four states (upload / progress / failed / result) each get a stable `key`.
- **Micro-interactions**: buttons scale .97 on press with spring; tab indicator slides via `layoutId`; radio-card selection ring animates in; drop-zone drag = marching-ants dashed border (SVG rect, animated `stroke-dashoffset`) + scale 1.01; slider thumbs bloom a neon glow while dragging; history rows stagger in 40ms apart; percentage readouts tick (animate number roll on change).
- **Equalizer motif** (pure CSS, reusable `.eq` component): 5 bars, `scaleY` keyframes with staggered `animation-delay`, gold bars. Large in ProgressCard, small "now playing" variant in the transport, tiny in the active history row.
- **`prefers-reduced-motion`**: global kill switch — decorative loops off, flicker replaced by simple fade, view transitions become opacity-only. Use `useReducedMotion()` from motion for JS-driven pieces plus a CSS media block.

## 3. Component treatments

### 3.1 Shell
- **Header**: keep layout. Brand mark becomes a **neon-outline rounded square** (pink stroke waveform glyph, subtle glow) — no more rotated orange circle. Wordmark in display 700. "Local only" pill: mono, `--surface-2`, green LED dot with soft glow (keep).
- **Hero**: eyebrow mono gold ("MAKE THE ROOM YOUR STAGE"). H1: "Turn your track into *karaoke.*" — "karaoke." in Instrument Serif italic, `--neon`, layered `text-shadow` neon bloom, the flicker-on entrance. Lede body in `--ink-muted`, max 620px.
- **Privacy strip**: becomes a slim "house rules" bar — mono micro labels with gold bullet separators, hairline top/bottom. Keep the ⌂→ replace glyph with a tiny inline SVG (shield or house), `--ink-faint`.
- **Footer**: mono micro, unchanged structure.

### 3.2 Upload card ("Choose your track")
- Card heading: step number becomes a **gold mono "01"** in a small square well; eyebrow mono; H2 display.
- **Source tabs**: pill-shaped segmented control on `--surface-2`; active pill = `--surface-3` with neon underline-glow indicator that **slides** between tabs (`layoutId="tab-indicator"`).
- **Drop zone**: the empty stage. `--surface-2` well, subtle diagonal hatch kept but warmer; center: a round **neon-rimmed mic/upload glyph**, "Drop an audio file here" in display 600, formats line in mono micro. Drag state: marching-ants neon dashed border + `--neon-dim` fill + scale 1.01. Has-file state: glyph swaps to a gold ♫ (or inline SVG note), filename in mono, size in micro; a "Choose another" text-button in neon.
- **Engine/quality radio cards**: keep grid anatomy (real inputs + custom marks). Selected = neon border at 70% + `--neon-dim` fill + the radio mark fills neon with a soft outer glow; badges (`Recommended`, `Experimental`) become tiny gold/mono chips. Speed tag right-aligned mono micro.
- **Rights checkbox**: custom 20px square, checked = neon fill with `--on-neon` check, spring pop (scale 0.8→1.05→1) on check.
- **Primary CTA**: full-width, 52px, **neon fill**, `--on-neon` text, weight 700, subtle outer glow (`0 8px 30px var(--neon-glow)`); hover = `--neon-hot` + lift 1px; press = spring squash; disabled = 35% opacity, no glow. Busy state: label swaps with a small inline spinner.
- **Upload progress**: 3px track in `--surface-3`, neon fill with a subtle animated shimmer; caption mono micro.

### 3.3 Progress card ("On air")
- Replace the breathing orbit with the **equalizer cluster**: 5 gold bars dancing (CSS), inside a round `--surface-2` well with a faint gold glow ring.
- Above it: an **"ON AIR" pill** — mono, neon text + neon hairline border, pulsing glow (2s loop).
- H2 = live `job.message` (display 600). Muted line: source name in mono.
- **Readout**: percentage in large mono (28px) with number-tick animation; "Model pass X of Y" mono micro; ETA right-aligned gold micro.
- **Progress track**: 4px, gold fill (matches meters), animated shimmer sweep.
- **Stage stepper**: keep `<ol>` anatomy. Done = gold-filled dots with ✓, connector line fills gold; active = neon-ringed dot with pulsing center; labels mono micro. 
- Foot note mono micro.
- While this card is mounted, add the shell class that warms the neon wash (§2.4).

### 3.4 Failed card
- Danger treatment, same anatomy: round danger-rimmed "!" well, eyebrow mono danger, message body `--ink-muted` (keep `pre-wrap`), "Try another source" secondary button. Entrance: small shake-settle (x: 0→−6→5→0, 350ms) — skipped under reduced motion.

### 3.5 Result card ("Showtime") — StemMixer
- Heading: **gold** ✓ in a gold-dim round well, eyebrow gold mono ("SEPARATION COMPLETE"), H2 "Your karaoke mix".
- On mount: the one-time **gold stage flash** (§2.4) + heading pops in with spring.
- **Transport**: `--surface-2` well; play button = 46px **neon round button** with glow (play/pause glyphs as inline SVGs, not Unicode); timecodes mono; **custom-styled range** for the timeline — 4px track, played-portion neon, 14px thumb with neon bloom while dragging. While playing, a tiny 3-bar eq pulses next to the timecode.
- **Stem cards**: keep 2-up grid. Each card: name in display 600 + descriptor in serif italic `--ink-faint` ("the karaoke bed" / "blend back for guidance"), live % in gold mono with tick animation, full-width custom range (gold track-fill for Instrumental, neon for Original vocals — instantly tells them apart).
- **Download CTA**: primary neon button with a ↓ inline SVG; hover glow.
- "Process another source" quiet text-button below the card.
- **CRITICAL**: the two hidden `<audio>` elements, their refs, the Web Audio gain graph, and the rAF playhead loop must remain functionally untouched. Ranges stay real `<input type="range">` with existing handlers.

### 3.6 Job history ("Set list")
- Card heading: eyebrow "STORED LOCALLY", H2 "Recent tracks", count in mono gold ("3 SAVED").
- Rows become **ticket stubs**: `--surface-2` rows with a perforated left edge (punched-hole radial-gradient mask) and a mono ticket index (№01, №02…) replacing the ♫ icon block. Filename display 500; meta line mono micro.
- Status pills: mono micro — active = neon with tiny eq bars, completed = gold dot, failed = danger dot. (Class names may change, but keep the mapping driven by `job.status` strings.)
- Actions: compact ghost chips (hairline border, mono 9px); Delete = danger ghost. Hover: row lifts 1px, border → `--line-2`; selected row = neon hairline + `--neon-dim` tint.
- Rows stagger-animate on first mount; a newly added row slides in via `AnimatePresence`.

### 3.7 Alerts
- Same anatomy, new skin: warn/danger dim fills, 1px matching border, radius `--r-md`, mono micro heading + body 13px; a slim colored left rail (3px) instead of full border emphasis. Slide-down entrance.

## 4. Copy polish (allowed, meaning-preserving)
- Eyebrows/labels may be tightened to fit the lounge voice (e.g. "SEPARATION COMPLETE", "ON AIR", "SET LIST" as a heading eyebrow) — but keep functional copy (button labels like "Fetch and separate", "Download instrumental WAV", rights attestation text) **unchanged**.

## 5. Hard constraints (do not violate)

1. Only `web/` changes. No backend, packaging, or docs edits (besides this spec).
2. Fully offline: all fonts/assets bundled through Vite; no CDN links, no Google Fonts `<link>`.
3. Keep functional wiring intact: dual `<audio>` refs + Web Audio gain mixing; rAF playhead (never seeks the media clocks); 1s polling; localStorage restore; XHR upload progress; inline `width:%` progress styles (or equivalent JS-driven mechanism).
4. Real inputs stay behind every custom control (radios, checkbox, ranges, file input); keep `role=tablist/tab`, `role=progressbar` + `aria-valuenow`, `aria-live` regions, `.sr-only` labels, visible `:focus-visible` (neon outline).
5. `index.html`: keep `#root`; update `theme-color` to `#0f0b09`; add an inline SVG favicon (neon waveform on dark rounded square, data URI).
6. `tsc -b` is strict about unused vars — build (`npm --prefix web run build`) and lint (`npm --prefix web run lint`) must pass after every stage.
7. Responsive: preserve/adapt the `max-width: 680px` breakpoint behaviors (single-column mixer, compact rows, shrunken hero).
8. `prefers-reduced-motion` honored everywhere (CSS + `useReducedMotion`).

## 6. File architecture

- `web/src/styles/tokens.css` — every custom property in §2.
- `web/src/styles/base.css` — reset, body, atmosphere layers, grain, focus, reduced-motion blocks, keyframes shared across views.
- `web/src/App.css` — rewritten component styles (token-driven only; zero raw hex outside tokens.css).
- `web/src/index.css` — slimmed: imports or is replaced by the above (keep import order in `main.tsx`: fonts → tokens → base → App.css).
- Components may be extracted into `web/src/components/*.tsx` (Header, Hero, UploadCard, ProgressCard, FailedCard, StemMixer, JobHistory, PrivacyStrip, Eq, icons) **but all state/effects/data logic stays in `App.tsx`** and moves only by prop-passing; do not restructure data flow.
- Inline SVG icon module (`web/src/components/icons.tsx`): waveform brand mark, play, pause, download, upload, note, check, alert — replacing Unicode glyphs.
