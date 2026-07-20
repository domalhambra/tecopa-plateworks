# GPX-First Flow with In-App Region Creation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Invert the wizard to drop-first — tracks come in, the region is *matched* against a built plate or *built in-app* via a cost-card-gated `region_prep.py` subprocess job.

**Architecture:** Two new engine endpoints (`POST /api/regions/plan`, `POST /api/regions/build` + status poll) power a creation card the UI shows when upload 422s with no matching region. Planning is pure logic (`region_prep.plan_build` imports with the core stack). Building spawns `region_prep.py` in `.venv-prep` on a **dedicated** single-slot `ThreadJobQueue`, streams its stdout into a new `progress` field, runs the GNIS labels build (non-fatal), hot-reloads `REGIONS` in place, and sweeps partial output on failure. The front-end drops the Region step entirely (generalizing the existing ≤1-region auto-skip), keeps dropped File objects across the 422, and re-uploads them when the build lands.

**Tech Stack:** FastAPI/Python 3.14 (engine), vanilla ES modules (UI), pytest.

**Spec:** `docs/superpowers/specs/2026-07-19-gpx-first-region-creation-design.md`
**Branch:** `gpx-first-flow` (already created, stacked on `macos-launcher-app`)

**Ground truth confirmed during planning (do not re-derive):**
- `plan_build(bbox_4326, dst_crs, resolution_m=None)` (`region_prep.py:71`) returns `{resolution_m, auto, grid:(w,h), transform, grid_mpx, over_budget, n_slices, landcover_resolution_m, est_dem_mb, est_peak_gb}`. It needs only numpy/pyproj/rasterio (all in the app venv). `transform` is NOT JSON-serializable — never return it from an endpoint.
- `region_prep.py` CLI: `--id --name --bbox W S E N --epsg` (all required), `--resolution` optional defaulting to `auto` — omitting it reproduces the plan's auto choice. It prints `Build plan: …`, `Fetching NHD hydrography...`, `Fetching NLCD land cover...`, etc. — those stdout lines ARE the progress feed. It writes `regions/<id>/` incl. `region.json` and `sources.json`.
- `scripts/build_labels.py` takes region ids as bare argv (`main()` reads `sys.argv[1:]`), reads `regions/<id>/region.json`, uses stdlib urllib only.
- `ThreadJobQueue` (`app/jobs.py`): `submit(fn)` → jid, worker thread under a semaphore, states `queued/running/done/error`, all record mutations under `self._lock`, `status(jid)` returns a copy, raises `KeyError` on unknown jid.
- `/api/upload` (`app/main.py:405`): multipart `files` + optional `session_id`/`region_id` form fields; the no-region failure is `HTTPException(422, "Tracks don't fall within any available region")` (raised at main.py:306/315/319). Size caps: `TRACK_FILE_MAX_BYTES`/`TRACK_BATCH_MAX_BYTES`.
- `REGIONS = regions.discover(REGIONS_ROOT)` at `app/main.py:26`; `regions.discover(root)` re-runs fine; reload must mutate the dict **in place**.
- `app/static/app.js:132-148` `loadRegions()`: when `list.length <= 1` it already sets `state.steps = ['tracks','frame','proof']` and goes straight to `tracks` — the GPX-first entry generalizes this branch to always.
- `doUpload()` (`app.js:187-245`) holds the dropped `File[]` as `arr`; its catch is `catch (e) { setStatus('Upload failed: ' + e.message); }`. `api.upload` (`api.js:38-45`) throws `ApiError` whose `.message` is the server detail and `.status` the HTTP code (see `asJson` in api.js).
- `startOver()` (`app.js:733`) resets state in place and preserves `state.regions`/`state.steps` — with the region step gone it lands on the dropzone with no changes beyond gallery removal.
- `_kml_segments(root)` (`app/ingest.py:154`) yields lists of `(lon, lat, when, ele)` tuples; `_parse_kml_bytes` hardens XML; `_kmz_to_kml` unzips with bounds. `load_gpx_tracks` uses `gpxpy`.
- `tests/fixtures/sample.gpx`: Susanville↔Eagle Lake, Lassen Co. CA (in-US), first `<trk><name>` is `Susanville to Eagle Lake 2024-06-01`.
- The 8 pre-existing test failures on `main` (oblique/labels/bleed/orphan-drill/readyz) are environmental — do not chase them; run the targeted files listed per task instead.

---

## File Structure

| File | Responsibility |
|---|---|
| Create `app/regionbuild.py` | Pure planning helpers (bbox/UTM/US-coverage/slug) + `run_build` subprocess orchestration |
| Create `tests/test_regionbuild.py` | Unit tests for the helpers + orchestration with a stub prep script |
| Create `tests/test_region_endpoints.py` | `/api/regions/plan` + `/api/regions/build` endpoint tests |
| Modify `app/ingest.py` | Add `lonlat_extent(payloads)` — raw lon/lat bbox + name prefill, no region needed |
| Modify `tests/test_ingest.py` (or create if the suite splits differently — check first) | Tests for `lonlat_extent` |
| Modify `app/jobs.py` | `progress` field + `set_progress()` |
| Modify `tests/test_server_foundation.py` | Progress-field test (this is where the existing `ThreadJobQueue` tests live) |
| Modify `app/main.py` | The three endpoints + dedicated `BUILD_QUEUE` + hot-reload wiring |
| Modify `app/static/api.js` | `planRegion`, `buildRegion`, `buildStatus` |
| Modify `app/static/app.js` | Always-GPX-first entry, region-step removal, plates dialog, creation card flow, reveal chip |
| Modify `app/static/state.js` | Default steps without `region`; `pendingFiles`, `builtRegion` fields |
| Modify `app/static/index.html` | Delete region pane; add plates dialog, build card, chip span |
| Modify `app/static/style.css` | Card/chip/dialog styles |
| Modify `README.md` | "Building regions from the app" subsection |

Env seams (all with defaults, overridable for tests/CI): `TECOPA_PREP_PYTHON` (default `.venv-prep/bin/python`), `TECOPA_PREP_SCRIPT` (default `region_prep.py`), `TECOPA_LABELS_SCRIPT` (default `scripts/build_labels.py`).

---

## Task 1: Pure planning helpers (`app/regionbuild.py`)

**Files:**
- Create: `app/regionbuild.py`
- Create: `tests/test_regionbuild.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_regionbuild.py`:

