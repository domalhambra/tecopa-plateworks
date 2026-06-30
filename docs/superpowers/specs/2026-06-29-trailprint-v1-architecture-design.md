# TrailPrint v1 Architecture Completion — Design Spec

Date: 2026-06-29
Status: Approved (design), pending implementation plan

## Goal

Finish the v1 technical architecture so TrailPrint can produce a finished, printable
map. Stays single-user and local — no database, job queue, or hosting (those are the
deferred v1.3 seams). Four product decisions, locked with the user:

1. Scope: **finish v1 features locally** (no server seams).
2. Hydrography: **lakes + major rivers**.
3. Multi-file upload: **accumulate into one map**.
4. Print target: **18 × 24 portrait** → re-fetch a properly-sized, NaN-trimmed region.

Five components: region pipeline, hydrography rendering, KML/KMZ ingest, upload
UI + API, and the tests that lock them. The compose→rasterize seam and all six
invariants are preserved; nothing here recomputes the picture twice or sizes a
visual element in pixels.

## Component 1 — Region pipeline (`region_prep.py`)

**Sizing for 18 × 24 @ 300 dpi.** The zoom cap floor is 10 m/px → 3000 m per print
inch, so an 18 × 24 crop needs 54 × 72 km of ground. Fetch a region with pan room:
bbox ≈ `-121.06 40.16 -120.34 40.85` (~61 × 77 km), centered on the
Susanville–Eagle Lake corridor, EPSG:32610, 10 m grid.

**Clip out the NaN border.** After reprojecting the py3dep DEM (EPSG:5070 Albers)
to UTM, the axis-aligned UTM extent is larger than the data quad, leaving NaN
corners (~36%). Fix: clip the reprojected raster to the UTM box of the requested
geographic bbox (`dem_da.rio.clip_box(...)`), which sits strictly inside the data,
so `dem.tif` is fully valid, the aim view is clean, and `region.json.bounds` is honest.

**`region.json` additions:** `"hydro_path": "hydro.json"`.

## Component 2 — Hydrography

### Fetch + bake (`region_prep.py`)
Fetch USGS NHD via `pynhd` (HyRiver family, installs clean on 3.14 like py3dep):
- Waterbodies (lakes/reservoirs/ponds) polygons within the bbox.
- Flowlines, filtered to **stream order ≥ 3** ("major" rivers).

Reproject to the region CRS, simplify, and write a sidecar **`hydro.json`**:

```json
{
  "crs": "EPSG:32610",
  "lakes":  [ {"coords": [[x,y], ...], "name": "Eagle Lake"} ],
  "rivers": [ {"coords": [[x,y], ...], "order": 4, "name": "Susan River"} ]
}
```

Coords are CRS metres (exterior rings for lakes, polylines for rivers). On no NHD
coverage, write empty lists (render simply draws no water).

A `bake_hydro(waterbodies_gdf, flowlines_gdf, crs, simplify_m) -> dict` function
holds the reproject/simplify/serialize logic, separable from the live fetch so it
is unit-testable with synthetic geometries.

### Render (`render.py`)
**Decision: vector, drawn at paint time — not a baked raster.** A baked 10 m river
line is 1 px at the final but sub-pixel at the proof (it would vanish), breaking
proof-predicts-final — the same class of bug just fixed for the relief radii.
Drawing water in physical units (line widths in points, scaled by DPI) keeps it
consistent across sizes.

`render.rasterize` reads `hydro.json` from `region_dir` (region-level data, like the
DEM — not on the spec). New `_draw_hydro(img, hydro, spec, out_w, out_h, dpi)`,
composited **relief → water → tracks → markers → title**:
- Lakes: fill the polygon flat in a muted slate-blue (no hillshade — water is flat),
  with a slightly darker soft shoreline. Anti-alias via a supersampled mask or edge blur.
- Rivers: water-colored polylines, width in points scaled by stream order
  (`base_pt + step_pt*(order-3)`, capped), feathered like the track ink.

