# Real-network demo tracks for the marketing farm

**Date:** 2026-08-15 · **Status:** Approved by Dom (this session) · **Scope:** `scripts/` only — no engine changes

## Problem

The farm's `_synth_tracks` invents journey geometry from region bounds alone:
sine-wave meanders radiating from a single base camp at the plate center
(`R = span * 0.24`). On a real poster this reads as squiggles drawn at random —
routes follow no roads or trails — and the ink pools in the middle of the plate,
leaving the corners empty. `assets/elko_bonneville/poster.png` (2026-08-15) is
the exhibit: a 165-mile corridor plate with all seven days clustered in one spot.

Two requirements, verbatim from Dom:

1. Example routes must follow **actual road and offroad data**, so they look like
   travel rather than scribbles.
2. Tracks must be **far-reaching** enough to make the whole poster interesting —
   no clustering in the middle with empty space around it.

## Decisions already made (with Dom, 2026-08-15)

| Decision | Choice | Why |
|---|---|---|
| Network source | **OSM via Overpass** (roads + 4WD + hiking trails) | Only source with singletrack; journeys read as backcountry trips, matching the brand. TIGER (PD) has no hiking trails. |
| Where the data lives | **Marketing-only gitignored cache**, never in plates | Plates are CC0; OSM is ODbL and can never be committed into them. `cache/` is already gitignored. |
| Demo story | **A year of trips** — 6–8 separate outings across the plate | One base-camp trip is *why* ink pools centrally. Separate outings in different corners fill the plate and match the product pitch ("your years outdoors"). |

## Design

One seam swap: everything downstream of the farm (`poster`, `film`, `editions`,
`wallpapers`, `mockups`, `model`, `detail`, `coin`) consumes `tracks` + `spots`.
Only the generator changes.

### 1 · Network fetch — `scripts/fetch_track_network.py`

New operator-run script, one plate per invocation (like `region_prep.py`):

- Query Overpass for ways in the region's `lonlat_bbox` with
  `highway=motorway|trunk|primary|secondary|tertiary|unclassified|residential|
  service|track|path|footway|bridleway|cycleway`.
- Classify each way: `road` (paved/residential/service), `4wd`
  (`highway=track`), `trail` (`path|footway|bridleway|cycleway`).
- Reproject node coordinates to the region CRS (`pyproj`, same one-projection
  rule as everything else).
- Write `cache/networks/<region_id>.json`: `{fetched: <iso date>, source:
  "OpenStreetMap via Overpass, ODbL", ways: [{class, nodes: [[x,y],…]}, …]}`.
- Cache is the **snapshot of record**: renders never touch live Overpass, so
  same cache + seed → identical tracks → identical image (within-build
  determinism, invariant 3, holds).
- Respect Overpass etiquette: single request per plate, retry with backoff,
  honest failure message pointing at the public mirror list.

**Licensing:** ODbL data stays in the gitignored cache. The rendered posters are
ODbL "produced works" → attribution, not share-alike: one footer line on the
landing page — `Demo route geometry © OpenStreetMap contributors`. Nothing else
in the repo carries OSM data. Plates stay CC0-clean.

### 2 · Graph + routing — `scripts/track_network.py`

- Build an undirected graph from the cached ways, **vertex-per-point**: every
  way point is a vertex keyed by its coordinates rounded to 0.1 m, and each
  consecutive pair becomes an edge. Ways that share an OSM node therefore
  connect automatically, and there is no way-splitting step to get wrong.

  > **Amended 2026-08-15 (implementation review).** This section originally
  > specified intersection-only nodes with full polyline geometry on each edge.
  > Vertex-per-point trades a larger graph for the removal of the entire
  > way-splitting code path — the part most likely to harbour a silent
  > topology bug. The cost is real: vertex and edge counts multiply by roughly
  > the average points-per-way, which Dijkstra pays directly. It is
  > **measured, not assumed** — the Task 9 real-plate smoke test reports
  > graph size and routing wall-clock. If routing proves too slow there, the
  > fix is a localised `contract_chains()` pass that collapses degree-2 runs
  > into polyline edges, recovering the intersection-only graph behind the
  > same API, rather than reworking the composer.
- Dijkstra over `heapq` (no new dependency; county-scale networks are small).
- Class-weighted edge costs: outing legs prefer `trail`/`4wd` (cost × 0.6),
  approach legs prefer `road`. Weights are constants in this module.

