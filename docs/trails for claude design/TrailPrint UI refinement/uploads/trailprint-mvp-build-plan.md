# TrailPrint MVP Implementation Plan

Goal: A single local app on a MacBook Pro that imports GPX tracks, renders a beautiful shaded-relief poster of where a person has been within one curated region, and serves three fidelity tiers (live aim, mid-fidelity proof, full-resolution final) from one render engine.

Architecture: One FastAPI process runs locally and serves both a thin browser UI and the render engine. The browser handles only the cheap interactive aim view (tracks drawn over a low-resolution region image with a draggable crop frame). All real rendering happens server-side in Python. The render engine is split at one load-bearing seam: a compose stage decides the picture once in ground coordinates and emits a CompositionSpec, and a rasterize stage paints that spec at any resolution. The proof and the final are the same spec painted at two pixel sizes.

Tech Stack: Python 3.11+, rasterio (GDAL), pyproj, numpy, scipy, shapely, gpxpy, Pillow, FastAPI, uvicorn. Region prep uses py3dep to fetch USGS 3DEP elevation. Tests use pytest. Frontend is vanilla HTML, CSS, and canvas with no framework.

---

## Success criterion (the finish line)

The MVP is done when your render of a familiar area reads as belonging in the same family as the two reference maps (the Utah shaded-relief and the Matanuska-Susitna hydrographic map), judged by eye, with a real GPX track sitting correctly on the terrain. The point of v1 is to settle the map style, not to scale.

## Non-goals for v1 (deferred, see Roadmap)

- No user photos, no EXIF or HEIC handling, no emoji glyph markers. v1 markers are clean designed geometric markers. (v1.1)
- No pre-baked soul-pass layers, no tile server, no map library in the browser. (v1.2)
- No accounts, no payments, no print fulfillment, no job queue, no database. Session state lives in a module-level dict. (v1.3, v1.4)
- One region only. GPX only (Avenza and OnX both export GPX). KML is later. (v1.2)

## Invariants you must not break

These are the decisions the whole product rests on. Protect them in every task.

1. One spec, painted at many sizes. The proof and the final must come from the identical CompositionSpec. Never compute the picture twice. Decide once in `compose`, paint in `rasterize`.
2. Physical units, never pixels, for anything visual. Line widths in points, marker diameters in inches, grain cell size in inches, title type in points. Convert to pixels per the target DPI at paint time. A line sized in pixels will look bold in the proof and vanish in the final.
3. Determinism. The same spec paints the same image every time. The grain generator and any jitter use a fixed seed carried on the spec.
4. One projection throughout. The DEM, the aim-view overview image, the tracks, and the crop all live in the region's projected CRS. Tracks arrive in latitude and longitude and must be reprojected before anything else touches them.
5. Registration is correctness, not polish. A track that sits 200 meters off its ridge still looks plausible. Prove the coordinate chain against a known control point before tuning any aesthetics.
6. The zoom cap. Never let a crop ask for more ground detail than the data holds. At 10 meter data and 300 DPI the floor is roughly 3 km of ground per printed inch. Validate it on the spec.

---

## File map

```
trailprint/
  README.md
  requirements.txt
  region_prep.py              # OFFLINE one-time: fetch DEM, build COG, build overview PNG + region.json
  regions/
    <region_id>/
      dem.tif                 # cloud-optimized GeoTIFF with overviews, in region CRS
      overview.png            # aim-view image, full region extent, same CRS
      region.json             # CRS, bounds, overview affine, elevation range, light + color recipe
  app/
    __init__.py
    main.py                   # FastAPI app, static serving, 3 endpoints
    session.py                # in-memory session store (single user)
    geo.py                    # CRS transforms + affine helpers (overview px <-> CRS, window math)
    ingest.py                 # GPX parse -> reproject -> simplify -> dedup
    density.py                # visitation grid + hotspot selection (count distinct tracks, not points)
    spec.py                   # CompositionSpec dataclass, build + validate (zoom cap)
    relief.py                 # hillshade, hypsometric tint, texture pass, valley darkening, grain
    render.py                 # rasterize(spec, dpi, watermark) -> PIL.Image
    static/
      index.html
      style.css
      app.js
  tests/
    fixtures/sample.gpx
    test_geo.py
    test_ingest.py
    test_density.py
    test_spec.py
    test_render.py
```

Responsibilities, one per file:

- `geo.py`: every coordinate conversion. The only place that knows how overview pixels, region CRS meters, and render windows relate. Single source of truth for registration.
- `ingest.py`: turns a raw GPX upload into clean projected polylines. Nothing aesthetic.
- `density.py`: turns projected tracks into a small set of well-spaced hotspots, weighted by visitation.
- `spec.py`: the contract between compose and rasterize. Holds the crop, print size, tracks, hotspots, and all physical style values plus the seed. Validates the zoom cap.
- `relief.py`: the art. Pure numpy functions that turn an elevation window into a styled relief array. This is the file you will spend the most time tuning.
- `render.py`: orchestration. Reads the DEM window for a spec at a given DPI, calls `relief.py`, draws tracks and markers in physical units, returns a Pillow image.
- `main.py`: three endpoints over the engine. No business logic of its own.

---

## Phase 0: Project scaffold

### Task 0.1: Repository and dependencies

Files:
- Create: `trailprint/requirements.txt`
- Create: `trailprint/README.md`
- Create: `trailprint/app/__init__.py` (empty)

Step 1: Write `requirements.txt`

```
rasterio>=1.3
pyproj>=3.6
numpy>=1.26
scipy>=1.11
shapely>=2.0
gpxpy>=1.6
Pillow>=10.2
fastapi>=0.110
uvicorn[standard]>=0.29
python-multipart>=0.0.9
# region prep only:
py3dep>=0.16
# dev:
pytest>=8.0
```

Step 2: Create the virtual environment and install

Run:
```
cd trailprint
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
Expected: clean install. On Apple Silicon, rasterio, pyproj, and Pillow ship native wheels, so no Homebrew GDAL is required.

Step 3: Verify the GDAL stack imports

Run:
```
python -c "import rasterio, pyproj, numpy, scipy, shapely, gpxpy, PIL; print('ok')"
```
Expected: `ok`

Step 4: Commit
```
git init
git add requirements.txt README.md app/__init__.py
git commit -m "Scaffold project and pin dependencies"
```

---

## Phase 1: The coordinate spine (registration first)

This phase exists to satisfy invariant 5 before any pixels get pretty. If the chain here is right, everything downstream can be trusted.

### Task 1.1: Region config schema and geo helpers

Files:
- Create: `app/geo.py`
- Create: `tests/test_geo.py`

Step 1: Write the failing test

```python
# tests/test_geo.py
import numpy as np
from app.geo import RegionGeo, lonlat_to_crs, crs_to_overview_px, overview_px_to_crs

