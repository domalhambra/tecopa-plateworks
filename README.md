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
- `app/provenance.py` — the self-describing-poster manifest (embed / extract / sanitize)
- `app/main.py` — the endpoints over the engine (upload, proof, final, reprint)
- `region_prep.py` — offline, one-time: fetch 3DEP DEM, build COG + overview + region.json
- `scripts/build_labels.py` — offline: fetch GNIS terrain names → `regions/<id>/labels.json`

## Named geography (GNIS labels)

The `Place names` toggle draws named geography on the sheet: terrain features (ranges,
summits, passes, valleys, desert flats) from `regions/<id>/labels.json` — built offline
by `scripts/build_labels.py` from the USGS GNIS Landforms service — plus the water names
already carried in `hydro.json`. `render._draw_labels` places them with priority +
greedy collision avoidance (range → summit → lake → pass → valley → river), a knockout
paper halo for legibility, and a per-sheet density cap. Ranges/deserts read as wide
tracked caps; everything else is a haloed point label. All sizes are physical, so the
proof and final place the same names (invariant 1). Rebuild after adding a region:
`python scripts/build_labels.py <id>`.

## Self-describing posters ("the file is the artwork")

Every PNG final embeds a provenance manifest in one compressed `zTXt` chunk (see
`app/provenance.py`): the full `CompositionSpec`, the sha256 of each source GPX, and
the engine/schema version. That makes the file **stateless-reprintable** —
`POST /api/reprint` re-renders any TrailPrint PNG at print resolution from the file
alone (no session, no DB), and `POST /api/reprint/inspect` reads its provenance
without rendering. Same spec → pixel-identical reprint (invariants 1 + 3).

- **Privacy:** the manifest carries the exact track coordinates. The proof step's
  *Reprintable file* toggle (form field `embed_spec`, default on) turns it off to
  produce a share copy with no embedded spec. PDF finals never carry the manifest
  (Pillow's PDF writer has no metadata seam) — self-describing posters are PNG-only.
- **Security:** a reprint spec is untrusted input. `provenance.sanitize_photos` keeps
  a hotspot photo only if its real path stays inside the uploads dir (else drops it),
  and `spec.validate` re-enforces aspect / the 120 MP ceiling / the zoom cap before any
  pixels are made — a crafted PNG can neither read server files nor request a gigapixel.
- **Forever-contract:** `tests/fixtures/manifest_v1.json` freezes the v1 schema; a
  poster a user printed today must still reprint after future upgrades.

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
