# TrailPrint

A single local app that imports GPX tracks and renders a shaded-relief poster of
where you've been within one curated region. One FastAPI process serves a thin
browser aim view and the render engine; all real rendering happens server-side in
Python.

The engine is split at one seam: **compose** decides the picture once in ground
coordinates and emits a `CompositionSpec`; **rasterize** paints that spec at any
resolution. The proof and the final are the same spec painted at two pixel sizes.

## Setup

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-lock.txt        # pinned core + test stack (what CI installs)
python -c "import rasterio, pyproj, numpy, scipy, shapely, gpxpy, PIL; print('ok')"
```

- `requirements.txt` — core runtime (unpinned minimums); `requirements-dev.txt` adds the
  test deps; `requirements-lock.txt` is the exact pinned set (determinism / CI).
- `requirements-regionprep.txt` — the heavy offline build stack for `region_prep.py`
  (py3dep/pynhd/pandas/geopandas). Only needed to build a new region.

On Apple Silicon, rasterio / pyproj / Pillow ship native wheels — no Homebrew GDAL
required.

## Layout

- `app/geo.py` — every coordinate conversion (overview px ↔ CRS meters ↔ windows)
- `app/ingest.py` — GPX → reproject → simplify → clean projected polylines
- `app/density.py` — visitation-weighted hotspots (count distinct tracks, not points)
- `app/spec.py` — the `CompositionSpec` contract + zoom-cap validation
- `app/relief.py` — pure-numpy relief passes (hillshade, hypsometric, texture, valley, grain)
- `app/render.py` — read DEM window, paint relief + tracks + markers in physical units
- `app/main.py` — three endpoints over the engine (upload, proof, final)
- `region_prep.py` — offline, one-time: fetch 3DEP DEM, build COG + overview + region.json

## Invariants

1. One spec, painted at many sizes — never compute the picture twice.
2. Physical units (points / inches), never pixels, for anything visual.
3. Determinism — fixed seed on the spec; same spec → same image.
4. One projection throughout — DEM, overview, tracks, crop all in the region CRS.
5. Registration is correctness — prove the coordinate chain before tuning aesthetics.
6. The zoom cap — never request finer ground detail than the data holds.

## Tests

```
pytest -q
```

The real 3DEP DEMs are gitignored, so `tests/conftest.py` hydrates a tiny synthetic DEM
per region on first run — the endpoint / render / registration suites run on a fresh
clone and in CI (GitHub Actions, `.github/workflows/ci.yml`) rather than skipping. A
machine with real DEMs runs them against real terrain instead. `/readyz` reports whether
every region has a present DEM whose bounds match its `region.json`.