# A minimal synthetic region: a 100km x 80km box in UTM 11N (EPSG:32611),
# rendered to a 1000 x 800 overview image.
REGION = RegionGeo(
    crs="EPSG:32611",
    # bounds in CRS meters: (min_x, min_y, max_x, max_y)
    bounds=(200000.0, 4000000.0, 300000.0, 4080000.0),
    overview_size=(1000, 800),  # width, height in px
)

def test_overview_affine_roundtrip():
    # CRS -> overview px -> CRS should return the original point
    x, y = 250000.0, 4040000.0
    px, py = crs_to_overview_px(REGION, x, y)
    x2, y2 = overview_px_to_crs(REGION, px, py)
    assert abs(x - x2) < 1e-6 and abs(y - y2) < 1e-6

def test_overview_corners():
    # top-left CRS corner maps to pixel (0, 0); bottom-right to (W, H)
    px, py = crs_to_overview_px(REGION, 200000.0, 4080000.0)
    assert abs(px) < 1e-6 and abs(py) < 1e-6
    px, py = crs_to_overview_px(REGION, 300000.0, 4000000.0)
    assert abs(px - 1000) < 1e-6 and abs(py - 800) < 1e-6

def test_control_point_projection():
    # A known lon/lat lands at a sane location inside the box.
    x, y = lonlat_to_crs(REGION, -117.0, 36.5)  # eastern California-ish
    assert REGION.bounds[0] <= x <= REGION.bounds[2]
    assert REGION.bounds[1] <= y <= REGION.bounds[3]
```

Step 2: Run, verify it fails
Run: `pytest tests/test_geo.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.geo'`

Step 3: Implement

```python
# app/geo.py
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
from pyproj import Transformer

@dataclass(frozen=True)
class RegionGeo:
    crs: str                       # e.g. "EPSG:32611"
    bounds: tuple                  # (min_x, min_y, max_x, max_y) in CRS meters
    overview_size: tuple           # (width_px, height_px)

@lru_cache(maxsize=8)
def _to_crs(crs: str) -> Transformer:
    # always_xy keeps argument order (lon, lat) -> (x, y)
    return Transformer.from_crs("EPSG:4326", crs, always_xy=True)

def lonlat_to_crs(region: RegionGeo, lon: float, lat: float):
    return _to_crs(region.crs).transform(lon, lat)

def crs_to_overview_px(region: RegionGeo, x: float, y: float):
    min_x, min_y, max_x, max_y = region.bounds
    w, h = region.overview_size
    px = (x - min_x) / (max_x - min_x) * w
    py = (max_y - y) / (max_y - min_y) * h   # image y grows downward
    return px, py

def overview_px_to_crs(region: RegionGeo, px: float, py: float):
    min_x, min_y, max_x, max_y = region.bounds
    w, h = region.overview_size
    x = min_x + (px / w) * (max_x - min_x)
    y = max_y - (py / h) * (max_y - min_y)
    return x, y

def crop_px_to_crs_window(region: RegionGeo, x0, y0, x1, y1):
    """A crop rectangle in overview pixels -> a CRS window (min_x, min_y, max_x, max_y)."""
    ax, ay = overview_px_to_crs(region, min(x0, x1), max(y0, y1))  # lower-left
    bx, by = overview_px_to_crs(region, max(x0, x1), min(y0, y1))  # upper-right
    return (ax, ay, bx, by)
```

Step 4: Run, verify pass
Run: `pytest tests/test_geo.py -q`
Expected: PASS

Step 5: Commit
```
git add app/geo.py tests/test_geo.py
git commit -m "Coordinate spine: region geo helpers with affine roundtrip tests"
```

### Task 1.2: Region prep script (offline, one-time)

This builds the assets for your flagship region. Pick something county-sized to start, like your Utah reference area. Run it once per region.

Files:
- Create: `region_prep.py`

Step 1: Implement

```python
# region_prep.py
"""
One-time, offline. Fetch 3DEP elevation for a bbox, write a COG with overviews,
build the aim-view overview PNG, and write region.json.

Usage:
    python region_prep.py --id sanpete_ut \
        --name "Sanpete, Utah" \
        --bbox -111.9 39.0 -111.2 39.6 \
        --epsg 32612
"""
import argparse, json, os
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject
import py3dep
from PIL import Image

def fetch_dem(bbox):
    # bbox is (west, south, east, north) in lon/lat. 10 m = 3DEP standard.
    return py3dep.get_dem(bbox, resolution=10)  # xarray DataArray, EPSG:4326

def to_cog(dem_da, dst_crs, out_path):
    src_crs = "EPSG:4326"
    arr = dem_da.values.astype("float32")
    h, w = arr.shape
    left = float(dem_da.x.min()); right = float(dem_da.x.max())
    bottom = float(dem_da.y.min()); top = float(dem_da.y.max())
    src_transform = rasterio.transform.from_bounds(left, bottom, right, top, w, h)

    dst_transform, dw, dh = calculate_default_transform(
        src_crs, dst_crs, w, h, left, bottom, right, top)
    dst = np.full((dh, dw), np.nan, dtype="float32")
    reproject(
        source=arr, destination=dst,
        src_transform=src_transform, src_crs=src_crs,
        dst_transform=dst_transform, dst_crs=dst_crs,
        resampling=Resampling.bilinear, src_nodata=np.nan, dst_nodata=np.nan)

    profile = dict(driver="GTiff", dtype="float32", count=1,
                   height=dh, width=dw, crs=dst_crs, transform=dst_transform,
                   nodata=np.nan, tiled=True, blockxsize=512, blockysize=512,
                   compress="deflate")
    with rasterio.open(out_path, "w", **profile) as ds:
        ds.write(dst, 1)
        # Overviews are the image pyramid: coarse copies for zoomed-out reads.
        ds.build_overviews([2, 4, 8, 16, 32], Resampling.average)
        ds.update_tags(ns="rio_overview", resampling="average")
    return out_path

def overview_png(cog_path, out_png, long_edge=1400):
    with rasterio.open(cog_path) as ds:
        scale = long_edge / max(ds.width, ds.height)
        ow, oh = int(ds.width * scale), int(ds.height * scale)
        elev = ds.read(1, out_shape=(oh, ow), resampling=Resampling.average)
        bounds = ds.bounds; crs = ds.crs.to_string()
    # A neutral grayscale relief just for aiming; the pretty version is rendered later.
    valid = np.isfinite(elev)
    lo, hi = np.nanpercentile(elev[valid], [1, 99])
    norm = np.clip((elev - lo) / (hi - lo + 1e-9), 0, 1)
    img = (norm * 255).astype("uint8")
    Image.fromarray(img, "L").convert("RGB").save(out_png)
    return (ow, oh), (bounds.left, bounds.bottom, bounds.right, bounds.top), crs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--bbox", nargs=4, type=float, required=True,
                    help="west south east north (lon/lat)")
    ap.add_argument("--epsg", type=int, required=True,
                    help="projected CRS for the region, e.g. a local UTM zone")
    args = ap.parse_args()

    out_dir = os.path.join("regions", args.id)
    os.makedirs(out_dir, exist_ok=True)
    dst_crs = f"EPSG:{args.epsg}"

    print("Fetching 3DEP DEM...")
    dem = fetch_dem(tuple(args.bbox))
    cog = to_cog(dem, dst_crs, os.path.join(out_dir, "dem.tif"))

    print("Building aim-view overview...")
    size, bounds, crs = overview_png(cog, os.path.join(out_dir, "overview.png"))

    with rasterio.open(cog) as ds:
        elev = ds.read(1)
        valid = np.isfinite(elev)
        emin, emax = float(np.nanpercentile(elev[valid], 0.5)), float(np.nanpercentile(elev[valid], 99.5))

    region = {
        "id": args.id, "name": args.name, "crs": crs,
        "bounds": list(bounds), "overview_size": list(size),
        "dem_path": "dem.tif", "overview_path": "overview.png",
        "native_resolution_m": 10,
        # absolute color scale + fixed light keep every crop consistent (invariant 4):
        "elevation_min": emin, "elevation_max": emax,
        "light_azimuth": 315, "light_altitude": 45, "z_factor": 1.0,
    }
    with open(os.path.join(out_dir, "region.json"), "w") as f:
        json.dump(region, f, indent=2)
    print(f"Region ready: {out_dir}")

if __name__ == "__main__":
    main()
```

