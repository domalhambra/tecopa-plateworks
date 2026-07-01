# TrailPrint Studio — Guided Wizard UI Refinement

**Date:** 2026-06-30
**Status:** Design approved, pending spec review
**Scope:** Frontend rewrite of `app/static/*` into a guided step wizard, plus one new backend endpoint. Reuses the existing render engine and API surface unchanged.

---

## 1. Background

The current UI (`app/static/index.html`, `app.js`, `style.css`, ~285 lines) is a flat single page: region cards, a drop zone, a file list, a print-size select, proof/accept/clear buttons, the aim canvas, and a marker side-list are all visible at once. It works for the operator but gives a first-time viewer no sense of sequence.

A Claude Design refinement ("TrailPrint Studio," delivered as `docs/trails for claude design/TrailPrint UI refinement/`) reimagines this as a 5-step guided wizard (Region → Tracks → Places → Frame → Proof) with a left-rail stepper, a Night/Day theme toggle, contextual hint pills, on-map label pills, and one primary action per step.

Before committing, the proposed workflow was adversarially red-teamed (six independent lenses — first-run cognitive load, step efficiency/IA, error paths, gesture discoverability, accessibility, power-operator speed — then a synthesis and a devil's-advocate pass). This spec is the product of that review. The raw refinement is honored where it helps a watching client; it is trimmed where it would slow the repeat operator or regress accessibility.

### The central tension the red-team surfaced

The same concierge session flips between two audiences: a **client watching over Dom's shoulder** (benefits from one-task-per-screen guidance) and **Dom the operator** running many posters back-to-back (the flat page let him drop-crop-render with zero navigation). A literal 5-gated-step wizard adds ~4–6 forced navigations for the operator and leaves three steps near-dead in the single-region v1 reality (Region auto-selects, Places is optional, Frame/Proof are one decide-confirm loop split across two screens). The design below keeps the guided feel while removing that regression.

---

## 2. Goals and non-goals

### Goals
- A guided flow that reads clearly to a first-time viewer, without being slower than the current flat page for the repeat operator.
- No empty "black void" resting states: every screen shows its primary action.
- Make the locked marker-drag-to-reposition decision actually work (persisted).
- Preserve the accessible marker side-list.
- Honor all six build-plan invariants (one spec painted at many sizes; physical units; determinism; one projection; registration; the zoom cap).

### Non-goals (deferred)
- Cross-region auto-recovery on upload (v1.2 — one region is v1 reality).
- Full keyboard-operable canvas / ARIA live regions on the spatial widgets.
- Client-side async poll timeout / attempt cap (risks abandoning a correct-but-slow 300 DPI final).
- "Express" chained proof+accept.
- Photo attachment remains optional (v1.1) and must never gate the flow.

---

## 3. Architecture

### Frontend
Vanilla JS, no framework (honors the build plan). The current single `app.js` grows with a step machine, so it is split into focused ES modules loaded via `<script type="module">` (no build step):

| Module | Responsibility |
|---|---|
| `app.js` | Bootstrap; owns the step state machine and transitions; wires the stepper. |
| `api.js` | Thin `fetch` wrappers for every endpoint; returns parsed JSON / blobs, throws typed errors. |
| `canvas.js` | All canvas drawing (overview, tracks, hotspots, crop box, label pills) plus the crop-draw and marker-drag pointer interactions. |
| `markers.js` | The marker side-list (label/icon/photo rows) and its sync to `/api/markers` + `/api/photo`. |
| `state.js` | The single `state` object + `localStorage` persistence (last region, print size, theme). |

Each module has one clear job, a small surface, and can be reasoned about in isolation.

### Backend
One new endpoint. Everything else is reused unchanged:
- `GET /api/regions`, `POST /api/upload`, `POST /api/markers`, `POST /api/photo`, `POST /api/proof`, `POST /api/final/submit`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/result`.
- **New:** `POST /api/markers/move` (§6).

---

## 4. The step state machine

Steps: `region` (conditional) → `tracks` (Tracks & Places, merged) → `frame` → `proof`.

**Advancement model (single nav paradigm):**
- Each step has one consistently placed **primary button** that names the next outcome ("Continue to Frame", "Render proof", "Accept & render final").
- The left-rail **stepper** shows progress and allows **click-back to any completed step**. It is not used for forward motion.
- Editing a completed step preserves later work where the data still applies (e.g., re-naming a marker does not discard a drawn crop; changing the crop invalidates the stamped spec and flags the proof as stale — see §5.4).

**Region auto-skip:** on load, `GET /api/regions`. If the list has ≤1 region, the `region` step is removed from the stepper, the single region is auto-selected, its name is shown in the header, and the flow starts on `tracks`. This carries forward the current flat UI's behavior (`app.js` `loadRegions()` already does this) so the wizard does not regress to a forced empty step. If 2+ regions exist, `region` is shown, and a subsequent track drop may still auto-resolve the region via the existing upload auto-detect.

---

## 5. Step details

### 5.1 Region (conditional)
- Shows the real `/api/regions` card gallery (each card = overview thumbnail + name), not an empty canvas.
- A one-line value statement above the gallery: e.g. "Turn your tracks into a shaded-relief poster."
- Pre-selects the last-used region from `localStorage` when present.
- Primary button: "Continue to Tracks" (enabled once a region is selected).
- Skipped entirely when ≤1 region exists.

### 5.2 Tracks & Places (merged)
This step merges the mockup's separate Tracks and Places steps into one surface — marker *position* and marker *identity* are one job.

**Empty state (before any upload):** a prominent dashed **drop zone** centered in the map pane — "Drop GPX / KML / KMZ here, or click to browse." This is the app's primary action and must be visible; the mockups only showed the post-upload view.

**Loaded state (after upload):**
- The low-res relief overview with tracks drawn and auto-detected gold hotspot markers.
- A persistent, compact "Add more files" control + accumulating file list (the backend accumulates across uploads; the user must be able to see and use that).
- The **marker side-list** (kept): one row per hotspot with a label field, icon picker, and optional photo attach — tab-able, unambiguous, screen-reader-friendly.
- **Drag-to-reposition:** dragging a hotspot dot on the map moves it; on drag-end the new position persists via `POST /api/markers/move` (§6). Enhancement layered on top of the side-list, not a replacement for it.
- Primary hint is verification-first: "Your tracks are on the map — the gold dots mark places you returned to most." The drag hint is a secondary tip that appears on first marker hover and self-retires.
- Naming is visibly **optional/skippable**. Primary button: "Continue to Frame" (enabled once at least one track is loaded).

**Marker-drag hit-testing:** hotspot dots render small (radius ~6px on the overview). A pointer-down within the dot's hit radius that moves beyond a small threshold before pointer-up is a drag (reposition). The side-list remains the unambiguous path for editing identity, so the map interaction only needs to handle *move*, avoiding click-vs-drag ambiguity on the dot itself.

### 5.3 Frame
- Print-size selector surfaced at the top of the step (it drives the crop aspect). Changing it re-fits the existing crop in place (never leaves a stale mismatch).
- **Sensible starter crop** drawn on entry: a fraction of the *region* extent centered on the track centroid, expanded to the selected print aspect, clamped to region bounds and to the zoom-cap floor. This is deliberately **not** the tight track bounding box — a tight cluster blown up to print aspect would trip the zoom cap and produce cramped framings. The starter box gives generous surrounding terrain (matching the county-scale reference posters) and guarantees "Render proof" works on entry without tripping the cap.
- **Crop-draw geometry fix:** the current implementation (`app.js:156–160`) pins `dragStart` as the top-left corner, so dragging up or left inverts the rectangle and the box only grows down-and-right. Normalize by taking `min`/`max` of start and current pointer and deriving the aspect-locked height on the correct side, so the box grows correctly in all four directions.
- Controls: "Reset frame" (clears only the crop, not the session), Escape cancels an in-progress drag.
- **Zoom-cap feedback:** during drag, tint the crop box red when it drops below the resolution floor. On a rejected proof (backend 422 `ZoomTooTightError`), translate the raw string ("X m/px requested, data floor is Y") into a human inline message: "This crop is too tight to print sharp at 18×24 — draw wider or pick a larger size."
- Primary button: "Render proof" (calls `POST /api/proof`, shows the returned PNG, advances to Proof).

### 5.4 Proof
- Shows the mid-fidelity framed poster proof (the poster-reveal styling from `s5-poster.png` — white border, title block, PROOF watermark; the watermark and title text are already server-rendered by `render.rasterize`).
- Primary button: "Accept & render final" — submits `POST /api/final/submit`, polls `GET /api/jobs/{id}` with the **existing** loop (queued/running/error/done), downloads the resulting PNG on `done`. No client-side timeout is added (a slow 300 DPI 5400×7200 render is still a correct render).
- **"Reframe"** button returns to Frame with the crop preserved (one click, not a stepper round-trip).
- **Stale-proof guard:** any edit that sets `spec=None` server-side (marker label/icon/photo/move, or a crop change) flags the proof as stale; Accept then prompts "re-render the proof first" rather than letting a stale proof look acceptable. Retry after a failed final is only offered while a valid stamped spec exists (a re-submit with `spec=None` would hit "Approve a proof first").

---

## 6. New endpoint: `POST /api/markers/move`

Persists a hand-repositioned marker so the render reads the moved coordinates (today drag would be silently ignored — the render uses original density coordinates).

**Request (form-encoded, matching the other marker endpoints):**
- `session_id: str`
- `i: int` — hotspot index
- `px: float`, `py: float` — new position in overview pixels

**Behavior:**
- Resolve the session (`_require_session`), validate `0 <= i < len(hotspots)`.
- Convert overview px → CRS via `overview_px_to_crs` (the existing geo helper).
- **Clamp** the CRS point to the region bounds; if the point is outside region bounds, reject with `422` (consistent with the density/zoom-cap error style).
- Write `hotspots[i]["x"]`, `hotspots[i]["y"]`; `session.update(session_id, hotspots=..., spec=None)` — invalidating the stamped spec exactly as label/icon/photo edits already do, so the next proof reflects the move.
- Return `{"ok": True}` plus the clamped `{"px","py"}` so the client can snap the dot to the clamped position.

**Out-of-crop cue (frontend):** `render._draw_markers` already skips markers outside the crop. So a marker dragged outside the eventual crop would silently vanish from the poster. The Frame/Proof view must show a cue (e.g., a muted "outside frame" state on that side-list row) when a marker's position falls outside the current crop.

---

## 7. Cross-cutting concerns

### Theming
Night (dark) and Day (light) palettes, with a header toggle whose choice persists in `localStorage`. Palettes derive from the exported Badwater design tokens (`_ds/.../tokens/colors.css`: dark is default `:root`, light under `[data-color-scheme="light"]`). The toggle restyles the whole UI; it does not change the rendered poster. Build this **last** — it is locked but adds no output value and should not gate the redesign.

### Accessibility (targeted, low-effort wins only)
- Fix stepper text contrast (the mockup's grey-on-black step labels fail WCAG AA).
- `aria-current="step"` on the active step; do not rely on color alone to signal the active step.
- Move focus to the new step's heading on transition.
- Keep the marker side-list of real form controls as the accessible marker surface (this is the single most clarity-forward element and must not be replaced by map-only popovers).
- Explicitly out of scope: a fully keyboard-operable crop canvas and aria-live announcements on the spatial widgets (deferred; high effort, low yield for a sighted single operator whose clients watch rather than operate).

### Clear / start-over safety
The global "Clear" becomes a confirmed "Start over" that lives only on the Region step (or an overflow), confirms when there is real work to lose, and keeps uploaded photos on disk until session end. The stepper's click-back already covers the common "redo the crop" intent, so Clear no longer needs to be persistent chrome on every step.

---

## 8. Scope

### Build now
1. Region step: real gallery + value line + auto-skip at ≤1 region + last-region memory.
2. Tracks & Places merged: drop-zone empty state, accumulating file list, side-list kept, drag-to-move.
3. `POST /api/markers/move` endpoint (with bounds clamp + out-of-crop cue).
4. Frame: starter crop, crop-draw geometry fix, print-size re-fit, reset/escape, red-tint + humanized 422.
5. Proof: reframe button, stale-proof guard, existing poll loop.
6. Single nav paradigm (named primary buttons + stepper click-back).
7. Targeted a11y wins (contrast, `aria-current`, focus-on-heading).
8. Night/Day theme toggle, persisted (last).

### Defer
Cross-region auto-recovery; full keyboard/ARIA canvas; async poll timeout; express proof+accept; anything photo-gating.

---

## 9. Testing

**New backend tests (pytest):**
- `POST /api/markers/move`: happy path writes new x/y and sets `spec=None`; a point inside bounds is accepted; a point outside region bounds is clamped or `422` per the contract; invalid `i` → error.
- Starter-crop helper: given a region + tracks, the computed starter crop matches the print aspect and sits at or above the zoom-cap floor (never produces an on-entry `ZoomTooTightError`).

**Existing suite:** stays green (`pytest -q`).

**Frontend (run-the-app verification):** crop-draw normalization in all four directions, marker drag + persistence, region auto-skip, empty-state visibility, theme toggle. Verified by launching the app and driving it, not by unit test (no frontend test harness in v1).

---

## 10. Invariants preserved

- **One spec, many sizes:** proof and final still render from the identical stamped `CompositionSpec`. `/api/markers/move` invalidates the spec (`spec=None`) rather than mutating a stamped one, so the next proof re-stamps.
- **Physical units / determinism / one projection / registration / zoom cap:** untouched — all rendering stays server-side through the existing engine. The starter crop is explicitly designed to respect the zoom cap on entry.

---

## 11. Open questions

- **Starter-crop fraction:** what fraction of region extent centered on the track centroid gives the best default framing across both regions? To be tuned by eye during implementation (the render loop is fast). Default proposal: size the crop so the tracks occupy roughly the middle third, then clamp to aspect + floor.
- **Merged-step layout:** exact placement of the side-list relative to the map on the Tracks & Places step (right pane vs. below) — to be settled visually against the design tokens during build.
