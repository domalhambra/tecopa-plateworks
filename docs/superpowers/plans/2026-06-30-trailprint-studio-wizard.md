# TrailPrint Studio — Guided Wizard UI Refinement — Implementation Plan

> **For agentic workers:** Implement this plan task-by-task. Backend tasks are TDD (failing test → see it fail → minimal impl → green → commit). Frontend tasks are a coherent module rewrite verified by run-the-app (no frontend unit harness in v1). Steps use checkbox (`- [ ]`) syntax for tracking.

**Source spec:** `docs/superpowers/specs/2026-06-30-trailprint-studio-wizard-design.md` (red-teamed, approved).

**Goal:** Rewrite `app/static/*` into a guided 4-step wizard (Region → Tracks&Places → Frame → Proof) that reads clearly to a first-time viewer without slowing the repeat operator, add one backend endpoint (`POST /api/markers/move`) and a tested starter-crop helper, and honor all six build-plan invariants. The render engine and every other API stay unchanged.

**Architecture:** Frontend stays vanilla JS, no build step, split into focused ES modules loaded via `<script type="module">`: `state.js` (state + localStorage), `api.js` (fetch wrappers), `canvas.js` (drawing + crop/drag pointer interactions), `markers.js` (side-list + sync), `app.js` (bootstrap + step machine). Backend adds `POST /api/markers/move` and a pure `starter_crop` helper surfaced in the `/api/upload` response. Region data (DEM, hydro) is still read from the region dir by `render`, never carried on the spec. Marker moves and crop changes invalidate the stamped spec (`spec=None`), never mutate a stamped one (invariant 1).