Step 2: Run it for your flagship region
Run (adjust bbox and epsg to your area; epsg should be the local UTM zone):
```
python region_prep.py --id sanpete_ut --name "Sanpete, Utah" \
  --bbox -111.9 39.0 -111.2 39.6 --epsg 32612
```
Expected: `regions/sanpete_ut/` contains `dem.tif`, `overview.png`, `region.json`. Open `overview.png` and confirm it looks like the right piece of land.

Step 3: Commit
```
git add region_prep.py
git commit -m "Region prep: fetch 3DEP, write COG with overviews, build overview PNG and config"
```

### Task 1.3: Registration control-point check

Before any styling, prove a known place lands where it should.

Files:
- Create: `tests/test_registration.py`

Step 1: Write the test (edit the control point to a peak or junction you can verify on a real map within your region)

```python
# tests/test_registration.py
import json, os
import rasterio
from app.geo import RegionGeo, lonlat_to_crs

REGION_DIR = "regions/sanpete_ut"

def load_region():
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    return RegionGeo(crs=cfg["crs"], bounds=tuple(cfg["bounds"]),
                     overview_size=tuple(cfg["overview_size"])), cfg

def test_control_point_elevation():
    # Pick a named summit inside your region and its real elevation (meters).
    LON, LAT, KNOWN_ELEV_M, TOL_M = -111.5, 39.3, 2800, 400
    region, cfg = load_region()
    x, y = lonlat_to_crs(region, LON, LAT)
    with rasterio.open(os.path.join(REGION_DIR, cfg["dem_path"])) as ds:
        val = list(ds.sample([(x, y)]))[0][0]
    assert abs(val - KNOWN_ELEV_M) < TOL_M, f"got {val} m at control point"
```

Step 2: Run
Run: `pytest tests/test_registration.py -q`
Expected: PASS. If it fails badly, the projection is wrong and you fix it here, before anything else.

Step 3: Commit
```
git add tests/test_registration.py
git commit -m "Registration: control-point elevation check against the DEM"
```

---

## Phase 2: Ingest and density

### Task 2.1: GPX ingest

Files:
- Create: `app/ingest.py`
- Create: `tests/fixtures/sample.gpx` (use a real export from OnX or Avenza, not synthetic; real files carry empty segments, missing timestamps, and large point counts)
- Create: `tests/test_ingest.py`

Step 1: Write the failing test

```python
# tests/test_ingest.py
from app.geo import RegionGeo
from app.ingest import load_gpx_tracks

REGION = RegionGeo(crs="EPSG:32612",
                   bounds=(400000.0, 4318000.0, 470000.0, 4385000.0),
                   overview_size=(1400, 1340))

def test_load_real_gpx():
    with open("tests/fixtures/sample.gpx", "rb") as f:
        tracks = load_gpx_tracks(f.read(), REGION)
    assert len(tracks) >= 1
    for t in tracks:
        assert t.coords.shape[1] == 2          # (N, 2) in CRS meters
        assert t.coords.shape[0] >= 2          # simplified but not empty
        assert t.track_id is not None
```

Step 2: Run, verify fail
Run: `pytest tests/test_ingest.py -q`
Expected: FAIL, no module `app.ingest`

Step 3: Implement

```python
# app/ingest.py
from __future__ import annotations
from dataclasses import dataclass
import io
import numpy as np
import gpxpy
from shapely.geometry import LineString
from app.geo import RegionGeo, lonlat_to_crs

@dataclass
class Track:
    track_id: str
    coords: np.ndarray   # (N, 2) float64, region CRS meters
    day: str | None      # ISO date if timestamps exist, else None

def load_gpx_tracks(data: bytes, region: RegionGeo,
                    simplify_tolerance_m: float = 15.0) -> list[Track]:
    gpx = gpxpy.parse(io.BytesIO(data))
    out: list[Track] = []
    idx = 0
    for trk in gpx.tracks:
        for seg in trk.segments:
            pts = [(p.longitude, p.latitude, p.time) for p in seg.points
                   if p.longitude is not None and p.latitude is not None]
            if len(pts) < 2:
                continue
            xy = np.array([lonlat_to_crs(region, lon, lat) for lon, lat, _ in pts])
            line = LineString(xy).simplify(simplify_tolerance_m, preserve_topology=False)
            coords = np.asarray(line.coords)
            if coords.shape[0] < 2:
                continue
            day = None
            t0 = next((t for _, _, t in pts if t is not None), None)
            if t0 is not None:
                day = t0.date().isoformat()
            out.append(Track(track_id=f"{trk.name or 'track'}-{idx}", coords=coords, day=day))
            idx += 1
    return out
```

Step 4: Run, verify pass
Run: `pytest tests/test_ingest.py -q`
Expected: PASS

Step 5: Commit
```
git add app/ingest.py tests/test_ingest.py tests/fixtures/sample.gpx
git commit -m "Ingest: parse GPX, reproject to region CRS, simplify tracks"
```

### Task 2.2: Visitation density and hotspots

Density must mean places you returned to, not where the GPS jittered. Count distinct tracks (or days) crossing a coarse grid cell, not raw points.

Files:
- Create: `app/density.py`
- Create: `tests/test_density.py`

Step 1: Write the failing test

