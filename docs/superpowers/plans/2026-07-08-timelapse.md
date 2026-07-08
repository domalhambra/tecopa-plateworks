# TrailPrint — Time-lapse Render: the poster as a film (design + implementation plan)

_2026-07-08 · Status: **proposed** (not yet built). Companion plan:
`2026-07-08-living-editions.md` — build Editions first (pure plumbing, no render
refactor); this plan touches `render.py` structurally. The two compound: the
time-lapse of a multi-edition poster is "watch a decade grow"._

---

## Context — why this feature

The spec already contains time: `track_days` rides every composition (it drives
journey grouping for the worn-width pass and terminus pins). And rendering is
deterministic — same spec, same image. Put together, an animation is not a new kind
of output: it is **one spec painted many times, each frame showing a prefix of the
journey in day order**. Terrain, water, and names hold still; the route accumulates,
outing by outing, until the final frame — which is pixel-identical to the poster.

Product intent: the shareable, alive version of the poster. A client posts the film;
the last frame *is* their print. On a phone it's a keepsake that replays the year.

## The one design idea: a frame is a prefix of the journeys

`render._journey_groups(spec)` already partitions tracks into journeys keyed by day.
Sort those journeys by day (day-less journeys last, in stable upload order) and the
frame plan is just the list of prefixes. Everything else falls out:

- **Determinism (invariant 3)**: the frame plan is a pure function of the spec — no
  clock, fixed seed. Same spec → byte-identical animation.
- **One spec, many paints (invariant 1)**: the last frame and `/api/final` are the
  same spec at the same dpi — they must be pixel-equal. That equality is the
  feature's master regression test.
- **Physical units (invariant 2)**: nothing new is sized; frames reuse the exact
  paint code.
- **Self-describing (the file is the artwork)**: the deliverable is an **APNG** — a
  PNG, so the provenance manifest embeds in the same `zTXt` chunk as ever. An
  animated TrailPrint file inspects and re-renders from the file alone, like any
  poster.

### Cost model — paint the base once, ink increments

A naive loop (full `rasterize` per frame) is ~N × a full final. Instead:

- The **static base** — relief, contours, hydro, geography labels — is painted once.
- `_coverage` already computes per-journey coverage layers (it takes `groups`).
  Compute each journey's coverage **once**, keep a running sum, and per frame apply
  the existing coverage→ink transfer (worn-width darkening is a nonlinear function
  of the *summed* coverage, so the running sum reproduces the full-prefix ink
  exactly) onto a fresh copy of the base, then draw that prefix's terminus pins and
  the static overlays.
- Total cost ≈ one full render + N cheap composites. A 40-frame phone-size film
  (1179×2556) is ~120 MP of composite work — seconds, not minutes.

## Product shape (v1)

- **Post-accept card in the wizard**, beside the wallpaper bundle: "Time-lapse".
  Frame-pacing controls (sensible defaults), a target (the accepted sheet at a
  bounded dpi, or a wallpaper preset for exact device pixels), submit → job → an
  autoplaying `<img>` preview (APNG plays natively in every modern browser) →
  download.
- **Frame narrative**: one terrain-only leader frame (the empty region, a beat
  before the first outing), then journeys accumulate in day order, then a long hold
  on the complete poster. Markers, photos, and furniture stay present on every
  frame (they are places and frame, not journey); terminus pins appear with their
  journey.
- **Day binning**: more distinct days than `max_frames` (default 40) are binned
  into `max_frames` steps by even count, so a decade of daily runs still reads as a
  film, not a flipbook.
- **APNG only** in v1 (see decision 1): it carries the manifest, holds full
  quality, and autoplays. File size is bounded by the animation ceiling below.

## Design by module

### `app/render.py` — refactor first, behavior-identical

Split `rasterize` into named stages with **zero behavior change** (the existing
determinism/registration suites plus one explicit before/after byte-equality test
guard the refactor):