Tunable style constants live at the top of `render.py` (WATER_FILL, WATER_SHORELINE,
RIVER_COLOR, RIVER_BASE_PT, RIVER_STEP_PT), the same pattern as the track/relief levers.

## Component 3 — KML/KMZ ingest (`ingest.py`)

Refactor the reproject → drop-non-finite → simplify → day-extract logic into a shared
`_make_track(pts, region, name, idx)` (pts = list of `(lon, lat, time|None)`), used by
both parsers so density/spec/render are untouched (same `Track` output).

- `load_gpx_tracks(data, region, ...)` — unchanged behavior, now via `_make_track`.
- `load_kml_tracks(data, region, ...)` — parse with **`lxml`** (already installed; no new
  dependency). Handle `<LineString><coordinates>` and Google `<gx:Track>`
  (`<gx:coord>` + `<when>`), with kml/gx namespaces.
- `load_tracks(data, region, filename=None)` — dispatch: `PK\x03\x04` magic → KMZ
  (unzip first `.kml`) → KML; `<gpx` → GPX; `<kml` → KML; else fall back to extension.

## Component 4 — Upload UI + API

### API (`app/main.py`)
`/api/upload` accepts a file **list** plus optional `session_id`:
- Parse each file via `load_tracks` (auto-detect GPX/KML/KMZ).
- If `session_id` exists, **append** to its tracks; else create a new session.
- Recompute hotspots over the full accumulated set; return merged track/hotspot
  projections + overview.
- 400 only if the result has zero usable tracks.

`session.py` gains a safe `has(sid)` / membership check so unknown ids are handled.

### UI (`app/static/`)
- A drag-and-drop zone ("Drop GPX / KML / KMZ here, or click to browse"),
  `multiple` file input.
- A file list (name + track count) and a **Clear** button (client forgets the
  session id and resets the canvas).
- Each drop POSTs the files with the current `session_id` so they accumulate.
- Crop → proof → final flow unchanged.

## Data flow

```
region_prep (offline):  3DEP DEM ─┐                 NHD water ─┐
                                  ├─ reproject+clip ─ dem.tif   ├─ bake ─ hydro.json
                                  └─ overview.png + region.json ┘
runtime: upload(files[]) → load_tracks (GPX/KML/KMZ) → accumulate in session
       → density → hotspots → [crop] → CompositionSpec
       → rasterize(spec, dpi): read dem.tif window + hydro.json
         → relief → water → tracks → markers → title  → PNG
```

## Testing

- `test_ingest`: KML `<LineString>`, KML `<gx:Track>` with timestamps, KMZ (zip a KML
  in-memory), dispatch by content sniff; existing GPX tests stay green.
- `test_render`: water compositing — synthetic `hydro.json` with a lake polygon + a
  river over a crop; assert lake-area pixels become water-colored and differ from the
  no-hydro render; rivers render.
- `test_main`: multi-file accumulate (two files in one request combine; a second
  upload with `session_id` appends).
- `bake_hydro`: unit-test reproject/simplify/serialize with synthetic geometries (no
  live fetch).
- Region rebuild + registration: re-run `region_prep`, re-assert the Susanville
  control point on the new DEM.

## Build order

1. Region pipeline: sizing + clip-to-bbox + hydro fetch/bake → new clean Lassen region.
2. KML/KMZ ingest (refactor + parser + tests).
3. Render hydrography (water layer + styling).
4. Upload UI + multi-file API.
5. End-to-end verify (finalized poster) + adversarial correctness review.

## Risks / open

- `pynhd` API surface + NHD coverage for the bbox; empty-water fallback handles gaps.
- Larger DEM fetch (~190 MB, a few minutes); one-time.
- KML variant coverage (LineString vs gx:Track, namespaces) — tests pin the common shapes.
- Water color/weight is a by-eye lever, tuned after the pipeline lands.