```python
# tests/test_density.py
import numpy as np
from app.ingest import Track
from app.density import hotspots

def line(a, b, n=50):
    return np.linspace(a, b, n)

def test_returned_place_outranks_one_off():
    base = (430000.0, 4350000.0)
    # Five overlapping tracks through 'base' (a returned-to place):
    repeated = [Track(f"r{i}", line(base, (base[0]+500, base[1]+500)), day=f"2024-01-0{i+1}")
                for i in range(5)]
    # One long one-off elsewhere:
    oneoff = [Track("o0", line((445000.0, 4365000.0), (446000.0, 4366000.0)), day="2024-02-01")]
    hs = hotspots(repeated + oneoff, region_bounds=(400000, 4318000, 470000, 4385000),
                  cell_m=1000, max_spots=3)
    assert len(hs) >= 1
    top = hs[0]
    assert abs(top["x"] - base[0]) < 2000 and abs(top["y"] - base[1]) < 2000
    assert top["weight"] >= 5
```

Step 2: Run, verify fail
Run: `pytest tests/test_density.py -q`
Expected: FAIL

Step 3: Implement

```python
# app/density.py
from __future__ import annotations
import numpy as np

def _rasterize_visits(tracks, bounds, cell_m):
    min_x, min_y, max_x, max_y = bounds
    nx = max(1, int((max_x - min_x) / cell_m))
    ny = max(1, int((max_y - min_y) / cell_m))
    # For each cell, collect the set of distinct track keys passing through it.
    sets = [[set() for _ in range(nx)] for _ in range(ny)]
    for t in tracks:
        key = t.day or t.track_id   # prefer distinct days, fall back to track id
        c = t.coords
        # densify so a straight segment still marks every cell it crosses
        seg_len = np.hypot(np.diff(c[:, 0]), np.diff(c[:, 1]))
        for i in range(len(c) - 1):
            steps = max(1, int(seg_len[i] / (cell_m * 0.5)))
            xs = np.linspace(c[i, 0], c[i+1, 0], steps)
            ys = np.linspace(c[i, 1], c[i+1, 1], steps)
            for x, y in zip(xs, ys):
                gx = int((x - min_x) / cell_m); gy = int((max_y - y) / cell_m)
                if 0 <= gx < nx and 0 <= gy < ny:
                    sets[gy][gx].add(key)
    grid = np.array([[len(sets[j][i]) for i in range(nx)] for j in range(ny)], dtype=float)
    return grid, nx, ny

def hotspots(tracks, region_bounds, cell_m=1000, max_spots=7, min_spacing_m=6000):
    if not tracks:
        return []
    min_x, min_y, max_x, max_y = region_bounds
    grid, nx, ny = _rasterize_visits(tracks, region_bounds, cell_m)
    # candidate cells, strongest first
    order = np.dstack(np.unravel_index(np.argsort(grid, axis=None)[::-1], grid.shape))[0]
    spots = []
    for gy, gx in order:
        w = grid[gy, gx]
        if w < 1:
            break
        x = min_x + (gx + 0.5) * cell_m
        y = max_y - (gy + 0.5) * cell_m
        if all(np.hypot(x - s["x"], y - s["y"]) >= min_spacing_m for s in spots):
            spots.append({"x": float(x), "y": float(y), "weight": int(w)})
        if len(spots) >= max_spots:
            break
    return spots
```

Step 4: Run, verify pass
Run: `pytest tests/test_density.py -q`
Expected: PASS

Step 5: Commit
```
git add app/density.py tests/test_density.py
git commit -m "Density: visitation-weighted hotspots with min spacing"
```

---

## Phase 3: The spec and the zoom cap

### Task 3.1: CompositionSpec

Files:
- Create: `app/spec.py`
- Create: `tests/test_spec.py`

Step 1: Write the failing test

```python
# tests/test_spec.py
import numpy as np
import pytest
from app.spec import CompositionSpec, ZoomTooTightError

def base_kwargs(**over):
    kw = dict(
        region_id="r", crs="EPSG:32612",
        crop=(430000.0, 4345000.0, 460000.0, 4385000.0),  # 30 km x 40 km
        print_w_in=18.0, print_h_in=24.0,
        native_resolution_m=10.0,
        tracks=[np.array([[431000.0, 4346000.0], [459000.0, 4384000.0]])],
        hotspots=[{"x": 445000.0, "y": 4365000.0, "weight": 5}],
        seed=7,
    )
    kw.update(over)
    return kw

def test_aspect_matches_print():
    s = CompositionSpec(**base_kwargs())
    crop_ar = (s.crop[2] - s.crop[0]) / (s.crop[3] - s.crop[1])
    assert abs(crop_ar - 18/24) < 0.02

def test_zoom_cap_rejects_too_tight():
    # 1 km wide crop on an 18 inch print at 300 dpi demands sub-10m detail -> reject
    with pytest.raises(ZoomTooTightError):
        CompositionSpec(**base_kwargs(crop=(445000.0, 4364250.0, 446000.0, 4365583.0))).validate(dpi=300)

def test_pixel_dims_track_dpi():
    s = CompositionSpec(**base_kwargs())
    assert s.pixel_size(96) == (1728, 2304)
    assert s.pixel_size(300) == (5400, 7200)
```

Step 2: Run, verify fail
Run: `pytest tests/test_spec.py -q`
Expected: FAIL

Step 3: Implement

```python
# app/spec.py
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

class ZoomTooTightError(ValueError):
    pass

@dataclass
class CompositionSpec:
    region_id: str
    crs: str
    crop: tuple           # (min_x, min_y, max_x, max_y) in CRS meters
    print_w_in: float
    print_h_in: float
    native_resolution_m: float
    tracks: list          # list of (N,2) arrays in CRS meters
    hotspots: list        # list of {"x","y","weight"}
    seed: int = 7

    # physical style values (invariant 2): everything visual sized in print units
    track_width_pt: float = 1.4
    track_color: tuple = (38, 36, 33)        # basalt-ish
    track_max_darken: float = 0.85           # overlap darkening ceiling
    marker_diameter_in: float = 0.32
    grain_cell_in: float = 0.014
    grain_strength: float = 0.05
    title_pt: float = 22.0
    title_text: str = ""

    def pixel_size(self, dpi: int) -> tuple:
        return (round(self.print_w_in * dpi), round(self.print_h_in * dpi))

    def ground_per_pixel(self, dpi: int) -> float:
        w_px, _ = self.pixel_size(dpi)
        return (self.crop[2] - self.crop[0]) / w_px

    def validate(self, dpi: int = 300):
        # zoom cap (invariant 6): never request finer ground detail than the data holds
        if self.ground_per_pixel(dpi) < self.native_resolution_m:
            raise ZoomTooTightError(
                f"{self.ground_per_pixel(dpi):.1f} m/px requested, "
                f"data floor is {self.native_resolution_m} m/px")
        return self
```

Step 4: Run, verify pass
Run: `pytest tests/test_spec.py -q`
Expected: PASS

Step 5: Commit
```
git add app/spec.py tests/test_spec.py
git commit -m "CompositionSpec: physical-unit style values, dpi-scaled pixel dims, zoom cap"
```

---