- `_paint_base(spec, dpi, region_dir, cfg, hydro, labels) -> (rgb, lum)` — off-DEM
  guard, DEM window, relief, contours, hydro, geography labels, and the luminance
  plane `_draw_markers` needs.
- `_paint_journey(rgb, lum, spec, out_w, out_h, dpi, groups)` — `_ink_tracks` +
  `_draw_termini`, restricted to the given journey groups. (`_ink_tracks` /
  `_coverage` already accept groups; the change is threading a subset through.)
- `_paint_overlays(img, spec, ...)` — markers, photos, keyline, compass, title
  block, watermark.
- `rasterize` becomes base → journey(all groups) → overlays. Public signature and
  output unchanged.

### `app/timelapse.py` (new)

- `frame_plan(spec, max_frames) -> list[list[group]]` — journeys sorted by day
  (None-day journeys last, stable order), binned to ≤ `max_frames` steps, with the
  leader (empty prefix) and the full prefix always present. Pure function; unit
  tests own the ordering/binning edge cases (all day-less, one journey, ties).
- `render_frames(spec, dpi, region_dir, cfg, plan)` — generator yielding PIL
  frames: base once, per-journey coverage once, running-sum ink per frame,
  overlays per frame. Memory holds the base, the running coverage array, and one
  frame at a time (the encoder consumes the generator).
- `encode_apng(frames, manifest, step_ms, hold_ms, dpi) -> bytes` —
  `Image.save(..., "PNG", save_all=True, append_images=..., duration=[...],
  loop=0, pnginfo=manifest_pnginfo(...))`, sRGB profile as usual. Per-frame
  `duration` list gives the leader a beat and the last frame its hold.

### `app/spec.py` / `app/provenance.py`

- **No new spec fields.** Pacing (`max_frames`, `step_ms`, `hold_ms`) is not a
  picture decision — it never changes any frame's pixels, only how many prefixes
  are cut and how long they show — so it stays out of the spec and rides the
  manifest's `animation` block instead.
- Manifest: additive optional `"animation": {"max_frames": N, "step_ms": M,
  "hold_ms": H}` — omitted for stills, so every existing manifest byte and frozen
  fixture is untouched; `MANIFEST_VERSION` stays 1. With the spec + this block,
  the animated file is fully reproducible.

### `app/main.py`

- Animation ceiling next to the render guards:
  `MAX_ANIMATION_PIXELS = 600_000_000` total (frames × w × h), checked before
  enqueue → honest 422 naming the fix ("fewer frames or a smaller target").
- **`POST /api/timelapse/submit`** (form: `session_id`, `max_frames=40`,
  `step_ms=220`, `hold_ms=2500`, optional `wallpaper_preset`, optional `dpi` for
  the print-sheet target, bounded ≤ `FINAL_DPI`, default `PROOF_DPI`-quality —
  a film is a screen artifact): `_require_stamped` gate; preset targets re-fit via
  the existing `wallpaper.spec_for_preset`; pacing params bounds-checked (frames
  2–120, durations 40–10000 ms) → one `ThreadJobQueue` job → blob
  `{session}/timelapse.png` → the existing `/api/jobs/{id}` → `/result` flow
  (`.png` already maps to the right media type).