### 3 · Journey composition — `network_tracks(region, net, n_trips, seed)`

Seeded (`np.random.default_rng(seed)`), fully deterministic:

- **Destination pool:** real named places from two committed plate files —
  `labels.json` entries of kind `summit`/`gap` (point coords), and named lakes
  from `hydro.json` (`lakes: [{name, coords}]`, destination = polygon
  centroid). (`labels.json` has **no** `lake` kind — verified across all five
  plates — so lakes must come from `hydro.json`.) Every candidate is snapped to
  the nearest network node within 2 km; entries that snap nowhere are dropped.
- **Coverage guarantee:** partition the plate into a 3×3 grid; greedy
  farthest-point selection of 6–8 destinations, never picking a cell twice
  until all occupied cells are used. This is the mechanical fix for
  requirement 2.
- **Trip shapes**, chosen per destination by seeded draw: out-and-back
  (trailhead → destination → back), loop where the network offers two
  sufficiently disjoint paths (disjointness threshold is a module constant,
  like the edge costs), or a 4WD day (route dominated by `4wd` ways).
- **Worn path:** one or two trailheads are reused across trips so the
  visitation-density story (`density.py` hotspots) survives.
- **Dates:** spread across the year by **kind-based season buckets** —
  lakes early (Mar–Jun), gaps mid (Jun–Aug), summits late (Jul–Oct) — with
  seeded jitter inside each bucket. Deliberately **not** DEM-sampled: elevation
  from the DEM would make dates a function of cache + seed + *DEM*, breaking
  the §1 determinism statement on hosts whose plates carry synthetic stand-in
  DEMs. Kind buckets are deterministic from committed plate data alone. The
  film becomes "the year drawing itself".
- **GPS realism:** densify edge geometry to ~15 m spacing, add seeded ~3 m
  jitter, so ink reads recorded rather than vector-perfect.
- **Hotspots:** destinations become the hotspot list directly, carrying their
  **real names** ("Antelope Mountain") — `density.hotspots` is **not consulted**
  for network tracks (the worn-path bullet above is about the rendered ink
  weave, not the spot list). `_annotate` changes accordingly: it assigns a
  label only to spots that arrive without one, and keeps assigning icons and
  the pinned photo for all.

### 4 · Farm integration + fallback

- `render_asset_farm.py`: if `cache/networks/<region>.json` exists →
  `network_tracks`; else → the existing `_synth_tracks`, unchanged, with a
  one-line notice. The farm still runs on a fresh clone and in CI with zero
  network access; the test suite is untouched by default.
- `--synthetic-tracks` flag forces the old generator (parity with
  `--synthetic-dem`).

### 5 · Marketing honesty

The journeys remain invented demos — that does not change and no copy claims
otherwise. They now travel real roads and real trails. No new claims → the
claims register is untouched. The only page change is the OSM attribution line.

## Testing (TDD, fixture-driven — no Overpass in tests)

New `tests/test_track_network.py` with a small hand-built fixture network:

1. Graph build: intersections become shared nodes; edge geometry survives.
2. Routing: Dijkstra picks the trail-weighted path when one exists.
3. Coverage: union bbox of generated tracks spans ≥ 60% of the plate in both
   axes, and ≥ 5 of the 3×3 cells receive ink.
4. Determinism: same cache + seed → identical coordinate arrays.
5. Fallback: no cache file → `_synth_tracks` output, byte-identical to today.
6. Snapping: candidates (label points and lake centroids alike) beyond 2 km of
   the network are dropped, never mis-anchored.

`fetch_track_network.py` itself is verified by hand against one plate (network-
dependent, same policy as `region_prep.py`).

## Rollout

1. Land the code (tests green).
2. Fetch network caches for all five plates.
3. Re-render: full farm for `lassen_ca`; `--only poster model` for the other
   four (elko at `--dpi 220`).
4. Eyeball each poster for coverage and route plausibility.
5. `build_deploy.py` → `netlify deploy --prod` → live verification (including
   the new attribution line).

## Out of scope

- Any engine (`app/`) change; any plate/`region_prep.py` change.
- Roads as rendered basemap furniture (a possible future, deliberately not now).
- Elevation-aware routing (DEM-costed paths) — YAGNI for demo imagery.
- Committing network data anywhere (licensing forbids it).