```python
# Unit tests for the pure planning helpers behind /api/regions/plan.
import math
import pytest

from app import regionbuild as rb


# ---- derive_bbox: pad 20%/side with a 3 km floor ----

def test_derive_bbox_pads_20_percent():
    # a 1-degree square: 20% pad dominates the 3 km floor
    b = rb.derive_bbox(-120.0, 40.0, -119.0, 41.0)
    w, s, e, n = b
    assert w == pytest.approx(-120.2, abs=0.01)
    assert e == pytest.approx(-118.8, abs=0.01)
    assert s == pytest.approx(39.8, abs=0.01)
    assert n == pytest.approx(41.2, abs=0.01)

def test_derive_bbox_floor_dominates_tiny_tracks():
    # a ~100 m track: the 3 km floor dominates. 3 km of latitude ~ 0.02695 deg.
    b = rb.derive_bbox(-120.0, 40.0, -119.999, 40.001)
    w, s, e, n = b
    assert (n - s) >= 0.001 + 2 * 0.9 * (3000.0 / 111320.0)   # floor applied both sides
    # longitude floor is wider on the ground->degree conversion at 40N
    assert (e - w) >= 0.001 + 2 * 0.9 * (3000.0 / (111320.0 * math.cos(math.radians(40))))

def test_derive_bbox_ordering_holds():
    w, s, e, n = rb.derive_bbox(-120.5, 40.1, -120.2, 40.6)
    assert w < e and s < n


# ---- utm_epsg ----

def test_utm_epsg_utah():
    # Tushar Mountains centroid ~ -112.5 -> zone 12 -> EPSG:32612
    assert rb.utm_epsg((-113.0, 38.0, -112.0, 39.0)) == 32612

def test_utm_epsg_california():
    # Lassen ~ -120.9..-120.5 -> zone 10 -> EPSG:32610
    assert rb.utm_epsg((-120.9, 40.3, -120.5, 40.8)) == 32610


# ---- US 3DEP coverage envelope ----

def test_us_coverage_conus_alaska_hawaii():
    assert rb.bbox_covered((-120.9, 40.3, -120.5, 40.8))        # CA
    assert rb.bbox_covered((-150.0, 61.0, -149.0, 62.0))        # AK
    assert rb.bbox_covered((-156.6, 20.5, -156.0, 21.0))        # Maui

def test_us_coverage_rejects_alps_and_straddle():
    assert not rb.bbox_covered((7.0, 45.8, 7.9, 46.2))          # Alps
    # straddling the border: not FULLY inside an envelope -> not covered
    assert not rb.bbox_covered((-120.0, 48.0, -119.0, 50.5))    # into BC


# ---- slug + collision ----

def test_slugify():
    assert rb.slugify("Sawtooth Traverse 2026!") == "sawtooth_traverse_2026"
    assert rb.slugify("  --  ") == "region"
    assert rb.slugify("") == "region"

def test_unique_id_suffixes():
    existing = {"sawtooth", "sawtooth_2"}
    assert rb.unique_id("sawtooth", existing) == "sawtooth_3"
    assert rb.unique_id("fresh", existing) == "fresh"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest -q tests/test_regionbuild.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.regionbuild'` (or AttributeError).

- [ ] **Step 3: Implement the helpers**

Create `app/regionbuild.py`:

```python
# app/regionbuild.py
"""Region creation from dropped tracks: the pure planning helpers behind
/api/regions/plan and the subprocess orchestration behind /api/regions/build.

The heavy fetch stack (py3dep/pynhd/pandas/geopandas) NEVER imports here -- the
build runs region_prep.py as a subprocess in its own venv (.venv-prep), exactly the
separation requirements-regionprep.txt was made for. Planning cost, by contrast, is
pure logic: region_prep.plan_build imports with the core stack."""
from __future__ import annotations
import math
import os
import re
import shutil
import subprocess
from collections import deque

# 3 km padding floor: enough ground for a crop to breathe around a short walk.
PAD_FRAC = 0.20
PAD_FLOOR_M = 3000.0
_M_PER_DEG_LAT = 111320.0

# USGS 3DEP terrain is US-only. A bbox must sit FULLY inside one envelope --
# straddling a border would bake truncated terrain and lie about it.
US_ENVELOPES = (
    (-125.5, 24.3, -66.8, 49.5),    # CONUS
    (-170.0, 51.0, -129.0, 71.6),   # Alaska (3DEP coverage, not the Aleutian tail)
    (-160.6, 18.8, -154.7, 22.4),   # Hawaii
)


def derive_bbox(w: float, s: float, e: float, n: float) -> tuple:
    """Track bounds -> region bbox: pad each side by max(20% of span, 3 km)."""
    mid = math.radians((s + n) / 2.0)
    floor_lat = PAD_FLOOR_M / _M_PER_DEG_LAT
    floor_lon = PAD_FLOOR_M / (_M_PER_DEG_LAT * max(0.2, math.cos(mid)))
    pad_lon = max(PAD_FRAC * (e - w), floor_lon)
    pad_lat = max(PAD_FRAC * (n - s), floor_lat)
    return (w - pad_lon, s - pad_lat, e + pad_lon, n + pad_lat)


def utm_epsg(bbox: tuple) -> int:
    """The northern-hemisphere UTM zone EPSG for the bbox centroid (US => north)."""
    lon = (bbox[0] + bbox[2]) / 2.0
    zone = int((lon + 180.0) // 6.0) + 1
    return 32600 + max(1, min(60, zone))


def bbox_covered(bbox: tuple) -> bool:
    w, s, e, n = bbox
    return any(w >= ew and e <= ee and s >= es and n <= en
               for ew, es, ee, en in US_ENVELOPES)


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return slug or "region"


def unique_id(slug: str, existing) -> str:
    if slug not in existing:
        return slug
    for i in range(2, 100):
        cand = f"{slug}_{i}"
        if cand not in existing:
            return cand
    raise ValueError(f"no free id for slug {slug!r}")
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest -q tests/test_regionbuild.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/regionbuild.py tests/test_regionbuild.py
git commit -m "regionbuild: pure planning helpers (bbox pad, UTM, US envelope, slug)"
```

---

## Task 2: Raw lon/lat extent + name prefill (`ingest.lonlat_extent`)

**Files:**
- Modify: `app/ingest.py` (append at end)
- Test: `tests/test_regionbuild.py` (append — keeps region-creation tests together; the existing ingest test file is organized around region-projected loading)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_regionbuild.py`:

```python
# ---- ingest.lonlat_extent: raw bounds + name prefill, no region required ----