## Phase 4: The relief engine (the centerpiece)

This is where most of your time goes. Build the baseline, confirm it renders, then tune by eye on a small crop. The functions are pure numpy so they preview in seconds. Every aesthetic lever is a named constant; that is your tuning surface.

### Task 4.1: Relief passes

Files:
- Create: `app/relief.py`
- Create: `tests/test_relief.py`

Step 1: Write the failing test (shape and range only; the look is judged by eye, not asserted)

```python
# tests/test_relief.py
import numpy as np
from app.relief import shaded_relief

def synthetic_terrain(h=256, w=320):
    yy, xx = np.mgrid[0:h, 0:w]
    return (np.sin(xx/25.0) * np.cos(yy/30.0) * 300 + 1500).astype("float32")

def test_relief_shape_and_range():
    elev = synthetic_terrain()
    rgb = shaded_relief(elev, res_m=30.0, elev_min=1000, elev_max=2000,
                        azimuth=315, altitude=45, z_factor=1.0, seed=7)
    assert rgb.shape == (256, 320, 3)
    assert rgb.dtype == np.uint8

def test_relief_is_deterministic():
    elev = synthetic_terrain()
    a = shaded_relief(elev, 30.0, 1000, 2000, 315, 45, 1.0, seed=7)
    b = shaded_relief(elev, 30.0, 1000, 2000, 315, 45, 1.0, seed=7)
    assert np.array_equal(a, b)   # invariant 3
```

Step 2: Run, verify fail
Run: `pytest tests/test_relief.py -q`
Expected: FAIL

Step 3: Implement the baseline recipe

```python
# app/relief.py
from __future__ import annotations
import numpy as np
from scipy.ndimage import gaussian_filter

# ---- tuning surface: edit these by eye against the reference maps ----
HYPSO_STOPS = [
    # (normalized_elevation 0..1, (r, g, b))  -- earthy, basin-to-peak
    (0.00, (171, 168, 140)),   # low salt/sage
    (0.25, (142, 150, 110)),   # green valley
    (0.50, (150, 134,  96)),   # tan slope
    (0.75, (120,  98,  74)),   # brown ridge
    (1.00, (236, 232, 220)),   # high near-white
]
TEXTURE_STRENGTH = 0.35        # ridge crispness (high-pass blend)
TEXTURE_RADIUS_PX = 6
VALLEY_STRENGTH = 0.30         # soft darkening in deep valleys
VALLEY_RADIUS_PX = 40
HILLSHADE_GAMMA = 1.1          # contrast of the light
# ---------------------------------------------------------------------

def _fill_nan(elev):
    if not np.isnan(elev).any():
        return elev
    m = np.nanmean(elev)
    return np.where(np.isnan(elev), m, elev)

def hillshade(elev, res_m, azimuth=315, altitude=45, z_factor=1.0):
    az = np.radians(360.0 - azimuth + 90.0)
    alt = np.radians(altitude)
    dy, dx = np.gradient(elev * z_factor, res_m)
    slope = np.pi/2 - np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)
    shaded = (np.sin(alt) * np.sin(slope)
              + np.cos(alt) * np.cos(slope) * np.cos(az - aspect))
    return np.clip(shaded, 0, 1)

def hypsometric(elev, elev_min, elev_max):
    norm = np.clip((elev - elev_min) / (elev_max - elev_min + 1e-9), 0, 1)
    stops = HYPSO_STOPS
    xs = np.array([s[0] for s in stops])
    rgb = np.zeros(elev.shape + (3,), dtype="float32")
    for ch in range(3):
        ys = np.array([s[1][ch] for s in stops], dtype="float32")
        rgb[..., ch] = np.interp(norm, xs, ys)
    return rgb / 255.0

def texture_pass(elev):
    # high-pass: sharpen ridges and drainages (a cheap stand-in for true texture shading)
    blur = gaussian_filter(elev, TEXTURE_RADIUS_PX)
    hp = elev - blur
    s = np.std(hp) + 1e-9
    return np.clip(0.5 + (hp / (4 * s)), 0, 1)   # 0..1, centered

def valley_pass(elev):
    # darken places that sit well below their surroundings
    big = gaussian_filter(elev, VALLEY_RADIUS_PX)
    depth = np.clip(big - elev, 0, None)
    s = np.percentile(depth, 99) + 1e-9
    return np.clip(depth / s, 0, 1)              # 0..1, 1 = deep valley

def grain(shape, cell_px, strength, seed):
    rng = np.random.default_rng(seed)
    h, w = shape
    small = rng.standard_normal((max(1, round(h / cell_px)),
                                 max(1, round(w / cell_px)))).astype("float32")
    # nearest-neighbor upscale to a paper-grain cell size
    ys = (np.linspace(0, small.shape[0] - 1, h)).astype(int)
    xs = (np.linspace(0, small.shape[1] - 1, w)).astype(int)
    g = small[np.ix_(ys, xs)]
    return 1.0 + strength * np.clip(g, -3, 3) / 3.0

def shaded_relief(elev, res_m, elev_min, elev_max,
                  azimuth=315, altitude=45, z_factor=1.0, seed=7,
                  grain_cell_px=2.0, grain_strength=0.05):
    elev = _fill_nan(elev.astype("float32"))
    base = hypsometric(elev, elev_min, elev_max)                  # color
    hs = hillshade(elev, res_m, azimuth, altitude, z_factor) ** HILLSHADE_GAMMA
    tex = texture_pass(elev)
    val = valley_pass(elev)

    light = (0.45 + 0.55 * hs)                                    # never fully black
    light = light * (1.0 - VALLEY_STRENGTH * val)                # sink the valleys
    light = light[..., None]

    img = base * light
    # blend texture as a soft dodge/burn around mid-gray
    img = img * (1.0 + TEXTURE_STRENGTH * (tex[..., None] - 0.5))
    img = img * grain(elev.shape, grain_cell_px, grain_strength, seed)[..., None]
    return (np.clip(img, 0, 1) * 255).astype("uint8")
```

Step 4: Run, verify pass
Run: `pytest tests/test_relief.py -q`
Expected: PASS

Step 5: Eyeball a real crop (the tuning loop starts here)
Run:
```
python - <<'PY'
import json, rasterio, numpy as np
from rasterio.enums import Resampling
from PIL import Image
from app.relief import shaded_relief
cfg = json.load(open("regions/sanpete_ut/region.json"))
with rasterio.open("regions/sanpete_ut/dem.tif") as ds:
    # small representative window at working resolution
    elev = ds.read(1, out_shape=(900, 700), resampling=Resampling.average)
rgb = shaded_relief(elev, res_m=30, elev_min=cfg["elevation_min"], elev_max=cfg["elevation_max"], seed=7)
Image.fromarray(rgb).save("tune.png")
print("wrote tune.png")
PY
```
Expected: `tune.png` looks like real relief. Now tune. Adjust the constants at the top of `relief.py`, re-run this one-liner, and compare to the reference maps. This is the loop you protect: small crop, seconds per change.