**Tech stack:** Python 3.11+ (this remote env; Dom's Mac is 3.14 — both fine), FastAPI + TestClient, Pillow/numpy/pyproj/shapely/rasterio. Frontend: vanilla ES modules, Canvas 2D. Tests: pytest.

**Conventions (this repo):**
- venv at `.venv`; run `./.venv/bin/python -m pytest tests/ -q`.
- The full render suite is DEM-gated: modules that rasterize carry `pytestmark = pytest.mark.skipif(not os.path.exists("regions/lassen_ca/dem.tif"), ...)` and SKIP on a fresh clone (the ~190 MB DEM is gitignored and rebuilt by `region_prep.py`). New tests that need no DEM go in a **non-gated** module so they run in CI; tests that must stamp a spec (needs `/api/proof` → DEM) go in the gated `tests/test_main.py`.
- The two region-prep test modules (`test_hydro.py`, `test_region_prep.py`) need `py3dep`/`geopandas` and are out of scope here; run with `--ignore` for both locally if those deps are absent.
- Commit messages: present-tense subject, body explains the *why*, end with the `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer. Granular commits, green before each.
- Branch: `claude/trailprint-wizard-implementation-3esxfl`.

**Facts locked from the codebase (do not re-derive):**
- **Zoom cap (`spec.validate(dpi)`):** raises `ZoomTooTightError(f"{ground_per_pixel:.1f} m/px requested, data floor is {native_resolution_m} m/px")` when `ground_per_pixel(dpi) < native_resolution_m`, where `ground_per_pixel = (crop_max_x - crop_min_x) / round(print_w_in * dpi)`. The check is strict `<`, so requested == floor passes. **Minimum crop ground-width to pass** = `native_resolution_m * round(print_w_in * dpi)`. At dpi=300, native=10 m: 18×24 → **54 000 m**, 24×36 → 72 000 m, 12×16 → 36 000 m, 9×12 → 27 000 m. Only print *width* enters the cap. The web app validates at `FINAL_DPI = 300` (proof time), so the starter crop must clear the 300-dpi floor.
- **Regions (concrete numbers for tests):** `lassen_ca` — EPSG:32610, bounds `(663529.83, 4447315.73, 726539.83, 4525515.73)`, width 63 010 m × height 78 200 m, overview `[1128, 1400]` px, native 10 m (≈55.86 m/overview-px). `susanville_reno` — bounds `(697012.91, 4386976.98, 760722.91, 4485346.98)`, 63 710 × 98 370 m, overview `[906, 1400]` px. **Note:** on `lassen_ca` (63 010 m wide) the 24×36 floor (72 000 m) exceeds region width → 24×36 cannot satisfy the cap there; 18×24 fits with room. Default print size is 18×24.
- **Geo (`app/geo.py`, all take a `RegionGeo`):** `crs_to_overview_px(region, x, y)`, `overview_px_to_crs(region, px, py)` (inverse), `crop_px_to_crs_window(region, x0, y0, x1, y1) → (min_x, min_y, max_x, max_y)`, `lonlat_to_crs(region, lon, lat)`. Overview px is (near-)isotropic: `metres_per_px = (max_x-min_x)/overview_w ≈ (max_y-min_y)/overview_h`.
- **Marker out-of-crop skip (`render._draw_markers`):** a marker is dropped from the poster iff its CRS point maps outside the crop window — equivalently `not (crop_min_x ≤ x ≤ crop_max_x and crop_min_y ≤ y ≤ crop_max_y)`. The frontend "outside frame" cue replicates this test against the current crop's CRS window.
- **`/api/upload` today** returns `{session, region, name, overview, overview_size, tracks (overview-px polylines), hotspots [{px,weight,label,icon,photo}]}` and sets `spec=None` on re-upload. Hotspots carry CRS `x`/`y` server-side (from `density.hotspots`).
- **Marker endpoints are form-encoded**; `_require_session(sid)` → 404; `set_photo` uses `422` for "marker index out of range". No `/api/markers/move` exists yet.
- **Design tokens** exported at `docs/trails for claude design/TrailPrint UI refinement/_ds/badwater-hd-design-system-*/tokens/colors.css`: dark under `:root`, light under `:root[data-color-scheme="light"]`. Core UI tokens to mirror into `app/static/tokens.css`: `--color-contrast`, `--color-foreground`, `--color-muted`, `--color-background[/-100/-200/-300]`, `--surface-elevated`, `--color-border[-strong]`, `--color-accent`(terracotta), `--color-accent-gold`, `--color-success`, `--color-warning`, `--color-error`, `--card-shadow`. Mockup screenshots (`screenshots/s1..s7`) and `TrailPrint Studio.dc.html` are the visual reference.

---

## Task 1: `POST /api/markers/move` endpoint (TDD)

Persist a hand-dragged marker so the render reads the moved coordinates (today a drag would be silently ignored). Clamp out-of-bounds to region bounds (forgiving); `422` reserved for a bad index. Invalidate the stamped spec.

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_markers_move.py` (non-gated — needs no DEM)
- Modify: `tests/test_main.py` (one gated spec-invalidation test)

- [ ] **Step 1: Failing non-gated tests** — `tests/test_markers_move.py`. Mirror `tests/test_markers.py` scaffolding (no DEM skip). Upload `tests/fixtures/sample.gpx` (upload needs no DEM), grab `session`, then exercise `/api/markers/move`:

```python
import os
import pytest
from fastapi.testclient import TestClient

def _client():
    from app.main import app
    return TestClient(app)

def _upload(c):
    files = [("files", ("a.gpx", open("tests/fixtures/sample.gpx", "rb").read(), "application/gpx+xml"))]
    r = c.post("/api/upload", files=files)
    assert r.status_code == 200
    return r.json()

def test_move_returns_ok_and_snapped_px():
    c = _client(); j = _upload(c)
    w, h = j["overview_size"]
    r = c.post("/api/markers/move", data={"session_id": j["session"], "i": 0,
               "px": w * 0.5, "py": h * 0.5})
    assert r.status_code == 200
    out = r.json()
    assert out["ok"] is True
    # a point well inside bounds round-trips unchanged (linear px<->crs map)
    assert abs(out["px"] - w * 0.5) < 1e-6
    assert abs(out["py"] - h * 0.5) < 1e-6

def test_move_clamps_out_of_bounds():
    c = _client(); j = _upload(c)
    w, h = j["overview_size"]
    r = c.post("/api/markers/move", data={"session_id": j["session"], "i": 0,
               "px": -500.0, "py": h + 500.0})
    assert r.status_code == 200
    out = r.json()
    # clamped back onto the region edge -> returned px/py inside [0, w]x[0, h]
    assert -1e-6 <= out["px"] <= w + 1e-6
    assert -1e-6 <= out["py"] <= h + 1e-6
    assert out["px"] > -500.0 and out["py"] < h + 500.0   # actually moved

def test_move_bad_index_422():
    c = _client(); j = _upload(c)
    r = c.post("/api/markers/move", data={"session_id": j["session"], "i": 999,
               "px": 10.0, "py": 10.0})
    assert r.status_code == 422

def test_move_unknown_session_404():
    c = _client()
    r = c.post("/api/markers/move", data={"session_id": "nope", "i": 0, "px": 1.0, "py": 1.0})
    assert r.status_code == 404
```

- [ ] **Step 2: Failing gated spec-invalidation test** — append to `tests/test_main.py` (DEM-gated; proves `spec=None` after a stamped proof):

```python
def test_move_marker_invalidates_spec():
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 200          # stamp a spec
    w, h = j["overview_size"]
    r = c.post("/api/markers/move", data={"session_id": j["session"], "i": 0,
               "px": w * 0.5, "py": h * 0.5})
    assert r.status_code == 200
    # spec invalidated -> final must 400 ("Approve a proof first")
    assert c.post("/api/final", data={"session_id": j["session"]}).status_code == 400
```

- [ ] **Step 3: Run, verify fail** — `./.venv/bin/python -m pytest tests/test_markers_move.py -q` → FAIL (endpoint 404/405). (`test_main.py` case is skipped without a DEM; that's fine.)

- [ ] **Step 4: Implement** in `app/main.py`, after `set_photo`, reusing the existing helpers and imports (add `overview_px_to_crs, crs_to_overview_px` to the `from app.geo import ...` line):

```python
@app.post("/api/markers/move")
async def move_marker(session_id: str = Form(...), i: int = Form(...),
                      px: float = Form(...), py: float = Form(...)):
    """Persist a hand-dragged hotspot. Convert overview px -> CRS, clamp to region
    bounds (never reject: 'snap the dot'), write x/y, invalidate the stamped spec so
    the next proof reflects the move. Returns the clamped position back in overview px."""
    st = _require_session(session_id)
    spots = st["hotspots"]
    if not (0 <= i < len(spots)):
        raise HTTPException(422, "marker index out of range")
    region = _region_or_404(st["region_id"])                 # geo lives on the region
    x, y = overview_px_to_crs(region.geo, px, py)
    min_x, min_y, max_x, max_y = region.cfg["bounds"]
    x = min(max(x, min_x), max_x)                             # clamp, don't reject
    y = min(max(y, min_y), max_y)
    spots[i]["x"], spots[i]["y"] = x, y
    session.update(session_id, hotspots=spots, spec=None)     # re-proof to apply
    cpx, cpy = crs_to_overview_px(region.geo, x, y)           # snap-back position
    return {"ok": True, "px": cpx, "py": cpy}
```

- [ ] **Step 5: Run, verify pass** — `./.venv/bin/python -m pytest tests/test_markers_move.py -q` → PASS. Full non-gated suite green: `./.venv/bin/python -m pytest tests/ -q --ignore=tests/test_hydro.py --ignore=tests/test_region_prep.py`.

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_markers_move.py tests/test_main.py
git commit -m "API: POST /api/markers/move persists dragged hotspot (bounds-clamped, invalidates spec)"
```

---

## Task 2: Starter-crop helper + `/api/upload` returns `starter_crop` (TDD)

A pure helper that computes a generous default crop centered on the tracks, aspect-locked to the print size, clamped to region bounds, and guaranteed at/above the zoom-cap floor so "Render proof" never trips the cap on entry. Surface it in the upload response so the Frame step draws it as the single source of truth (frontend does only a lightweight aspect re-fit on print-size change).

**Files:**
- Modify: `app/geo.py` (add `starter_crop`)
- Modify: `app/main.py` (`/api/upload` includes `starter_crop`)
- Create: `tests/test_starter_crop.py` (non-gated)

- [ ] **Step 1: Failing tests** — `tests/test_starter_crop.py`:

```python
from app.geo import RegionGeo, starter_crop, crop_px_to_crs_window

LASSEN = RegionGeo(crs="EPSG:32610",
                   bounds=(663529.83, 4447315.73, 726539.83, 4525515.73),
                   overview_size=(1128, 1400))

def _tracks_px():
    # a tight cluster near region center (overview px), the hard case for the cap
    cx, cy = 1128 * 0.5, 1400 * 0.5
    return [[[cx - 20, cy - 20], [cx + 20, cy + 25], [cx + 10, cy - 15]]]

def test_starter_crop_matches_print_aspect_and_clears_floor():
    x0, y0, x1, y1 = starter_crop(LASSEN, _tracks_px(), 18, 24,
                                  native_resolution_m=10, dpi=300)
    # crop is a valid overview-px box, ordered, inside the overview
    assert 0 <= x0 < x1 <= 1128 and 0 <= y0 < y1 <= 1400
    win = crop_px_to_crs_window(LASSEN, x0, y0, x1, y1)          # CRS metres
    ground_w = win[2] - win[0]
    # zoom cap: ground_per_pixel(300) = ground_w / round(18*300) >= 10
    assert ground_w / round(18 * 300) >= 10.0 - 1e-6
    # aspect (CRS metres) locked to the print aspect 18/24 within a small tolerance
    ground_h = win[3] - win[1]
    assert abs((ground_w / ground_h) - (18 / 24)) < 0.02

def test_starter_crop_is_centered_on_tracks():
    x0, y0, x1, y1 = starter_crop(LASSEN, _tracks_px(), 18, 24, native_resolution_m=10, dpi=300)
    cx = (x0 + x1) / 2; cy = (y0 + y1) / 2
    assert abs(cx - 1128 * 0.5) < 60 and abs(cy - 1400 * 0.5) < 60   # near track centroid

def test_starter_crop_clamps_into_region():
    # tracks near an edge: the aspect box must slide inside, never spill out
    tracks = [[[40, 40], [70, 90]]]
    x0, y0, x1, y1 = starter_crop(LASSEN, tracks, 18, 24, native_resolution_m=10, dpi=300)
    assert 0 <= x0 < x1 <= 1128 and 0 <= y0 < y1 <= 1400
```

- [ ] **Step 2: Run, verify fail** — `./.venv/bin/python -m pytest tests/test_starter_crop.py -q` → FAIL (`starter_crop` missing).

- [ ] **Step 3: Implement `starter_crop` in `app/geo.py`.** Work in CRS metres (the cap is metres-exact), then map to overview px:

```python
def starter_crop(region: RegionGeo, tracks_px, print_w_in, print_h_in,
                 native_resolution_m, dpi=300, track_fraction=1/3):
    """A generous default crop (overview px) for the Frame step: centered on the track
    centroid, aspect-locked to the print size, clamped to region bounds, and >= the
    zoom-cap floor at `dpi` so the first proof never trips ZoomTooTightError.

    tracks_px: list of polylines in overview pixels (as returned by /api/upload).
    Returns (x0, y0, x1, y1) in overview pixels, ordered."""
    min_x, min_y, max_x, max_y = region.bounds
    reg_w, reg_h = max_x - min_x, max_y - min_y
    aspect = print_w_in / print_h_in                      # width / height

    # track centroid + span, converted to CRS metres
    pts = [p for t in tracks_px for p in t]
    xs = [overview_px_to_crs(region, px, py)[0] for px, py in pts]
    ys = [overview_px_to_crs(region, px, py)[1] for px, py in pts]
    if pts:
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        span_w = (max(xs) - min(xs)) / track_fraction     # tracks ~ middle third
        span_h = (max(ys) - min(ys)) / track_fraction
    else:
        cx, cy = (min_x + max_x) / 2, (min_y + max_y) / 2
        span_w = span_h = 0.0

    floor_w = native_resolution_m * round(print_w_in * dpi)   # cap floor, metres
    # target width: max of (track-driven, aspect-fit of track height, cap floor),
    # then clamp to what the region can hold
    w = max(span_w, span_h * aspect, floor_w)
    w = min(w, reg_w, reg_h * aspect)                     # fit inside the region box
    h = w / aspect
    if h > reg_h:                                         # aspect vs region: refit on height
        h = reg_h; w = h * aspect

    # center, then slide the box fully inside region bounds
    x0 = min(max(cx - w / 2, min_x), max_x - w)
    y0 = min(max(cy - h / 2, min_y), max_y - h)
    win = (x0, y0, x0 + w, y0 + h)                        # (min_x, min_y, max_x, max_y) CRS
    # map CRS window -> overview px (note y flips)
    px0, py0 = crs_to_overview_px(region, win[0], win[3])   # top-left
    px1, py1 = crs_to_overview_px(region, win[2], win[1])   # bottom-right
    return (min(px0, px1), min(py0, py1), max(px0, px1), max(py0, py1))
```

Note: when `floor_w` exceeds region width (e.g. 24×36 on `lassen_ca`) the `min(w, reg_w, ...)` clamp caps at the region — the crop then falls *below* the floor and a real proof would 422 with the humanized message (Task 5); this is a genuine "region too small for that size," not a helper bug. The default 18×24 always clears the floor on both current regions.

- [ ] **Step 4: Wire into `/api/upload`.** After computing `tpx`, add the default-size starter crop to the response dict:

```python
    start = starter_crop(region.geo, tpx, 18, 24,
                         native_resolution_m=region.cfg["native_resolution_m"])
    return {"session": sid, "region": region.id, "name": region.name,
            "overview": f"/regions/{region.id}/overview.png",
            "overview_size": region.cfg["overview_size"],
            "tracks": tpx, "hotspots": hpx, "starter_crop": start}
```

(Add `starter_crop` to the `from app.geo import ...` line.)

- [ ] **Step 5: Run, verify pass** — `./.venv/bin/python -m pytest tests/test_starter_crop.py -q` → PASS. Add one non-gated assertion to `tests/test_markers_move.py`/upload test or a small check that `/api/upload` includes `starter_crop` with a valid ordered box (upload needs no DEM). Full non-gated suite green.

- [ ] **Step 6: Commit**

```bash
git add app/geo.py app/main.py tests/test_starter_crop.py
git commit -m "Geo: starter_crop helper (aspect-locked, floor-safe, clamped) surfaced on /api/upload"
```

---

## Task 3: Frontend skeleton — `state.js`, `api.js`, new `index.html` shell, `tokens.css` + base `style.css`

Stand up the module skeleton and the wizard chrome (left-rail stepper + header + step panes) that the interaction tasks fill in. No behavior regressions: after this task the page loads, shows the stepper, and the Tracks empty-state drop zone.

**Files:**
- Create: `app/static/state.js`, `app/static/api.js`, `app/static/tokens.css`
- Rewrite: `app/static/index.html`
- Rewrite: `app/static/style.css`

- [ ] **Step 1: `tokens.css`** — mirror the exported Badwater core UI tokens: dark under `:root`, light under `:root[data-color-scheme="light"]` (values from the facts block above). One `--tp-accent` alias (default `var(--color-accent-gold)`) drives wizard accents so a later switch is one line.

- [ ] **Step 2: `state.js`** — a single exported `state` object plus persistence:

```js
export const state = {
  step: 'tracks', steps: ['region','tracks','frame','proof'],
  session: null, region: null, regionName: '', regions: [],
  ovSize: null, scale: 1, tracks: [], hotspots: [],
  crop: null, starterCrop: null, printW: 18, printH: 24,
  proofStale: false, hasSpec: false, files: [],
};
const LS = 'trailprint';                       // {region, printSize, theme}
export function loadPrefs() { try { return JSON.parse(localStorage.getItem(LS)) || {}; } catch { return {}; } }
export function savePref(k, v) { const p = loadPrefs(); p[k] = v; localStorage.setItem(LS, JSON.stringify(p)); }
```

- [ ] **Step 3: `api.js`** — thin typed `fetch` wrappers for every endpoint used: `getRegions()`, `upload(files, {sessionId, regionId})`, `setMarkers(sid, markers)`, `uploadPhoto(sid, i, file)`, `moveMarker(sid, i, px, py)`, `proof(sid, crop, printW, printH)` (returns a Blob or throws `{status, message}`), `submitFinal(sid)`, `jobStatus(jid)`, `jobResultBlob(url)`. Each throws a typed `ApiError` carrying `status` + server text so callers can humanize (e.g. the 422 zoom message).

- [ ] **Step 4: `index.html`** — module entry + wizard layout:
  - `<link rel="stylesheet" href="tokens.css">` then `style.css`; `<script type="module" src="app.js"></script>`.
  - `<header>`: title, region name, a **theme toggle** button (wired in Task 7), and a Start-over affordance (wired in Task 6).
  - Left-rail `<nav id="stepper">` (built by `app.js`): one row per active step, circle + "Step N" eyebrow + label, connectors, `aria-current` on active.
  - A main `<section id="stage">` with per-step panes: `#pane-region` (gallery + value line), `#pane-tracks` (map canvas + drop-zone overlay + side-list host + "Add more files" + file chips), `#pane-frame` (print-size select + map canvas + Reset frame + hint + primary button), `#pane-proof` (proof image + Reframe + Accept). One consistently placed **primary button** per pane, plus a `#hint` pill region and a `#status` line.
  - Keep the accessible marker **side-list** host (`#markerList`) — real form controls, not map popovers.

- [ ] **Step 5: base `style.css`** — restyle entirely from tokens (`var(--color-*)`), no hard-coded hex except inside the canvas. Stepper contrast passes WCAG AA (active label `--color-contrast`, others `--color-muted`, never grey-on-black). Dashed drop zone, hint pill, file chips, side-list rows, poster pane with card shadow.

- [ ] **Step 6: Verify load** — `./.venv/bin/uvicorn app.main:app` (background); open `/`; confirm the page renders the stepper + Tracks drop-zone empty state with no console errors. (Region auto-skip / full flow land in Task 6.) This is a coherent-skeleton checkpoint; deeper drive is Task 8.

- [ ] **Step 7: Commit**

```bash
git add app/static/
git commit -m "Web UI: wizard skeleton — token-driven theme, ES-module split (state/api), stepper shell + step panes"
```

---

## Task 4: `canvas.js` — drawing, crop-draw geometry fix, marker drag-to-move, starter crop, print-size re-fit

All canvas drawing and the two pointer interactions (crop-draw on Frame, marker-drag on Tracks). Fixes the inverted-crop bug and lands drag-to-reposition with persistence.

**Files:**
- Create: `app/static/canvas.js`
- Modify: `app/static/app.js` (wire draw + interaction handlers per step)

- [ ] **Step 1: Drawing** — `drawTracks()` renders the overview image, track polylines, gold hotspot dots (r≈6), the crop box (Frame only), and on-map **label pills** for named markers (cream plate, per the mockup). `ovToCanvas`/`canvasToOv` use `state.scale`.

- [ ] **Step 2: Crop-draw geometry fix (all four directions).** Replace the current `dragStart`-as-top-left logic (`app.js:156–160`, which inverts when dragging up/left). Normalize with min/max and derive the aspect-locked height on the correct side:

```js
// pointer-move while drawing a crop:
const ar = state.printW / state.printH;
const x0 = Math.min(startX, curX), x1 = Math.max(startX, curX);
let w = x1 - x0;
let h = w / ar;
// grow up or down depending on drag direction
const y0 = (curY < startY) ? (startY - h) : startY;
state.crop = [x0, y0, x0 + w, y0 + h];
```

Clamp the box to the canvas. **Escape** cancels an in-progress drag (restore the prior crop, stop tracking).

- [ ] **Step 3: Starter crop on Frame entry.** On entering Frame, set `state.crop` from `state.starterCrop` (overview px → canvas px). "Reset frame" restores the starter crop (clears only the crop, not the session).

- [ ] **Step 4: Print-size re-fit.** Changing the size select updates `state.printW/H`, persists it (`savePref('printSize', ...)`), and re-fits the existing crop *in place*: keep center, re-lock to the new aspect, grow to the new size's floor when the region allows, clamp to bounds. Never leave a stale aspect mismatch. Floor in overview px = `native_resolution_m * round(printW*300) / metresPerOverviewPx`, where `metresPerOverviewPx = (max_x-min_x)/overview_w` from the region's `bounds` (available via `state.regions`).

- [ ] **Step 5: Zoom-cap red tint during drag.** While drawing/refitting, if the crop's ground width is below the floor, tint the crop stroke/fill red (`var(--color-error)`); otherwise gold. Pure client-side check using `metresPerOverviewPx`.

- [ ] **Step 6: Marker drag-to-reposition (Tracks step).** Hit-test pointer-down against hotspot dots (hit radius ~ dot radius in canvas px). If the pointer moves beyond a small threshold before up, it is a drag: live-move the dot, and on pointer-up call `api.moveMarker(sid, i, ovPx, ovPy)`, then snap the dot to the returned clamped `{px,py}` and set `state.proofStale = true`. The side-list stays the unambiguous identity-edit path, so the map handles *move only* (no click-vs-drag ambiguity on the dot). First-hover shows a self-retiring "Drag a marker to reposition it" secondary tip.

- [ ] **Step 7: Verify (run-the-app, Task 8 covers depth)** — crop grows correctly dragging in all four directions; marker drag persists (Network shows `/api/markers/move` 200) and snaps; size change re-fits. No DEM needed for any of this.

- [ ] **Step 8: Commit**

```bash
git add app/static/canvas.js app/static/app.js
git commit -m "Web UI canvas: 4-direction crop-draw fix, starter crop, floor-aware size re-fit, marker drag-to-move"
```

---

## Task 5: `markers.js` — side-list, sync, out-of-crop cue

The accessible marker side-list (kept, unchanged in spirit) plus the "outside frame" cue so a marker dragged/clamped outside the current crop doesn't silently vanish from the poster.

**Files:**
- Create: `app/static/markers.js`
- Modify: `app/static/app.js` (render side-list on Tracks/Frame; refresh cue when the crop changes)

- [ ] **Step 1: Side-list rows** — one row per hotspot: a dot, a label `<input>` (placeholder `Marker N`), an icon `<select>` (dot/peak/camp/water/flag/camera/star), and an optional photo attach `<label><input type=file hidden></label>`. Tab-order sane, screen-reader-friendly. On change: update `state`, call `api.setMarkers` / `api.uploadPhoto`, set `state.proofStale = true`, and set status "re-render the proof to see it".

- [ ] **Step 2: Out-of-crop cue** — given the current crop's CRS window (from `crop_px_to_crs_window` math replicated in JS, or by mapping the canvas crop back through `metresPerOverviewPx`), mark a row `outside-frame` (muted style + "outside frame" chip) when its marker's CRS point falls outside `crop_min_x..max_x / min_y..max_y`, matching `render._draw_markers`'s skip. Recompute on every crop change and after a marker drag.

- [ ] **Step 3: Verify** — name a marker → row updates and proof flagged stale; drag a marker outside the crop on Frame → its side-list row shows "outside frame". No DEM needed.

- [ ] **Step 4: Commit**

```bash
git add app/static/markers.js app/static/app.js
git commit -m "Web UI markers: accessible side-list module + out-of-frame cue matching the render skip"
```

---

## Task 6: `app.js` — step machine, stepper, region flow, proof step, a11y, Start-over

The bootstrap and the single-nav paradigm that ties the modules together.

**Files:**
- Modify/finish: `app/static/app.js`

- [ ] **Step 1: Step machine** — `state.steps = ['region','tracks','frame','proof']`; `go(step)` swaps the visible pane, rebuilds the stepper, moves focus to the new pane's heading, sets `aria-current="step"`. Named **primary buttons** drive forward ("Continue to Tracks/Frame", "Render proof", "Accept & render final"); the **stepper allows click-back to any completed step only** (never forward). Editing a completed step preserves later work where the data still applies.

- [ ] **Step 2: Region flow + auto-skip + memory** — on load `getRegions()`. If ≤1 region: drop `region` from `state.steps`, auto-select the sole region, show its name in the header, start on `tracks`. If ≥2: show the Region pane (real gallery, value line "Turn your tracks into a shaded-relief poster."), pre-select the last-used region from `loadPrefs().region`, "Continue to Tracks" enabled once selected; a subsequent drop may still auto-resolve the region via the existing upload auto-detect. Persist the chosen region (`savePref('region', id)`).

- [ ] **Step 3: Tracks step** — empty-state dashed drop zone centered in the map pane ("Drop GPX / KML / KMZ here, or click to browse"). After upload: draw overview+tracks+hotspots, show "Add more files" + accumulating file chips, render the side-list (Task 5), set `state.starterCrop`. Verification-first hint: "Your tracks are on the map — the gold dots mark places you returned to most." Naming visibly optional. Primary: "Continue to Frame" (enabled once ≥1 track loaded).

- [ ] **Step 4: Frame step** — print-size select at top (default from `loadPrefs().printSize` else 18×24), starter crop drawn on entry, Reset frame, Escape-cancel, red-tint + the humanized 422 on a rejected proof: translate `"X m/px requested, data floor is Y"` → "This crop is too tight to print sharp at {W}×{H} — draw wider or pick a larger size." Primary: "Render proof" → `api.proof(...)`, on success show the PNG and `go('proof')`, set `state.hasSpec = true`, `state.proofStale = false`.

- [ ] **Step 5: Proof step** — show the framed proof (server already renders white border / title / PROOF watermark). Primary: "Accept & render final" → `submitFinal` then poll `jobStatus` with the **existing** queued/running/error/done loop and download on done (no client timeout). **Reframe** button → `go('frame')` with the crop preserved (one click). **Stale-proof guard:** any spec-invalidating edit (marker label/icon/photo/move or a crop change) sets `state.proofStale = true`; Accept then blocks with "re-render the proof first". Retry-after-failed-final only while `state.hasSpec && !state.proofStale`.

- [ ] **Step 6: a11y wins** — stepper contrast (Task 3), `aria-current="step"`, focus-to-heading on transition. Marker side-list stays the accessible marker surface.

- [ ] **Step 7: Start-over safety** — the global Clear becomes a confirmed "Start over" living on the Region step (or header overflow); confirm only when there's real work to lose; keep uploaded photos on disk until session end. Stepper click-back covers the common "redo the crop" intent, so Clear is no longer persistent chrome on every step.

- [ ] **Step 8: Verify (feeds Task 8)** — full click-through: auto-skip on the single-region clone, empty-state → upload → tracks → continue → frame (starter crop) → render proof (see note: proof render itself needs a DEM; verify wiring/humanized-error without one) → accept path wiring. Stepper back-nav preserves work; a11y focus moves.

- [ ] **Step 9: Commit**

```bash
git add app/static/app.js app/static/index.html
git commit -m "Web UI: step machine, region auto-skip + memory, single-nav stepper, proof reframe + stale guard, a11y"
```

---

## Task 7: Night/Day theme toggle, persisted (build last)

Locked but adds no output value, so it lands last and must not gate the redesign.

**Files:**
- Modify: `app/static/app.js`, `app/static/tokens.css`, `app/static/style.css`

- [ ] **Step 1: Toggle** — header button flips `document.documentElement` `data-color-scheme` between the default (dark/Night) and `light` (Day). Persist via `savePref('theme', ...)`; apply on load before first paint (avoid a flash). The toggle restyles the whole UI only; it never changes the rendered poster.

- [ ] **Step 2: Verify** — toggle flips Night↔Day, choice survives reload, contrast still passes in both, poster proof unchanged.

- [ ] **Step 3: Commit**

```bash
git add app/static/
git commit -m "Web UI: persisted Night/Day theme toggle from Badwater design tokens"
```

---

## Task 8: End-to-end verification, adversarial review, push, PR

- [ ] **Step 1: Full non-gated suite** — `./.venv/bin/python -m pytest tests/ -q --ignore=tests/test_hydro.py --ignore=tests/test_region_prep.py` → all green (new move + starter-crop tests included; render suite skips cleanly without a DEM). Confirm `tests/test_main.py` still *collects* (the new gated test skips, doesn't error).

- [ ] **Step 2: Run-the-app drive (Playwright/Chromium, preinstalled).** Launch uvicorn; script the wizard: region auto-skip, empty-state visibility, upload `sample.gpx` (accumulate a second file), crop-draw in all four directions, marker drag + `/api/markers/move` persistence + snap + out-of-frame cue, print-size re-fit + red-tint, stepper back-nav preserving work, theme toggle persistence. Screenshot each step and send the key ones to the user. **Note honestly:** the proof/final *render* needs the gitignored DEM; either (a) generate a throwaway synthetic `regions/lassen_ca/dem.tif` (right CRS/bounds/size, smoothed noise — NOT committed) to drive a real proof+final and screenshot the poster, or (b) verify the proof wiring + humanized-422 path only and state the DEM caveat. Prefer (a) for a real poster screenshot.

- [ ] **Step 3: Adversarial correctness review (Workflow).** Fan-out review over the changed files (`app/main.py`, `app/geo.py`, and each `app/static/*.js` + `index.html`) across dimensions (correctness, invariant-preservation, a11y, error paths), then independently *verify* each finding before folding in confirmed fixes with regression tests. This is the repo's established practice (caught ~15 real bugs previously).

- [ ] **Step 4: Invariant spot-check** — confirm no client path mutates a stamped spec; every spec-invalidating action sets `spec=None` server-side; the starter crop clears the 300-dpi floor; physical units unchanged; one projection throughout.

- [ ] **Step 5: Update the handoff** — refresh `docs/superpowers/handoffs/HANDOFF.md` "what's next" (async render path is now wired into the UI; wizard shipped).

- [ ] **Step 6: Push + PR** — `git push -u origin claude/trailprint-wizard-implementation-3esxfl`; open a **draft** PR (mirror any repo PR template) describing the wizard, the new endpoint, the starter-crop helper, and the DEM caveat on visual proof verification.

---

## Risks / notes
- **DEM absent in this env:** the render suite and any real proof/final are DEM-gated; the wizard's proof step calls the unchanged `/api/proof`. Verify render-adjacent behavior with a throwaway synthetic DEM or clearly caveat it.
- **Starter crop vs narrow regions:** 24×36's 72 km floor exceeds `lassen_ca`'s 63 km width — that size legitimately can't satisfy the cap there; the humanized 422 guides the user. Default 18×24 always clears the floor on both current regions.
- **Overview px near-isotropy:** crop aspect is locked in overview/canvas px (matching existing code); the floor check is done in CRS metres for exactness. The ~0.1% x/y scale difference from integer overview sizing is within the aspect tolerance.
- **Module drift:** the starter crop's "generous framing" logic lives only in Python (tested) and is delivered via `/api/upload`; the frontend only does the simpler center-preserving aspect re-fit on size change — keeps a single tested source of truth.
- **No frontend test harness (v1):** frontend correctness is run-the-app + adversarial review, per repo convention.