from app import ingest

GPX_ALPS = b"""<?xml version="1.0"?>
<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">
 <trk><name>Haute Route Day 1</name><trkseg>
  <trkpt lat="45.9" lon="6.9"/><trkpt lat="45.95" lon="7.0"/>
 </trkseg></trk></gpx>"""

KML_MIN = b"""<?xml version="1.0"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>
<LineString><coordinates>-112.5,38.4,0 -112.4,38.5,0</coordinates></LineString>
</Placemark></Document></kml>"""


def test_lonlat_extent_gpx_bounds_and_name():
    ext = ingest.lonlat_extent([(GPX_ALPS, "day1.gpx")])
    assert ext["name"] == "Haute Route Day 1"
    w, s, e, n = ext["bbox"]
    assert (w, s, e, n) == pytest.approx((6.9, 45.9, 7.0, 45.95))

def test_lonlat_extent_kml_and_merge():
    ext = ingest.lonlat_extent([(GPX_ALPS, "a.gpx"), (KML_MIN, "b.kml")])
    w, s, e, n = ext["bbox"]
    assert w == pytest.approx(-112.5) and e == pytest.approx(7.0)

def test_lonlat_extent_fixture_has_bounds_and_name():
    data = open("tests/fixtures/sample.gpx", "rb").read()
    ext = ingest.lonlat_extent([(data, "sample.gpx")])
    assert ext["name"] == "Susanville to Eagle Lake 2024-06-01"
    assert ext["bbox"] is not None

def test_lonlat_extent_no_points_is_none():
    ext = ingest.lonlat_extent([(b"<gpx></gpx>", "empty.gpx")])
    assert ext["bbox"] is None

def test_lonlat_extent_garbage_is_skipped_not_raised():
    ext = ingest.lonlat_extent([(b"\x00\x01not xml", "junk.gpx"),
                                (KML_MIN, "b.kml")])
    assert ext["bbox"] is not None            # the good file still counts
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest -q tests/test_regionbuild.py -k lonlat`
Expected: FAIL — `AttributeError: module 'app.ingest' has no attribute 'lonlat_extent'`.

- [ ] **Step 3: Implement**

Append to `app/ingest.py` (after `load_tracks`; reuse the module's existing imports — `gpxpy`, and the `_parse_kml_bytes`/`_kml_segments`/`_kmz_to_kml` helpers are all defined above):

```python
def lonlat_extent(payloads) -> dict:
    """Raw lon/lat bounding box + a name prefill across (data, filename) payloads --
    the no-region parse behind /api/regions/plan. Malformed files are skipped, not
    fatal: the caller reports 'no points' only when NOTHING parsed. The name prefill
    is the first GPX <name> found (file-level, else first track's)."""
    import gpxpy
    w = s = float("inf")
    e = n = float("-inf")
    name = ""
    for data, filename in payloads:
        fn = (filename or "").lower()
        try:
            if fn.endswith(".kmz"):
                segs = _kml_segments(_parse_kml_bytes(_kmz_to_kml(data)))
                pts = [(p[0], p[1]) for seg in segs for p in seg]
            elif fn.endswith(".kml"):
                segs = _kml_segments(_parse_kml_bytes(data))
                pts = [(p[0], p[1]) for seg in segs for p in seg]
            else:
                g = gpxpy.parse(data.decode("utf-8", errors="replace"))
                if not name:
                    name = (g.name or next((t.name for t in g.tracks if t.name), "") or "").strip()
                pts = [(pt.longitude, pt.latitude)
                       for t in g.tracks for sg in t.segments for pt in sg.points]
        except Exception:
            continue                      # one bad file must not sink the batch
        for lon, lat in pts:
            if lon < w: w = lon
            if lon > e: e = lon
            if lat < s: s = lat
            if lat > n: n = lat
    if not (w <= e and s <= n):
        return {"bbox": None, "name": name}
    return {"bbox": (w, s, e, n), "name": name}
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest -q tests/test_regionbuild.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/ingest.py tests/test_regionbuild.py
git commit -m "ingest: lonlat_extent -- raw bounds + name prefill for region planning"
```

---

## Task 3: Job progress field (`app/jobs.py`)

**Files:**
- Modify: `app/jobs.py`
- Test: `tests/test_server_foundation.py` (the existing `ThreadJobQueue` tests live there — append alongside them).

- [ ] **Step 1: Write the failing test** (in the file found above)

```python
def test_job_progress_field_updates_and_survives_status():
    from app.jobs import ThreadJobQueue
    import threading, time
    q = ThreadJobQueue()
    release = threading.Event()

    def work():
        release.wait(timeout=5)
        return "ok"

    jid = q.submit(work)
    q.set_progress(jid, "fetching slice 1/3")
    assert q.status(jid)["progress"] == "fetching slice 1/3"
    q.set_progress("nonexistent", "ignored")     # unknown jid: silently dropped
    release.set()
    for _ in range(50):
        if q.status(jid)["state"] == "done":
            break
        time.sleep(0.1)
    assert q.status(jid)["result"] == "ok"
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — `AttributeError: 'ThreadJobQueue' object has no attribute 'set_progress'`.

- [ ] **Step 3: Implement**

In `app/jobs.py`: add `"progress": None` to the record dict created in `submit()` (line 48-49), and add this method to the class:

```python
    def set_progress(self, jid: str, text: str) -> None:
        """Worker-updated one-line status for long jobs (region builds). Unknown jid
        is a no-op: the record may have been TTL-evicted mid-build."""
        with self._lock:
            if jid in self._jobs:
                self._jobs[jid]["progress"] = text
```

- [ ] **Step 4: Run to verify it passes**, then run that whole test file.

- [ ] **Step 5: Commit**

```bash
git add app/jobs.py tests/<file>
git commit -m "jobs: progress field + set_progress for long-running builds"
```

---

## Task 4: `run_build` subprocess orchestration

**Files:**
- Modify: `app/regionbuild.py` (append)
- Test: `tests/test_regionbuild.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_regionbuild.py`:

```python
# ---- run_build: subprocess orchestration against stub scripts (no network) ----

import json as _json
import sys


def _write_stub_prep(tmp_path, body):
    """A stand-in region_prep.py: same argv contract, controllable behavior."""
    p = tmp_path / "stub_prep.py"
    p.write_text(
        "import argparse, os, sys, json\n"
        "ap = argparse.ArgumentParser()\n"
        "for a in ('--id','--name','--epsg'): ap.add_argument(a, required=True)\n"
        "ap.add_argument('--bbox', nargs=4, type=float, required=True)\n"
        "args = ap.parse_args()\n" + body)
    return str(p)

STUB_OK = """
out = os.path.join(os.environ['STUB_REGIONS_ROOT'], args.id)
os.makedirs(out, exist_ok=True)
print('Build plan: 10 m (auto) -> grid 100x100')
print('Fetching NHD hydrography...')
json.dump({'name': args.name, 'id': args.id}, open(os.path.join(out, 'region.json'), 'w'))
open(os.path.join(out, 'overview.png'), 'wb').write(b'png')
print('done')
"""

STUB_FAIL = """
out = os.path.join(os.environ['STUB_REGIONS_ROOT'], args.id)
os.makedirs(out, exist_ok=True)
open(os.path.join(out, 'region.json'), 'w').write('{}')   # partial output
print('Build plan: ...')
print('Fetching NHD hydrography...')
sys.exit(3)
"""


def _write_stub_labels(tmp_path, ok=True):
    p = tmp_path / "stub_labels.py"
    p.write_text("import sys\nsys.exit(0)\n" if ok else "import sys\nsys.exit(1)\n")
    return str(p)


def _params():
    return {"id": "stub_region", "name": "Stub Region",
            "bbox": (-120.9, 40.3, -120.5, 40.8), "epsg": 32610}


def test_run_build_streams_progress_and_returns(tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_REGIONS_ROOT", str(tmp_path / "regions"))
    lines = []
    res = rb.run_build(_params(), repo_root=".",
                       regions_root=str(tmp_path / "regions"),
                       prep_python=sys.executable,
                       prep_script=_write_stub_prep(tmp_path, STUB_OK),
                       labels_script=_write_stub_labels(tmp_path, ok=True),
                       set_progress=lines.append)
    assert res["labels_note"] is None
    assert any("hydrography" in l for l in lines)
    assert (tmp_path / "regions" / "stub_region" / "region.json").exists()


def test_run_build_failure_cleans_partial_and_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_REGIONS_ROOT", str(tmp_path / "regions"))
    with pytest.raises(RuntimeError) as ei:
        rb.run_build(_params(), repo_root=".",
                     regions_root=str(tmp_path / "regions"),
                     prep_python=sys.executable,
                     prep_script=_write_stub_prep(tmp_path, STUB_FAIL),
                     labels_script=_write_stub_labels(tmp_path),
                     set_progress=lambda s: None)
    assert "hydrography" in str(ei.value)          # tail lines ride the error
    assert not (tmp_path / "regions" / "stub_region").exists()   # partial swept


def test_run_build_labels_failure_is_nonfatal(tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_REGIONS_ROOT", str(tmp_path / "regions"))
    res = rb.run_build(_params(), repo_root=".",
                       regions_root=str(tmp_path / "regions"),
                       prep_python=sys.executable,
                       prep_script=_write_stub_prep(tmp_path, STUB_OK),
                       labels_script=_write_stub_labels(tmp_path, ok=False),
                       set_progress=lambda s: None)
    assert res["labels_note"]                       # note, not an exception
    assert (tmp_path / "regions" / "stub_region").exists()
```

- [ ] **Step 2: Run to verify they fail** (`-k run_build`; AttributeError).

- [ ] **Step 3: Implement**

Append to `app/regionbuild.py`:

```python
def run_build(params: dict, repo_root: str, regions_root: str,
              prep_python: str, prep_script: str, labels_script: str,
              set_progress) -> dict:
    """Spawn region_prep in the prep venv, stream its stdout into set_progress,
    then run the GNIS labels build (non-fatal). Raises RuntimeError with the last
    output lines on prep failure -- after sweeping the partial region dir so a
    retry starts clean. The id is trusted here only as far as its shape: callers
    (the build endpoint) enforce ^[a-z0-9_]+$ before ever reaching this."""
    rid = params["id"]
    if not re.fullmatch(r"[a-z0-9_]+", rid):
        raise ValueError(f"unsafe region id {rid!r}")
    w, s, e, n = params["bbox"]
    cmd = [prep_python, prep_script,
           "--id", rid, "--name", params["name"],
           "--bbox", str(w), str(s), str(e), str(n),
           "--epsg", str(params["epsg"])]
    tail: deque = deque(maxlen=10)
    proc = subprocess.Popen(cmd, cwd=repo_root, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            tail.append(line)
            set_progress(line)
    rc = proc.wait()
    if rc != 0:
        shutil.rmtree(os.path.join(regions_root, rid), ignore_errors=True)
        raise RuntimeError(
            f"region build failed (exit {rc}). Last output:\n" + "\n".join(tail))
    set_progress("Building place-name labels (GNIS)...")
    labels_note = None
    lab = subprocess.run([prep_python, labels_script, rid], cwd=repo_root,
                         capture_output=True, text=True)
    if lab.returncode != 0:
        labels_note = ("Place-name labels failed to build -- the region works "
                       "without them. Rebuild later with: "
                       f"python {labels_script} {rid}")
    return {"labels_note": labels_note}
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest -q tests/test_regionbuild.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/regionbuild.py tests/test_regionbuild.py
git commit -m "regionbuild: run_build subprocess orchestration (stream, sweep, labels)"
```

---

## Task 5: The three endpoints (`app/main.py`)

**Files:**
- Modify: `app/main.py`
- Create: `tests/test_region_endpoints.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_region_endpoints.py`:

