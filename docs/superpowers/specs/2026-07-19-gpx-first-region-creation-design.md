# GPX-First Flow with In-App Region Creation — Design

**Date:** 2026-07-19
**Status:** Approved by Dom (brainstorming session)
**Branch:** `gpx-first-flow` (stacked on `macos-launcher-app` — depends on the Tecopa Printworks rebrand)

## Goal

Invert the wizard: the user drops GPX tracks first, and the region is an *outcome* —
matched when a built plate covers the tracks, **created in-app** when none does. The
region gallery stops being a step and becomes a build-artifact browser.

## Why (the reframe from brainstorming)

The five existing plates exist only because they cover Dom's own test tracks. In real
use — client tracks — uploads will usually land **outside every built plate**, so the
"no plate" case is the *common* case, not an error. The backend is already GPX-first:
`region_id` is optional on upload, `_best_region()` auto-matches from track bounds,
and auto-recovery switches regions when a pre-pick was wrong (`app/main.py:291-320`).
The engine also already has the creation machinery as an offline CLI: `region_prep.py
--id --name --bbox --epsg` with an automatic resolution planner that **prints its cost
plan before fetching anything**, memory-bounded slice fetching, and a separate heavy
venv (`.venv-prep`, per `requirements-regionprep.txt`). This design connects those
two facts with UI.

## Decisions (from brainstorming)

1. **Scope:** drop-first entry + region reveal + in-app creation. (Auto-proof preview,
   sample-tracks demo, and a dedicated no-match graticule map were explicitly cut.)
2. **Creation depth:** fully in-app, behind a cost card — not a guided-terminal
   handoff, not deferred.
3. **Naming:** one editable name field on the cost card, prefilled from the GPX file's
   own `<name>` metadata when present; the region id is slugified from it.
4. **Pipeline architecture:** the engine spawns `region_prep.py` as a **subprocess in
   `.venv-prep`** via the existing job queue (Approach A). The heavy fetch stack
   (py3dep/pynhd/pandas/geopandas) never enters the app venv. In-process imports and
   a sidecar daemon were considered and rejected.

## Flow design

### 1. Entry & re-sequencing

- The dropzone is screen one: "Drop your GPX, KML or KMZ", with "Continue a poster…"
  beneath it. `state.steps` becomes `['tracks', 'frame', 'proof']`; the Region step
  and its stepper entry are removed. Precedent already in the code: the wizard
  auto-skips the Region step when ≤1 region exists (`app/static/app.js:137`).
- The region-gallery pane is deleted as a step. A quiet **"Built plates"** link on the
  entry screen opens the gallery read-only (browse what exists; plates are artifacts
  now, not choices).
- "Start over" returns to the empty dropzone.

### 2. Match path

Upload runs exactly as today. When `_best_region` matches, the workspace opens with a
**reveal chip** beside the region name in the toolbar: "Matched · Tushar Mountains,
Utah". No plate-override picker (with in-app creation, wrong-plate cases essentially
vanish; the auto-recovery path still protects a stale pre-pick from a continued
poster).

### 3. No-match path: the cost card

On the 422 ("Tracks don't fall within any available region") the UI **keeps the
dropped File objects client-side** and shows the creation card instead of an error.

New endpoint `POST /api/regions/plan` (multipart, same track payloads):
- Parses tracks (existing ingest), derives the bbox: track bounds in lon/lat padded
  **~20% per side with a 3 km floor**, so later crops have composition room.
- Picks the UTM zone EPSG from the bbox centroid.
- Pre-checks the bbox against US 3DEP coverage (CONUS/AK/HI envelope). Outside → an
  honest "USGS 3DEP covers US terrain only" response; the card shows that message
  (no Build button).
- Runs `plan_build()` — pure logic, importable without the fetch stack — and returns:
  area, chosen resolution (10/30/60 m), grid px, estimated DEM size, slice count.
- Returns the name prefill (first GPX `<name>` found, else empty) and the slugified
  id with a collision check against existing region ids (collision → suffix `_2` etc.).