Step 6: Commit
```
git add app/relief.py tests/test_relief.py
git commit -m "Relief engine: hillshade, hypsometric tint, texture, valley, grain (tunable baseline)"
```

---

## Phase 5: Rasterize (compose meets paint)

### Task 5.1: Render a spec at any DPI

Files:
- Create: `app/render.py`
- Create: `tests/test_render.py`

Step 1: Write the failing test

```python
# tests/test_render.py
import json, numpy as np
from app.spec import CompositionSpec
from app.render import rasterize

def test_proof_and_final_same_layout():
    cfg = json.load(open("regions/sanpete_ut/region.json"))
    crop = (cfg["bounds"][0]+5000, cfg["bounds"][1]+5000,
            cfg["bounds"][0]+5000+30000, cfg["bounds"][1]+5000+40000)
    spec = CompositionSpec(region_id="sanpete_ut", crs=cfg["crs"], crop=crop,
                           print_w_in=18, print_h_in=24, native_resolution_m=10,
                           tracks=[np.array([[crop[0]+1000, crop[1]+1000],
                                             [crop[2]-1000, crop[3]-1000]])],
                           hotspots=[{"x": (crop[0]+crop[2])/2, "y": (crop[1]+crop[3])/2, "weight": 4}],
                           seed=7)
    region_dir = "regions/sanpete_ut"
    proof = rasterize(spec, dpi=96, region_dir=region_dir, watermark=True)
    final = rasterize(spec, dpi=300, region_dir=region_dir, watermark=False)
    assert proof.size == (1728, 2304)
    assert final.size == (5400, 7200)
```

Step 2: Run, verify fail
Run: `pytest tests/test_render.py -q`
Expected: FAIL

Step 3: Implement

```python
# app/render.py
from __future__ import annotations
import os
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from PIL import Image, ImageDraw, ImageFont
from app.spec import CompositionSpec
from app.relief import shaded_relief

MARGIN_FRAC = 0.06   # read a little past the crop so shadows entering the frame are correct

def _pt_to_px(pt, dpi):  # points -> pixels
    return pt * dpi / 72.0

def _read_window(region_dir, cfg, crop, out_w, out_h):
    """Read the DEM for the crop (plus a margin) at the output resolution.
    rasterio picks the right overview level for us (the image pyramid)."""
    mx = (crop[2] - crop[0]) * MARGIN_FRAC
    my = (crop[3] - crop[1]) * MARGIN_FRAC
    big = (crop[0]-mx, crop[1]-my, crop[2]+mx, crop[3]+my)
    pad_x = round(out_w * MARGIN_FRAC); pad_y = round(out_h * MARGIN_FRAC)
    with rasterio.open(os.path.join(region_dir, cfg["dem_path"])) as ds:
        win = from_bounds(*big, transform=ds.transform)
        elev = ds.read(1, window=win,
                       out_shape=(out_h + 2*pad_y, out_w + 2*pad_x),
                       resampling=Resampling.bilinear, boundless=True, fill_value=np.nan)
    ground_per_px = (crop[2]-crop[0]) / out_w
    return elev, pad_x, pad_y, ground_per_px

def _crs_to_px(x, y, crop, out_w, out_h):
    px = (x - crop[0]) / (crop[2]-crop[0]) * out_w
    py = (crop[3] - y) / (crop[3]-crop[1]) * out_h
    return px, py

def _draw_tracks(base_img, spec, out_w, out_h, dpi):
    # multiply-blend so places ridden many times darken (frequency as weight)
    overlay = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    width = max(1, round(_pt_to_px(spec.track_width_pt, dpi)))
    r, g, b = spec.track_color
    alpha = round(255 * (1 - spec.track_max_darken) ** 0.5)  # per-pass darkening
    for coords in spec.tracks:
        pts = [(_crs_to_px(x, y, spec.crop, out_w, out_h)) for x, y in coords]
        d.line(pts, fill=(r, g, b, max(40, alpha)), width=width, joint="curve")
    return Image.alpha_composite(base_img.convert("RGBA"), overlay)

def _draw_markers(img, spec, elev_lum, out_w, out_h, dpi):
    d = ImageDraw.Draw(img, "RGBA")
    dia = max(6, round(spec.marker_diameter_in * dpi))
    for hs in spec.hotspots:
        cx, cy = _crs_to_px(hs["x"], hs["y"], spec.crop, out_w, out_h)
        if not (0 <= cx <= out_w and 0 <= cy <= out_h):
            continue
        # contrast check: dark marker on light terrain, light marker on dark
        yy = int(np.clip(cy, 0, out_h-1)); xx = int(np.clip(cx, 0, out_w-1))
        lum = elev_lum[yy, xx]
        ring = (244, 240, 228, 255) if lum < 0.5 else (43, 42, 40, 255)
        fill = (199, 169, 85, 255)  # rabbitbrush gold
        r = dia / 2
        d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=fill, outline=ring,
                  width=max(2, dia//12))
    return img

def rasterize(spec: CompositionSpec, dpi: int, region_dir: str,
              watermark: bool = False) -> Image.Image:
    import json
    spec.validate(dpi)
    cfg = json.load(open(os.path.join(region_dir, "region.json")))
    out_w, out_h = spec.pixel_size(dpi)

    elev, pad_x, pad_y, gpp = _read_window(region_dir, cfg, spec.crop, out_w, out_h)
    rgb = shaded_relief(
        elev, res_m=gpp,
        elev_min=cfg["elevation_min"], elev_max=cfg["elevation_max"],
        azimuth=cfg["light_azimuth"], altitude=cfg["light_altitude"],
        z_factor=cfg["z_factor"], seed=spec.seed,
        grain_cell_px=max(1.0, spec.grain_cell_in * dpi),
        grain_strength=spec.grain_strength)
    # trim the margin back to the exact crop
    rgb = rgb[pad_y:pad_y+out_h, pad_x:pad_x+out_w, :]
    base = Image.fromarray(rgb, "RGB")

    lum = (0.2126*rgb[...,0] + 0.7152*rgb[...,1] + 0.0722*rgb[...,2]) / 255.0
    img = _draw_tracks(base, spec, out_w, out_h, dpi)
    img = _draw_markers(img, spec, lum, out_w, out_h, dpi)

    if spec.title_text:
        d = ImageDraw.Draw(img)
        size = max(10, round(_pt_to_px(spec.title_pt, dpi)))
        try:
            font = ImageFont.truetype("Georgia.ttf", size)
        except Exception:
            font = ImageFont.load_default()
        d.text((round(0.04*out_w), round(0.94*out_h)), spec.title_text,
               fill=(43, 42, 40), font=font)

    if watermark:
        d = ImageDraw.Draw(img, "RGBA")
        d.text((out_w//2 - 120, out_h//2), "PROOF", fill=(255, 255, 255, 90))
    return img.convert("RGB")

def save_print(img: Image.Image, path: str, dpi: int):
    img.save(path, dpi=(dpi, dpi))   # embeds DPI so a print shop reads true size
```