```python
# /api/regions/plan + /api/regions/build against stub scripts (no network).
import io
import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import regions as regions_mod

client = TestClient(main.app)

GPX_ALPS = b"""<?xml version="1.0"?>
<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">
 <trk><name>Haute Route</name><trkseg>
  <trkpt lat="45.9" lon="6.9"/><trkpt lat="45.95" lon="7.0"/>
 </trkseg></trk></gpx>"""


def _plan(files):
    return client.post("/api/regions/plan",
                       files=[("files", (n, io.BytesIO(d), "application/gpx+xml"))
                              for d, n in files])


def test_plan_in_us_returns_estimate_and_prefill():
    data = open("tests/fixtures/sample.gpx", "rb").read()
    r = _plan([(data, "sample.gpx")])
    assert r.status_code == 200
    j = r.json()
    assert j["us_covered"] is True
    assert j["epsg"] == 32610                      # Lassen -> UTM 10N
    assert j["name_prefill"] == "Susanville to Eagle Lake 2024-06-01"
    assert j["id"] and j["id"] not in main.REGIONS  # collision-checked slug
    assert j["resolution_m"] in (10, 30, 60)
    assert j["grid"][0] > 0 and j["est_dem_mb"] > 0
    assert "transform" not in j                    # not JSON-serializable; never leaks

def test_plan_outside_us_is_honest():
    r = _plan([(GPX_ALPS, "alps.gpx")])
    assert r.status_code == 200
    j = r.json()
    assert j["us_covered"] is False

def test_plan_no_points_is_422():
    r = _plan([(b"<gpx></gpx>", "empty.gpx")])
    assert r.status_code == 422

def test_plan_reports_prep_readiness(monkeypatch):
    monkeypatch.setattr(main, "PREP_PYTHON", "/nonexistent/python")
    data = open("tests/fixtures/sample.gpx", "rb").read()
    assert _plan([(data, "sample.gpx")]).json()["prep_ready"] is False


# ---- build ----

def _stub_env(tmp_path, monkeypatch, prep_body_ok=True):
    regions_root = tmp_path / "regions"
    regions_root.mkdir()
    monkeypatch.setenv("STUB_REGIONS_ROOT", str(regions_root))
    monkeypatch.setattr(main, "REGIONS_ROOT", str(regions_root))
    prep = tmp_path / "prep.py"
    ok_body = (
        "import argparse, os, json\n"
        "ap = argparse.ArgumentParser()\n"
        "for a in ('--id','--name','--epsg'): ap.add_argument(a, required=True)\n"
        "ap.add_argument('--bbox', nargs=4, type=float, required=True)\n"
        "a = ap.parse_args()\n"
        "out = os.path.join(os.environ['STUB_REGIONS_ROOT'], a.id)\n"
        "os.makedirs(out, exist_ok=True)\n"
        "print('Build plan: stub')\n")
    if prep_body_ok:
        # region.json must satisfy regions.Region(); copy a real one and re-name it.
        ok_body += (
            "cfg = json.load(open('regions/susanville_reno/region.json'))\n"
            "cfg['name'] = a.name\n"
            "json.dump(cfg, open(os.path.join(out, 'region.json'), 'w'))\n"
            "open(os.path.join(out, 'overview.png'), 'wb').write(b'x')\n")
    else:
        ok_body += "import sys; sys.exit(3)\n"
    prep.write_text(ok_body)
    labels = tmp_path / "labels.py"
    labels.write_text("import sys\nsys.exit(0)\n")
    monkeypatch.setattr(main, "PREP_PYTHON", sys.executable)
    monkeypatch.setattr(main, "PREP_SCRIPT", str(prep))
    monkeypatch.setattr(main, "LABELS_SCRIPT", str(labels))
    return regions_root


def _wait_done(jid, timeout=15):
    for _ in range(timeout * 10):
        st = client.get(f"/api/regions/build/{jid}").json()
        if st["state"] in ("done", "error"):
            return st
        time.sleep(0.1)
    raise AssertionError("build job never finished")


BUILD_REQ = {"id": "stub_built", "name": "Stub Built",
             "bbox": [-120.9, 40.3, -120.5, 40.8], "epsg": 32610}


def test_build_end_to_end_hot_reloads_registry(tmp_path, monkeypatch):
    _stub_env(tmp_path, monkeypatch)
    saved = dict(main.REGIONS)
    try:
        r = client.post("/api/regions/build", json=BUILD_REQ)
        assert r.status_code == 200
        st = _wait_done(r.json()["job"])
        assert st["state"] == "done", st
        assert "stub_built" in main.REGIONS         # in-place hot reload
    finally:
        main.REGIONS.clear(); main.REGIONS.update(saved)


def test_build_failure_surfaces_error(tmp_path, monkeypatch):
    _stub_env(tmp_path, monkeypatch, prep_body_ok=False)
    saved = dict(main.REGIONS)
    try:
        r = client.post("/api/regions/build", json=BUILD_REQ)
        st = _wait_done(r.json()["job"])
        assert st["state"] == "error"
        assert "exit 3" in st["error"]
    finally:
        main.REGIONS.clear(); main.REGIONS.update(saved)


def test_build_rejects_bad_id_us_and_collision(tmp_path, monkeypatch):
    _stub_env(tmp_path, monkeypatch)
    bad = dict(BUILD_REQ, id="Bad Id!")
    assert client.post("/api/regions/build", json=bad).status_code == 422
    alps = dict(BUILD_REQ, bbox=[7.0, 45.8, 7.9, 46.2])
    assert client.post("/api/regions/build", json=alps).status_code == 422
    taken = dict(BUILD_REQ, id=next(iter(main.REGIONS)))
    assert client.post("/api/regions/build", json=taken).status_code == 409

def test_build_unknown_job_404():
    assert client.get("/api/regions/build/nope").status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest -q tests/test_region_endpoints.py`