- **`/api/reprint`**: when the uploaded file's manifest carries `animation`,
  re-render the film (same job-free path as stills is wrong here — a film render
  is slow, so reprint-of-animation goes through the queue: respond `{job}` instead
  of streaming; stills keep today's synchronous contract). `/api/reprint/inspect`
  reports the animation block.

### `app/static/` (wizard)

- Post-accept "Time-lapse" card: pacing slider (frame count), target picker
  (accepted sheet / device presets reusing the wallpaper preset list), submit →
  poll → `<img>` preview + download. No new preview machinery — the browser plays
  APNG.

## Decision points for Dom (defaults chosen — cheap to reverse before build)

1. **APNG only** (chosen) vs. WebP/GIF/MP4. APNG: manifest + lossless + autoplay.
   MP4 needs an ffmpeg dependency (refused for v1 — first non-Python binary dep);
   animated WebP is a cheap later add for size-sensitive sharing; GIF is a quality
   downgrade with nothing in return. Cost: APNG files are large — the ceiling and
   the screen-dpi default keep them tens of MB, not hundreds.
2. **Leader frame** (chosen): one beat of bare terrain before the first journey.
   Alternative — open on journey 1. Pure `frame_plan` tweak.
3. **Markers/photos/furniture static on every frame** (chosen) vs. appearing with
   their nearest journey. Static keeps v1 honest (hotspots aren't dated — inferring
   their date from nearby tracks is guesswork); pins accumulating with journeys
   already gives the film its motion.
4. **Reprint of an animated file re-renders the film** (chosen, via the job queue)
   vs. re-rendering only the final still. The file promises "the file is the
   artwork"; honoring that for films keeps the promise unconditional.
5. **Default target is screen-resolution** (chosen): a film is watched, not
   printed. Print-dpi films are allowed up to the ceiling for whoever wants one.

## Implementation plan (TDD, in order)

**Phase 1 — the refactor (no behavior change)**
1. Split `rasterize` into `_paint_base` / `_paint_journey` / `_paint_overlays`.
   Tests — a pinned spec renders **byte-identical** before/after (assert against a
   pre-refactor golden checksum committed with the test); full existing suite
   green untouched.

**Phase 2 — the film engine**
2. `timelapse.frame_plan`; tests — day ordering, day-less-last stability, binning
   to `max_frames`, leader + full prefix always present, purity/determinism,
   degenerate cases (one journey, all day-less, `max_frames=2`).
3. `timelapse.render_frames` + `encode_apng`; tests — **last frame pixel-equal to
   `rasterize(spec)` at the same dpi** (the master invariant); running-sum ink
   equals full-prefix ink for a 3-journey overlap case (worn-width correctness);
   APNG `is_animated`, `n_frames`, per-frame durations; the manifest extracts from
   the animated file and `manifest_to_spec` round-trips (verify Pillow writes
   `pnginfo` text chunks with `save_all=True` — this is the plan's one library
   assumption; if it fails, fall back to embedding via a rewritten first IDAT-less
   pass, and say so in the doc).

**Phase 3 — API**
4. `/api/timelapse/submit` + ceiling + pacing bounds + preset targeting; reprint
   of animated files via the queue; inspect reports `animation`. Tests — submit →
   job → APNG in blobs; ceiling/bounds 422s; wallpaper-preset film is exact device
   pixels; reprint(film) reproduces it byte-identically; frozen
   `manifest_animation_v1.json` fixture (forever-contract, same discipline as
   print/wallpaper/edition fixtures).

**Phase 4 — wizard + quality**
5. The Time-lapse card; drive end-to-end (Playwright/Chromium): compose from
   `sample.gpx` (multi-day fixture), submit, poll, confirm the preview animates
   and the download inspects correctly.
6. By-eye pass on real terrain (pacing feel, leader beat, hold length) — pacing
   defaults are the one aesthetic judgment in this plan; budget a taste session.

Adversarial review (the `Workflow` tool pattern) after Phases 1–2 and 3, per repo
convention. Phase 1 is the risk concentration: a silent behavior change in the
refactor corrupts every downstream output, which is why it ships alone with a
byte-equality gate.

## Verification

- `pytest -q` green; the pinned before/after golden proves the refactor inert.
- The master invariant, end-to-end: render `/api/final`, render the film at the
  same dpi, extract the film's last frame — pixel-equal.
- Determinism: two runs of the same submit → byte-identical APNG.
- File-size sanity: default phone film ≤ ~40 MB; 4K desktop film under the ceiling.

## Out of scope (later)

- Animated WebP / MP4 exports; per-point (intra-day) animation — `ingest` keeps
  only day granularity today, and per-point time would swell the spec; iOS Live
  Photo / Android live-wallpaper packaging; a scrubber UI over the film; music.