Step 4: Run, verify pass
Run: `pytest tests/test_render.py -q`
Expected: PASS. Open the two output sizes from a quick script if you want to confirm the proof predicts the final.

Step 5: Commit
```
git add app/render.py tests/test_render.py
git commit -m "Rasterize: read DEM window at output res, paint relief + tracks + markers in physical units"
```

---

## Phase 6: The thin web app

### Task 6.1: Session store and endpoints

Files:
- Create: `app/session.py`
- Create: `app/main.py`

Step 1: Implement the session store

```python
# app/session.py
import uuid
_SESSIONS = {}   # single user, single machine (invariant: no DB in v1)

def create(data: dict) -> str:
    sid = uuid.uuid4().hex
    _SESSIONS[sid] = data
    return sid

def get(sid: str) -> dict:
    return _SESSIONS[sid]

def update(sid: str, **kw):
    _SESSIONS[sid].update(kw)
```

Step 2: Implement the app

```python
# app/main.py
import io, json, os
import numpy as np
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from app.geo import RegionGeo, crs_to_overview_px, crop_px_to_crs_window
from app.ingest import load_gpx_tracks
from app.density import hotspots
from app.spec import CompositionSpec, ZoomTooTightError
from app import session, render

REGION_ID = "sanpete_ut"
REGION_DIR = os.path.join("regions", REGION_ID)
CFG = json.load(open(os.path.join(REGION_DIR, "region.json")))
GEO = RegionGeo(crs=CFG["crs"], bounds=tuple(CFG["bounds"]),
                overview_size=tuple(CFG["overview_size"]))

app = FastAPI()

@app.post("/api/upload")
async def upload(gpx: UploadFile = File(...)):
    tracks = load_gpx_tracks(await gpx.read(), GEO)
    if not tracks:
        raise HTTPException(400, "No usable tracks in file")
    spots = hotspots(tracks, region_bounds=CFG["bounds"])
    sid = session.create({"tracks": tracks, "hotspots": spots})
    # project to overview pixels for the aim canvas
    tpx = [[crs_to_overview_px(GEO, x, y) for x, y in t.coords] for t in tracks]
    hpx = [{"px": crs_to_overview_px(GEO, s["x"], s["y"]), "weight": s["weight"]} for s in spots]
    return {"session": sid, "overview": f"/regions/{REGION_ID}/overview.png",
            "overview_size": CFG["overview_size"], "tracks": tpx, "hotspots": hpx}

def _build_spec(sid, crop_px, print_w, print_h, dpi, watermark_title=""):
    st = session.get(sid)
    crop = crop_px_to_crs_window(GEO, *crop_px)
    spec = CompositionSpec(
        region_id=REGION_ID, crs=CFG["crs"], crop=crop,
        print_w_in=print_w, print_h_in=print_h,
        native_resolution_m=CFG["native_resolution_m"],
        tracks=[t.coords for t in st["tracks"]],
        hotspots=st["hotspots"], seed=7, title_text=watermark_title)
    spec.validate(dpi)
    session.update(sid, spec=spec)   # stamp it (invariant 1): final renders from this
    return spec

@app.post("/api/proof")
async def proof(session_id: str = Form(...),
                x0: float = Form(...), y0: float = Form(...),
                x1: float = Form(...), y1: float = Form(...),
                print_w: float = Form(18.0), print_h: float = Form(24.0)):
    try:
        spec = _build_spec(session_id, (x0, y0, x1, y1), print_w, print_h, dpi=96)
    except ZoomTooTightError as e:
        raise HTTPException(422, str(e))
    img = render.rasterize(spec, dpi=96, region_dir=REGION_DIR, watermark=True)
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")

@app.post("/api/final")
async def final(session_id: str = Form(...)):
    spec = session.get(session_id).get("spec")
    if spec is None:
        raise HTTPException(400, "Approve a proof first")
    img = render.rasterize(spec, dpi=300, region_dir=REGION_DIR, watermark=False)
    out = os.path.join("regions", REGION_ID, f"final_{session_id}.png")
    render.save_print(img, out, dpi=300)
    return FileResponse(out, media_type="image/png", filename="trailprint.png")

app.mount("/regions", StaticFiles(directory="regions"), name="regions")
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
```

Step 3: Run the server
Run: `uvicorn app.main:app --reload`
Expected: serves on `http://127.0.0.1:8000`

Step 4: Commit
```
git add app/session.py app/main.py
git commit -m "Web app: upload, proof, final endpoints over the render engine"
```

### Task 6.2: The aim-view UI

Files:
- Create: `app/static/index.html`
- Create: `app/static/style.css`
- Create: `app/static/app.js`

Step 1: index.html

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>TrailPrint</title>
<link rel="stylesheet" href="style.css"></head>
<body>
  <header><h1>TrailPrint</h1></header>
  <main>
    <div id="controls">
      <input type="file" id="gpx" accept=".gpx">
      <label>Print <select id="size">
        <option value="18,24">18 x 24</option>
        <option value="24,36">24 x 36</option>
        <option value="12,16">12 x 16</option>
      </select></label>
      <button id="proofBtn" disabled>Render proof</button>
      <button id="acceptBtn" disabled>Accept &amp; render final</button>
    </div>
    <canvas id="map" width="900" height="860"></canvas>
    <div id="proofPane"><img id="proofImg" alt="proof appears here"></div>
  </main>
  <script src="app.js"></script>