Expected: FAIL — 404s (endpoints don't exist).

- [ ] **Step 3: Implement the endpoints**

In `app/main.py`:

(a) Imports. `main.py` currently imports ingest names only as `from app.ingest import …` (no module alias) and has **no `import re`** — add all of these near the top:
- `import re` (with the stdlib imports)
- `from app import ingest, regionbuild` (with the other `app.` imports)
- `from pydantic import BaseModel` (check it isn't already there)
- `import region_prep` goes **inside** each endpoint body, not module level (keeps app startup unchanged; `pytest.ini` sets `pythonpath = .` and uvicorn runs from the repo root, so the root-level module resolves).

(b) Near the `QUEUE` definition (~line 44-49), add:

```python
# Region builds run on their OWN single-slot queue: a multi-minute DEM fetch must
# never block poster renders behind it, and TECOPA_RENDER_CONCURRENCY must not
# break the one-build-at-a-time guarantee.
BUILD_QUEUE = jobs.ThreadJobQueue(ttl_seconds=TTL_SECONDS, max_concurrency=1)
PREP_PYTHON = os.environ.get("TECOPA_PREP_PYTHON", ".venv-prep/bin/python")
PREP_SCRIPT = os.environ.get("TECOPA_PREP_SCRIPT", "region_prep.py")
LABELS_SCRIPT = os.environ.get("TECOPA_LABELS_SCRIPT", "scripts/build_labels.py")
```

(c) The endpoints (place after the upload endpoint's section). Reuse `TRACK_FILE_MAX_BYTES`/`TRACK_BATCH_MAX_BYTES` for the plan reads:

```python
@app.post("/api/regions/plan")
async def region_plan(files: List[UploadFile] = File(...)):
    """The cost card behind 'no plate covers these tracks': derive a padded bbox +
    UTM zone from the raw lon/lat extent, run region_prep's planner (pure logic --
    no fetch stack), and return an honest estimate plus a name prefill. Never
    fetches anything; never writes anything."""
    import region_prep
    payloads, total = [], 0
    for f in files:
        data = await f.read()
        total += len(data)
        if len(data) > TRACK_FILE_MAX_BYTES or total > TRACK_BATCH_MAX_BYTES:
            raise HTTPException(422, "Track upload exceeds the size limit")
        payloads.append((data, f.filename))
    ext = ingest.lonlat_extent(payloads)
    if ext["bbox"] is None:
        raise HTTPException(422, "No track points found in the dropped files")
    bbox = regionbuild.derive_bbox(*ext["bbox"])
    covered = regionbuild.bbox_covered(bbox)
    epsg = regionbuild.utm_epsg(bbox)
    resp = {"us_covered": covered, "bbox": list(bbox), "epsg": epsg,
            "name_prefill": ext["name"],
            "id": regionbuild.unique_id(
                regionbuild.slugify(ext["name"]), REGIONS.keys()),
            "prep_ready": os.path.exists(PREP_PYTHON)}
    if covered:
        plan = region_prep.plan_build(bbox, f"EPSG:{epsg}")
        resp.update(resolution_m=plan["resolution_m"], grid=list(plan["grid"]),
                    grid_mpx=round(plan["grid_mpx"], 1),
                    est_dem_mb=round(plan["est_dem_mb"], 1),
                    n_slices=plan["n_slices"], over_budget=plan["over_budget"])
    log.info("event=region.plan covered=%s epsg=%s id=%s", covered, epsg, resp["id"])
    return resp


class RegionBuildRequest(BaseModel):
    id: str
    name: str
    bbox: List[float]
    epsg: int


@app.post("/api/regions/build")
async def region_build(req: RegionBuildRequest):
    """Build a new terrain plate from a plan. The client's plan response is
    untrusted: id shape, US coverage, collision, and the grid budget are all
    re-checked here before a byte is fetched."""
    import region_prep
    if not re.fullmatch(r"[a-z0-9_]{1,64}", req.id):
        raise HTTPException(422, "Region id must be lowercase letters, digits, _")
    if len(req.bbox) != 4:
        raise HTTPException(422, "bbox must be [west, south, east, north]")
    bbox = tuple(req.bbox)
    if not regionbuild.bbox_covered(bbox):
        raise HTTPException(422, "USGS 3DEP terrain covers the US only")
    if req.id in REGIONS:
        raise HTTPException(409, f"Region id '{req.id}' already exists")
    plan = region_prep.plan_build(bbox, f"EPSG:{req.epsg}")
    if plan["over_budget"]:
        raise HTTPException(422,
            "This area is too large to build from the app (corridor-scale grid). "
            "Build it deliberately from the terminal: python region_prep.py ...")
    name = (req.name or "").strip()[:80] or req.id
    params = {"id": req.id, "name": name, "bbox": bbox, "epsg": req.epsg}

    # The worker can start before submit() returns the jid, so the progress lambda
    # reads it from a holder and set_progress no-ops on the not-yet-known jid --
    # worst case the first progress line is lost, replaced within a second.
    holder = {}

    def build_job():
        result = regionbuild.run_build(
            params, repo_root=os.getcwd(), regions_root=REGIONS_ROOT,
            prep_python=PREP_PYTHON, prep_script=PREP_SCRIPT,
            labels_script=LABELS_SCRIPT,
            set_progress=lambda s: BUILD_QUEUE.set_progress(holder.get("jid", ""), s))
        REGIONS.clear()
        REGIONS.update(regions.discover(REGIONS_ROOT))   # in-place: refs stay valid
        return {"region": req.id, "labels_note": result["labels_note"]}

    holder["jid"] = jid = BUILD_QUEUE.submit(build_job)
    log.info("event=region.build.submit jid=%s id=%s", jid, req.id)
    return {"job": jid}


@app.get("/api/regions/build/{jid}")
async def region_build_status(jid: str):
    try:
        st = BUILD_QUEUE.status(jid)
    except KeyError:
        raise HTTPException(404, "Unknown build job")
    return {"state": st["state"], "progress": st.get("progress"),
            "error": st["error"], "result": st["result"]}
```

Note for the implementer: the `holder`/`.get("jid", "")` form in the code block above is deliberate and authoritative — the worker thread can start before `submit()` returns the jid, and `set_progress` no-opping on an unknown jid makes the race harmless (at worst the first progress line is lost). Do not "simplify" it to a direct `jid` closure.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest -q tests/test_region_endpoints.py tests/test_regionbuild.py`
Expected: all PASS.

- [ ] **Step 5: Regression check on touched surfaces**

Run: `.venv/bin/python -m pytest -q tests/test_main.py tests/test_credit_and_names.py 2>&1 | tail -3`
Expected: only the pre-existing environmental failure (`test_readyz_ok_with_hydrated_regions`) — nothing new.

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_region_endpoints.py
git commit -m "api: /api/regions/plan + /api/regions/build on a dedicated build queue"
```

---

## Task 6: UI — always GPX-first entry, plates dialog, chip

**Files:**
- Modify: `app/static/state.js`, `app/static/app.js`, `app/static/index.html`, `app/static/style.css`

No JS test rig exists; verification is the browser walk in Step 5 (and Task 8's end-to-end).

- [ ] **Step 1: state.js**

- Change `steps: ['region', 'tracks', 'frame', 'proof']` → `steps: ['tracks', 'frame', 'proof']`.
- Add to the state object: `pendingFiles: null,` (File[] kept across a no-region 422) and `builtRegion: null,` (id of a region built this session — drives the chip verb).

- [ ] **Step 2: index.html**

- Delete the entire `pane-region` div (`<!-- STEP: Region -->` block, lines ~44-55).
- In the toolbar, after `<span id="regionName" class="doc-title"></span>`, add:
  `<span id="regionBadge" class="region-badge" hidden></span>`
- Under the `#continuePoster` button inside `.map-pane`, add:
  `<button id="browsePlates" class="dz-continue" type="button">▦ Built plates — browse existing terrain</button>`
- After `.map-pane`'s closing tag (still inside `.doc`), add the plates dialog and the build card:

```html
<dialog id="platesDialog" class="plates-dialog">
  <h3>Built plates</h3>
  <p class="lede">Terrain already on this machine. Drop tracks anywhere in the US to build a new one.</p>
  <div id="platesList" class="region-gallery"></div>
  <button id="platesClose" class="ghost" type="button">Close</button>
</dialog>

<div id="buildCard" class="build-card" hidden>
  <h3 id="buildTitle">No plate covers these tracks</h3>
  <p id="buildLede" class="lede"></p>
  <div id="buildEstimate" class="build-est"></div>
  <label class="build-name">Region name
    <input id="buildName" type="text" maxlength="80" placeholder="Name this region — it prints on the poster">
  </label>
  <div id="buildActions">
    <button id="buildGo" class="primary" type="button">Build this region</button>
  </div>
  <pre id="buildProgress" class="build-progress" hidden></pre>
  <p id="buildError" class="build-error" hidden></p>
</div>
```

- [ ] **Step 3: app.js**

- `loadRegions(pending)`: replace the whole body's branching with the unconditional GPX-first entry:

```js
async function loadRegions(pending) {
  let list = [];
  try { list = await pending; } catch { /* leave empty; drop-to-detect still works */ }
  state.regions = list;                      // kept for the plates dialog + match echo
  state.steps = ['tracks', 'frame', 'proof'];
  go('tracks');
}
```

- Delete `buildRegionGallery()` and the `#toTracks` / `#continuePosterRegion` wiring in `wire()` (grep for both ids; the elements are gone from index.html). Keep `selectRegion()` — the match path still calls it — but drop its `$('toTracks').disabled` line and the `.region-card` class toggle loop (cards no longer select).
- Remove `'region'` from `STEP_LABELS` and the `$('pane-region').hidden` line in `go()`.
- Add the plates dialog wiring (in `wire()`):

```js
$('browsePlates').onclick = () => {
  const host = $('platesList'); host.innerHTML = '';
  for (const r of state.regions) {
    const card = document.createElement('div');
    card.className = 'region-card static';
    const img = document.createElement('img'); img.src = r.overview; img.alt = '';
    const span = document.createElement('span'); span.textContent = r.name;
    card.append(img, span);
    host.appendChild(card);
  }
  $('platesDialog').showModal();
};
$('platesClose').onclick = () => $('platesDialog').close();
```

- The chip: in `doUpload()`'s success path, right after `state.regionName = j.name; …`, add:

```js
    const badge = $('regionBadge');
    badge.textContent = state.builtRegion === j.region ? 'Built' : 'Matched';
    badge.hidden = false;
```

  And in `startOver()`, add `$('regionBadge').hidden = true; state.builtRegion = null; state.pendingFiles = null;` alongside the existing resets.

- [ ] **Step 4: style.css** (append)

```css
/* GPX-first: the reveal chip, the plates dialog, the creation card */
.region-badge { font-size: 11px; padding: 2px 8px; border-radius: 10px;
  background: var(--accent-soft, #e8e3d8); color: var(--ink, #333);
  text-transform: uppercase; letter-spacing: .06em; }
.plates-dialog { border: none; border-radius: 10px; padding: 20px;
  max-width: 640px; box-shadow: 0 12px 40px rgba(0,0,0,.25); }
.plates-dialog::backdrop { background: rgba(0,0,0,.35); }
.region-card.static { cursor: default; }
.build-card { margin: 14px auto; max-width: 460px; padding: 18px;
  border: 1px solid var(--line, #d8d2c4); border-radius: 10px;
  background: var(--paper, #faf7f0); }
.build-est { font-size: 13px; line-height: 1.5; margin: 10px 0; }
.build-name { display: block; font-size: 12px; margin: 10px 0; }
.build-name input { display: block; width: 100%; margin-top: 4px; padding: 6px 8px; }
.build-progress { font-size: 11px; max-height: 72px; overflow: hidden;
  white-space: pre-wrap; opacity: .8; margin-top: 10px; }
.build-error { color: #a33; font-size: 12px; white-space: pre-wrap; }
```

(Match the file's existing CSS-variable names — open style.css and reuse its actual token names for paper/ink/line/accent rather than the fallbacks above.)

- [ ] **Step 5: Browser verification**

Start the engine (`.venv/bin/python -m uvicorn app.main:app --port 8000`), open `http://127.0.0.1:8000/`:
- The first screen is the dropzone (no region gallery, no Region step in the rail).
- "Built plates" opens the dialog listing the five test plates; Close works.
- Dropping `tests/fixtures/sample.gpx` lands in the workspace with the chip reading **Matched** next to the region name.
- Start over returns to the dropzone; chip hidden.

- [ ] **Step 6: Commit**

```bash
git add app/static/
git commit -m "ui: GPX-first entry -- region step removed, plates dialog, reveal chip"
```

---

## Task 7: UI — creation card flow

**Files:**
- Modify: `app/static/api.js`, `app/static/app.js`

- [ ] **Step 1: api.js** (append)

```js
// Region creation: plan (cost card) and build (background job) for tracks that no
// built plate covers. plan takes the same File[] the failed upload had.
export async function planRegion(files) {
  const fd = new FormData();
  for (const f of files) fd.append('files', f);
  const res = await fetch('/api/regions/plan', { method: 'POST', body: fd });
  return asJson(res);
}
export async function buildRegion(params) {
  const res = await fetch('/api/regions/build', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params) });
  return asJson(res);
}
export async function buildStatus(jid) {
  const res = await fetch(`/api/regions/build/${jid}`);
  return asJson(res);
}
```

- [ ] **Step 2: app.js — the creation flow**

Replace `doUpload`'s catch with a no-region branch:

```js
  } catch (e) {
    if (e.status === 422 && /any available region/.test(e.message || '')) {
      state.pendingFiles = arr;
      await enterCreationFlow(arr);
    } else {
      setStatus('Upload failed: ' + e.message);
    }
  }
```

Add the flow functions (near `doUpload`):

```js
// --- region creation (GPX-first: no plate covers the tracks) ---
async function enterCreationFlow(files) {
  setStatus('No plate covers these tracks — planning a new region…');
  let p;
  try { p = await api.planRegion(files); }
  catch (e) { setStatus('Planning failed: ' + e.message); return; }
  const card = $('buildCard');
  $('dropzone').hidden = true; $('continuePoster').hidden = true;
  $('browsePlates').hidden = true;
  card.hidden = false;
  $('buildError').hidden = true; $('buildProgress').hidden = true;
  $('buildName').value = p.name_prefill || '';
  if (!p.us_covered) {
    $('buildLede').textContent =
      'These tracks are outside USGS 3DEP coverage — terrain data is US-only, '
      + 'so a plate can’t be built for them here.';
    $('buildEstimate').textContent = '';
    $('buildActions').hidden = true;
    return;
  }
  if (!p.prep_ready) {
    $('buildLede').textContent = 'The region-build toolchain isn’t set up yet. In the project folder run:';
    $('buildEstimate').textContent =
      'python3 -m venv .venv-prep && source .venv-prep/bin/activate\n'
      + 'pip install -r requirements-regionprep.txt';
    $('buildActions').hidden = true;
    return;
  }
  $('buildLede').textContent =
    'Tecopa Printworks can build the terrain for these tracks from USGS data.';
  $('buildEstimate').textContent =
    `Terrain: ${p.resolution_m} m grid (${p.grid[0]}×${p.grid[1]}), `
    + `~${Math.round(p.est_dem_mb)} MB download in ${p.n_slices} slice(s).`;
  $('buildActions').hidden = false;
  $('buildGo').disabled = false;
  $('buildGo').onclick = () => startBuild(p);
}

async function startBuild(p) {
  const name = $('buildName').value.trim() || p.name_prefill || p.id;
  $('buildGo').disabled = true;
  $('buildError').hidden = true;
  $('buildProgress').hidden = false; $('buildProgress').textContent = 'Starting…';
  let jid;
  try {
    ({ job: jid } = await api.buildRegion(
      { id: p.id, name, bbox: p.bbox, epsg: p.epsg }));
  } catch (e) { showBuildError(e.message); return; }
  const timer = setInterval(async () => {
    let st;
    try { st = await api.buildStatus(jid); } catch { return; }   // transient poll miss
    if (st.state === 'running' || st.state === 'queued') {
      if (st.progress) $('buildProgress').textContent = st.progress;
      return;
    }
    clearInterval(timer);
    if (st.state === 'error') { showBuildError(st.error || 'Build failed'); return; }
    state.builtRegion = st.result.region;
    $('buildCard').hidden = true;
    const files = state.pendingFiles || [];
    state.pendingFiles = null;
    setStatus(st.result.labels_note
      ? `Region built (${st.result.labels_note}) — loading your tracks…`
      : 'Region built — loading your tracks…');
    await doUpload(files);                    // now matches the new plate; chip = Built
  }, 1000);
}

function showBuildError(msg) {
  $('buildError').textContent = msg;
  $('buildError').hidden = false;
  $('buildGo').disabled = false;
}
```

Also: in `startOver()` add `$('buildCard').hidden = true; $('browsePlates').hidden = false;` so a reset clears the card.

- [ ] **Step 3: Browser verification (stubbed build)**

Restart the engine with the stub seams so no real fetch happens:
```bash
TECOPA_PREP_PYTHON="$PWD/.venv/bin/python" TECOPA_PREP_SCRIPT="/tmp/stub_prep.py" \
  .venv/bin/python -m uvicorn app.main:app --port 8000
```
after writing `/tmp/stub_prep.py` (same stub as `tests/test_region_endpoints.py::_stub_env`, with `STUB_REGIONS_ROOT=regions` — but pointing at a **throwaway** regions root via `TECOPA_REGIONS` to avoid polluting `regions/`; copy `regions/susanville_reno/region.json` and both plates' overview into the throwaway root first so existing-match still works, or simply accept an empty plates dialog for this walk).
- Drop a GPX with out-of-plate US coordinates (make one with two trackpoints near, e.g., lon -111.7 lat 40.6): the card appears with an estimate and the name prefilled.
- Click Build: progress lines stream; on done the workspace opens with the chip reading **Built**.
- Drop the Alps GPX from the tests: the card explains US-only coverage, no Build button.

- [ ] **Step 4: Commit**

```bash
git add app/static/
git commit -m "ui: creation card -- plan, cost estimate, build progress, re-upload"
```

---

## Task 8: Docs + full verification + finish

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README**

In the Setup section (after the venv block's bullets), add:

```markdown
- To **build new regions from the app** (drop tracks anywhere in the US and the
  wizard offers to fetch the terrain), create the separate prep venv once:
  `python3 -m venv .venv-prep && .venv-prep/bin/pip install -r requirements-regionprep.txt`.
  Without it the app still works against already-built plates; oversized
  (corridor-scale) areas are refused in-app and remain a deliberate
  `region_prep.py` terminal run.
```

And in the Layout list, update the `region_prep.py` line to note it now also backs the in-app build (`POST /api/regions/build` spawns it in `.venv-prep`).

- [ ] **Step 2: Targeted suite**

Run: `.venv/bin/python -m pytest -q tests/test_regionbuild.py tests/test_region_endpoints.py tests/test_main.py tests/test_ingest.py 2>&1 | tail -3`
Expected: only the pre-existing `test_readyz_ok_with_hydrated_regions` environmental failure; everything new passes. (If a `tests/test_ingest.py` doesn't exist under that name, run the file that covers ingest — find it with `grep -rl load_gpx_tracks tests/`.)

- [ ] **Step 3: Full suite (background, ~10 min)**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -3`
Expected: `8 failed` (the same pre-existing set) — zero NEW failures.

- [ ] **Step 4: Real-build acceptance (manual, requires network + .venv-prep)**

With the real engine running (no stub env vars): drop a GPX for a small US area with no plate (~10 km trail), confirm the estimate looks sane (small download), click Build, watch it complete (~1-5 min), and take the flow to a rendered proof. This is the one step that exercises the real `region_prep.py` path end to end.

- [ ] **Step 5: Commit + finish**

```bash
git add README.md
git commit -m "docs: in-app region building setup + scope"
```

Then use the superpowers:finishing-a-development-branch skill for the `gpx-first-flow` branch (PR onto `main` — note it stacks on `macos-launcher-app`, so either merge PR #36 first or open the PR with that base).

---

## Out of scope (do not build)

Plate-override picker, auto-proof after drop, sample-tracks demo, client-side GPX parsing, packing built regions into `.trailplate.zip`, non-US terrain sources, build-job persistence across engine restarts, deleting plates from the UI.