The card shows the estimate + the name field + one primary button **"Build this
region"**. If `.venv-prep/bin/python` does not exist, the button is replaced by the
two setup commands (`python3 -m venv .venv-prep && …pip install -r
requirements-regionprep.txt`), honestly.

### 4. The build job

New endpoint `POST /api/regions/build` `{id, name, bbox, epsg}`. The client's plan
response is untrusted input, so the server re-validates: the US-3DEP envelope check
and slug rules re-run server-side, and `plan_build()` re-runs — a bbox whose grid is
`over_budget` even at 60 m is **rejected** with an honest message (that's
corridor-scale territory; the operator can still build it deliberately via the CLI).
- Enqueues on a **dedicated** `ThreadJobQueue(max_concurrency=1)` instance for
  builds — NOT the shared render `QUEUE` — so a multi-minute build never blocks
  poster renders, and `TECOPA_RENDER_CONCURRENCY` can't break the one-build-at-a-time
  guarantee. The job record gains a `progress: str` field; the worker updates it
  under the queue's existing lock.
- The worker spawns `.venv-prep/bin/python region_prep.py --id … --name … --bbox …
  --epsg …` with cwd = repo root, streaming its stdout (which already narrates
  plan → slice fetches → hydro → overview) line-by-line into `progress`.
- Then runs `scripts/build_labels.py <id>` (same venv-prep interpreter). Labels
  failure is **non-fatal**: the region works without place names; the job result
  carries a note the card displays.
- Then hot-reloads the registry in place: `REGIONS.clear();
  REGIONS.update(regions.discover(REGIONS_ROOT))` (other modules hold the dict
  reference, so in-place mutation is required, not rebinding).
- `GET /api/regions/build/{job}` polls state + progress (mirrors the render-job
  pattern).
- **Failure at the prep stage:** job state `error`, last ~10 stdout/stderr lines
  surfaced on the card, and the partial `regions/<id>/` directory **removed** so a
  retry starts clean.

### 5. After the build

The card streams progress while polling. On `done`, the UI re-uploads the kept File
objects — they now match the new plate — and the workspace opens with the chip
reading "Built · <name>". Flow from there is unchanged (Tracks → Frame → Proof).

## Error handling summary

| Case | Behavior |
|---|---|
| Tracks outside US 3DEP coverage | Card explains US-only terrain, no Build button |
| `.venv-prep` missing | Card shows setup commands instead of Build |
| Slug collision with existing region | Auto-suffix at plan time; re-checked at build time (409 on race) |
| Bbox over budget even at 60 m | Build endpoint rejects with an honest message (CLI remains the deliberate path) |
| prep subprocess fails / network dies | Job error + last output lines on card; partial region dir removed |
| `build_labels.py` fails | Non-fatal; note on card, region proceeds |
| Second build submitted while one runs | Queued (existing semaphore); card shows "queued" |
| Engine restarted mid-build | Job record lost (in-memory queue); partial dir swept on next build of same id; acceptable for single-operator v1 |

## Out of scope

Plate-override picker, auto-proof render after drop, sample-tracks demo, packing
built regions into `.trailplate.zip` (release machinery), non-US terrain sources,
deleting/managing built plates from the UI, persisting build jobs across restarts.

## Testing / verification

- **Unit (pure, CI):** bbox padding + floor derivation, UTM zone selection, US
  envelope check, slug/collision logic — pure functions, fixture tracks.
- **Endpoint (CI):** `/api/regions/plan` against fixture GPX (in-bounds → estimate;
  out-of-US → honest refusal; missing venv-prep flagged via an env override so CI
  can simulate both).
- **Orchestration (CI, no network):** `/api/regions/build` with the prep command
  stubbed by a fake script that writes a synthetic region (same trick as
  `tests/conftest.py`'s synthetic DEM hydration) — exercises progress streaming,
  labels non-fatality, hot-reload, failure cleanup.
- **Acceptance (manual, once):** one real build of a small bbox (~10 km trail),
  end-to-end from drop to proof.