</body></html>
```

Step 2: style.css

```css
body { font: 15px/1.4 Georgia, serif; margin: 0; color: #2b2a28; background: #efeae0; }
header { padding: 12px 20px; background: #1a1a1c; color: #ebe6d9; }
header h1 { margin: 0; font-size: 20px; letter-spacing: 1px; }
main { display: grid; grid-template-columns: 900px 1fr; gap: 20px; padding: 20px; }
#controls { grid-column: 1 / -1; display: flex; gap: 14px; align-items: center; }
#map { border: 1px solid #c7a955; cursor: crosshair; background: #ddd; }
#proofPane img { max-width: 100%; box-shadow: 0 4px 18px rgba(0,0,0,.25); }
button:disabled { opacity: .4; }
button { background: #2b2a28; color: #ebe6d9; border: 0; padding: 8px 14px; cursor: pointer; }
</style>
```
(Drop the stray `</style>` line; CSS files need no tags.)

Step 3: app.js

```javascript
const cv = document.getElementById('map');
const ctx = cv.getContext('2d');
const overview = new Image();
let state = { session: null, ovSize: null, tracks: [], hotspots: [], crop: null, scale: 1 };

function ovToCanvas(px, py) {
  return [px * state.scale, py * state.scale];
}
function canvasToOv(cx, cy) {
  return [cx / state.scale, cy / state.scale];
}

function draw() {
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (overview.complete && state.ovSize) ctx.drawImage(overview, 0, 0, cv.width, cv.height);
  ctx.strokeStyle = 'rgba(43,42,40,.7)'; ctx.lineWidth = 1.2;
  for (const t of state.tracks) {
    ctx.beginPath();
    t.forEach(([px, py], i) => { const [x, y] = ovToCanvas(px, py); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.stroke();
  }
  for (const h of state.hotspots) {
    const [x, y] = ovToCanvas(h.px[0], h.px[1]);
    ctx.fillStyle = '#c7a955'; ctx.beginPath(); ctx.arc(x, y, 6, 0, 7); ctx.fill();
  }
  if (state.crop) {
    const [a, b, c, d] = state.crop;
    ctx.strokeStyle = '#c7a955'; ctx.lineWidth = 2;
    ctx.strokeRect(a, b, c - a, d - b);
  }
}

document.getElementById('gpx').onchange = async (e) => {
  const fd = new FormData(); fd.append('gpx', e.target.files[0]);
  const r = await fetch('/api/upload', { method: 'POST', body: fd });
  if (!r.ok) { alert('Upload failed'); return; }
  const j = await r.json();
  state.session = j.session; state.ovSize = j.overview_size;
  state.scale = cv.width / j.overview_size[0];
  cv.height = Math.round(j.overview_size[1] * state.scale);
  state.tracks = j.tracks; state.hotspots = j.hotspots;
  overview.src = j.overview; overview.onload = draw;
  document.getElementById('proofBtn').disabled = false;
};

// drag a crop rectangle locked to the chosen print aspect ratio
let dragStart = null;
cv.onmousedown = (e) => { dragStart = [e.offsetX, e.offsetY]; };
cv.onmousemove = (e) => {
  if (!dragStart) return;
  const [sw, sh] = document.getElementById('size').value.split(',').map(Number);
  const ar = sw / sh;
  let w = e.offsetX - dragStart[0];
  let h = w / ar;
  state.crop = [dragStart[0], dragStart[1], dragStart[0] + w, dragStart[1] + h];
  draw();
};
cv.onmouseup = () => { dragStart = null; };

document.getElementById('proofBtn').onclick = async () => {
  if (!state.crop) { alert('Drag a crop box first'); return; }
  const [sw, sh] = document.getElementById('size').value.split(',').map(Number);
  const [a, b, c, d] = state.crop.map((v, i) => canvasToOv(...(i % 2 === 0 ? [v, 0] : [0, v]))[i % 2]);
  const fd = new FormData();
  fd.append('session_id', state.session);
  fd.append('x0', a); fd.append('y0', b); fd.append('x1', c); fd.append('y1', d);
  fd.append('print_w', sw); fd.append('print_h', sh);
  const r = await fetch('/api/proof', { method: 'POST', body: fd });
  if (!r.ok) { alert('Proof rejected: ' + (await r.text())); return; }
  document.getElementById('proofImg').src = URL.createObjectURL(await r.blob());
  document.getElementById('acceptBtn').disabled = false;
};

document.getElementById('acceptBtn').onclick = async () => {
  const fd = new FormData(); fd.append('session_id', state.session);
  const r = await fetch('/api/final', { method: 'POST', body: fd });
  if (!r.ok) { alert('Final failed'); return; }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(await r.blob()); a.download = 'trailprint.png'; a.click();
};
```

Step 4: Manual end-to-end check
Run: `uvicorn app.main:app --reload`, open `http://127.0.0.1:8000`, upload your real GPX, confirm the tracks sit on the right terrain, drag a crop, render a proof, accept, and open the downloaded final.
Expected: a framable poster of your region with your tracks on it, proof and final matching.

Step 5: Commit
```
git add app/static/
git commit -m "Aim-view UI: upload, crop, proof preview, final download"
```

---

## Phase 7: The concierge loop (how you actually deliver v1)

No code. The delivery model for v1 is you at the keyboard. A client either sits with you or reaches your Mac through a secure tunnel for a live session. Sequence:

1. Client uploads their GPX and frames the crop in the browser.
2. They render the mid-fidelity proof. They decide on the proof, never on the rough aim view.
3. On accept, the full render runs on your Mac and they get the file, or you send it to a print shop.

If you want a remote client to reach your machine without deploying anything, run `uvicorn` and expose port 8000 through a tunnel (for example `cloudflared tunnel --url http://localhost:8000`). That is a session convenience, not infrastructure, and it is the natural bridge to v1.3.

---

## Roadmap beyond v1

Lighter on purpose. What you learn shipping and showing v1 will reshape all of this. Each item names the seam in v1 that already accommodates it, so none of these is a teardown.

### v1.1 — Make it personal (photos and richer markers)
Adds: photo upload, EXIF GPS read, HEIC support, geotag-to-hotspot matching, manual placement for the many photos that carry no GPS (your A7SIII files), textured photo frames, and emoji or icon glyph markers.
Seam it uses: the CompositionSpec already carries `hotspots`. Photos become an optional field on a hotspot, and `_draw_markers` gains a photo-frame branch. Nothing upstream changes. Manual placement is a new drag interaction in the aim canvas writing back to the same spec.

### v1.2 — Make it scale across terrain (more regions, soul passes baked)
Adds: several curated regions, KML import for Avenza, and pre-baked soul-pass layers per pyramid level (true texture shading, multidirectional hillshade, sky-view occlusion) so very large regions render fast and consistently.
Seam it uses: `region_prep.py` already writes a per-region config and a COG with overviews. Baked soul layers become extra bands or sibling COGs the config points to, and `render._read_window` reads them alongside elevation instead of computing them live. The relief constants you tuned in v1 become the recipe stored in `region.json`.

### v1.3 — Make it unattended (lift the same engine to a server)
Adds: a job queue and a worker so proofs and finals render without you at the keyboard, plus object storage for uploads and outputs, and a Postgres job table replacing the in-memory session dict.
Seam it uses: the compose-then-rasterize split is exactly a queue boundary. A job is a stamped CompositionSpec. `session.py` is the only file that gets swapped for a database, because the spec was always the unit of work. The concierge tunnel from Phase 7 is the rehearsal for this.

### v1.4 — Make it a business (accounts, payment, fulfillment)
Adds: user accounts, checkout before the final render, and a print-on-demand integration so a framed print ships to the client.
Seam it uses: the final render is already gated behind an explicit accept. Payment slots in front of `/api/final` as a precondition, and fulfillment consumes the same print-ready file the engine already produces at true DPI.

---

## Build order and the one rule

Build the phases in order. Phase 1 (registration) and Phase 4 (the relief) are where the value and the risk both concentrate, so reach a tuned `tune.png` you would frame before wiring the web app around it. The single rule that keeps every later version an addition rather than a rebuild: decide the picture once as a CompositionSpec, and paint that spec at whatever resolution the moment calls for.
