# Order Plate per Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `scripts/order.py prepare <folder>` reads a customer's tracks, frames them nestled, and reuses or builds a plate sized to the print, with terrain as fine as the print can show and at most 2× upsampled.

**Architecture:** Pure planning lives in `app/orderplate.py` (framing, projection, grid choice). The order folder and its state live in `app/order.py`. `app/orderprep.py` runs Prepare and calls the fetch stack only as `.venv-prep` subprocesses: `scripts/dem_coverage.py` for 3DEP coverage, and `region_prep.py` plus `scripts/build_labels.py` through the existing `regionbuild.run_build`. `region_prep.py` learns to fetch one 3DEP layer and warp it onto a different grid, so a plate is never larger than its print needs.

**Tech Stack:** Python 3.14, pyproj, rasterio, `tomllib`, py3dep 0.19 (`.venv-prep` only), pytest.

**Spec:** `docs/superpowers/specs/2026-09-24-order-pipeline-design.md`, sections 1–3 and the Amendments. This plan is sub-project 1 of 5.

---

## Before you start

- Read `CLAUDE.md` (invariants 4, 6, 12, 13) and `docs/changing-things.md` › Build a new plate.
- Two venvs. `.venv` runs the app and the tests. `.venv-prep` runs anything that imports py3dep or pynhd. Never install the prep stack into `.venv`.
- Baseline: `tests/test_output_fitness.py::test_mp4_twin_is_tagged_bt709` already fails on `main` on Dom's Mac (the local ffmpeg writes no `colr` box). Compare failure sets, not totals.
- Fast suite: `.venv/bin/python -m pytest -n auto -m "not slow" -q`. Full suite before any push to `main`: `.venv/bin/python -m pytest -n auto -q`.

## Decisions made while planning (they refine the spec)

1. **The grid and the fetched layer are separate.** The spec said "add 3 m and 1 m to `DEM_RES_CHOICES`". That would make the in-app auto planner pick 1 m for small plates. Instead, `DEM_RES_CHOICES` stays `(10, 30, 60)`. An order passes an explicit grid (`--resolution`) and the layer to fetch (`--source-resolution`). A 25 m grid is fetched from the 10 m static layer and averaged down. The plate then holds about 1.44× the print's pixels, whatever the ground size.
2. **Below 10 m, the grid is fetched from the 3DEP dynamic service at the grid's own cell size.** The service resamples the finest source it holds. Task 1 checks that it really delivers lidar detail. If it does not, `USE_DYNAMIC_FINE = False` and orders use the static layers with the 2× rule.
3. **The 2× cap is global.** `spec.validate` and the studio's red tint allow 2×. The default framing (`starter_crop`, `refit_crop_aspect`, the studio's refit, wallpaper floors) still aims for 1×, so nothing gets softer unless someone asks for a tighter frame.
4. **3DEP has no 3 m data at Tecopa** (index query, 2026-09-24: 1 m yes, 3 m no). The coverage check is required, not optional.

## File map

| File | Change | Responsibility |
|---|---|---|
| `app/spec.py` | modify | `MAX_UPSAMPLE`, the 2× zoom cap |
| `app/regions.py` | modify | `max_upsample` in `Region.meta()` for the studio |
| `app/static/canvas.js` | modify | the studio's too-tight and infeasible checks at 2× |
| `region_prep.py` | modify | grid and source decoupled, `--out-root`, coverage helpers |
| `scripts/dem_coverage.py` | create | 3DEP coverage per layer as JSON, in `.venv-prep` |
| `scripts/build_labels.py` | modify | `--root` for plates outside `regions/` |
| `app/regionbuild.py` | modify | `run_build` passes grid, source, out-root and env |
| `app/orderplate.py` | create | pure plate planning for one order |
| `app/order.py` | create | the order folder, `order.toml`, `state.json` |
| `app/orderprep.py` | create | Prepare: plan, reuse or build, state, report |
| `scripts/order.py` | create | the command line |
| tests | create/modify | one test file per module, listed per task |
| docs | modify | Task 10 |

---

### Task 1: Check that the 3DEP dynamic service delivers lidar detail

**Goal:** Measure whether a 3 m grid fetched from the dynamic service holds more terrain detail than the 10 m static layer, and record the result for Task 6.

**Files:**
- Create: `$TMPDIR/probe_dynamic_dem.py` (throwaway, not committed)

**Acceptance Criteria:**
- [ ] The probe prints the NaN share and the Laplacian standard deviation for both grids.
- [ ] Two hillshade PNGs exist for a side-by-side look.
- [ ] The result (PASS or FAIL, with the numbers) is written down for Task 6 and Task 10.

**Verify:** `.venv-prep/bin/python $TMPDIR/probe_dynamic_dem.py` → a line `nan share … ratio …`. PASS when the ratio is 1.5 or more and the NaN share is under 0.05.

**Steps:**

- [ ] **Step 1: Write the probe**

```python
# probe_dynamic_dem.py -- throwaway check for the order-plate plan, Task 1.
import os
import certifi
os.environ.setdefault("SSL_CERT_FILE", certifi.where())   # before py3dep (aiohttp)
import numpy as np
import py3dep
from PIL import Image
from rasterio.enums import Resampling

BBOX = (-116.27, 35.88, -116.24, 35.91)   # Tecopa: the 3DEP index lists 1 m lidar here
CRS = "EPSG:32611"
CELL = 3.0


def on_grid(resolution):
    da = py3dep.get_dem(BBOX, resolution)
    out = da.rio.reproject(CRS, resolution=CELL, resampling=Resampling.bilinear)
    z = out.values.squeeze().astype("f8")
    return z[5:-5, 5:-5]


def laplacian_std(z):
    lap = (4 * z[1:-1, 1:-1] - z[:-2, 1:-1] - z[2:, 1:-1]
           - z[1:-1, :-2] - z[1:-1, 2:])
    return float(np.nanstd(lap))


def shade(z, path):
    gy, gx = np.gradient(np.nan_to_num(z, nan=np.nanmean(z)), CELL)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.radians(315), np.radians(45)
    hs = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    Image.fromarray((np.clip(hs, 0, 1) * 255).astype("uint8")).save(path)


dyn = on_grid(3)      # not 10/30/60, so py3dep uses the dynamic service (get_map)
sta = on_grid(10)     # the static 10 m tiles, bilinear up to the same 3 m grid
ld, ls = laplacian_std(dyn), laplacian_std(sta)
print(f"nan share {float(np.isnan(dyn).mean()):.4f}  laplacian std: "
      f"dynamic 3 m {ld:.3f}  static 10 m {ls:.3f}  ratio {ld / ls:.2f}")
shade(dyn, os.path.join(os.environ.get("TMPDIR", "."), "probe_dynamic_3m.png"))
shade(sta, os.path.join(os.environ.get("TMPDIR", "."), "probe_static_10m.png"))
```

- [ ] **Step 2: Run it from the repo root**

Run: `.venv-prep/bin/python $TMPDIR/probe_dynamic_dem.py`
Expected: one line of numbers, and two PNGs in `$TMPDIR`.

- [ ] **Step 3: Decide and record**

PASS (ratio ≥ 1.5 and NaN share < 0.05): Task 6 keeps `USE_DYNAMIC_FINE = True`.
FAIL: Task 6 sets `USE_DYNAMIC_FINE = False`. Tell Dom before you continue, because the spec's "fetch the finest 3DEP data" then reduces to the 10 m layer plus the 2× rule.
Write the numbers into your task notes. Task 10 copies them into `docs/decisions.md`. Show Dom the two PNGs.

No commit. The probe is not part of the repo.

---

### Task 2: The zoom cap allows 2× upsampling (invariant 6)

**Goal:** `CompositionSpec.validate` and the studio accept a frame up to 2× finer than the plate's data, and refuse past it.

**Files:**
- Modify: `app/spec.py` (constant below `FINAL_DPI`, near line 32; the zoom-cap block near line 375)
- Modify: `app/regions.py` (`Region.meta`)
- Modify: `app/static/canvas.js:95-128`
- Modify: `CLAUDE.md` (invariant 6)
- Test: `tests/test_spec.py`, `tests/test_regions.py`

**Acceptance Criteria:**
- [ ] A 10 m plate validates a crop at exactly 5.0 m/px at 300 dpi.
- [ ] A 10 m plate refuses 4.8 m/px with `ZoomTooTightError` whose message says `data floor is 5 m/px`.
- [ ] `Region.meta()` carries `max_upsample: 2.0`.
- [ ] `cropBelowFloor`, `sizeInfeasibleForRegion` and `presetInfeasibleForRegion` divide the floor by `r.max_upsample`. The refit floor at `canvas.js:76` stays at 1×.
- [ ] `node --check app/static/canvas.js` passes, and `tests/test_docs.py` passes (the `CLAUDE.md` token budget).

**Verify:** `.venv/bin/python -m pytest tests/test_spec.py tests/test_regions.py tests/test_docs.py -q` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing tests** in `tests/test_spec.py`, after `test_zoom_cap_allows_exactly_native`:

```python
def test_zoom_cap_allows_up_to_2x_upsampling():
    # Invariant 6, amended 2026-09-24: 27000 m / 5400 px = exactly 5.0 m/px on a
    # 10 m plate is a 2x upsample, the most allowed (the cap is a strict `<`).
    s = CompositionSpec(**base_kwargs(crop=(430000.0, 4345000.0, 457000.0, 4381000.0)))
    assert s.ground_per_pixel(300) == 5.0
    assert s.validate(dpi=300) is s


def test_zoom_cap_rejects_past_2x():
    # 26000 m / 5400 px = 4.81 m/px: past 2x on a 10 m plate
    s = CompositionSpec(**base_kwargs(crop=(430000.0, 4345000.0, 456000.0, 4379666.67)))
    with pytest.raises(ZoomTooTightError, match="data floor is 5 m/px"):
        s.validate(dpi=300)
```

And in `tests/test_regions.py`, at the end of `test_region_meta_shape`:

```python
    assert m["max_upsample"] == 2.0     # the studio's zoom floor divides by this
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_spec.py -k "2x" tests/test_regions.py::test_region_meta_shape -q`
Expected: `test_zoom_cap_allows_up_to_2x_upsampling` FAILS with `ZoomTooTightError`, and `test_region_meta_shape` FAILS with `KeyError: 'max_upsample'`.

- [ ] **Step 3: Implement.** In `app/spec.py`, after `FINAL_DPI = 300`:

```python
# Invariant 6: a final may ask for up to MAX_UPSAMPLE times finer ground than the plate
# holds. render.py reads the DEM bilinear, so a 2x upsample stays smooth; past 2x the
# relief goes soft and the cap refuses. Default framing still aims for 1x.
MAX_UPSAMPLE = 2.0
```

Replace the zoom-cap `if` block in `validate` (the lines from `if gpp < self.native_resolution_m:` to the closing parenthesis of the raise):

```python
        floor_m = self.native_resolution_m / MAX_UPSAMPLE
        if gpp < floor_m:
            raise ZoomTooTightError(
                f"{gpp:.1f} m/px requested, data floor is {floor_m:g} m/px "
                f"({self.native_resolution_m:g} m plate, at most "
                f"{MAX_UPSAMPLE:g}x upsampled)")
```

Update the comment above it: replace `never request finer ground detail than the data holds` with `never request more than MAX_UPSAMPLE times finer ground than the data holds`.

In `app/regions.py`, add the import `from app.spec import MAX_UPSAMPLE` below `from app.geo import RegionGeo`, and add one key to the dict `meta()` returns, after `"native_resolution_m"`:

```python
                "max_upsample": MAX_UPSAMPLE,
```

In `app/static/canvas.js`, change the three floor tests. Leave line 76 (the refit floor) as it is.

```js
// Is the current crop below the zoom-cap floor for the selected print width? The
// server allows r.max_upsample x finer ground than the plate (invariant 6).
export function cropBelowFloor() {
  const c = cropOverviewPx(); const r = activeRegion(); const mpp = metresPerPx();
  if (!c || !r || !mpp) return false;
  const groundW = (c[2] - c[0]) * mpp;
  return groundW < (r.native_resolution_m / (r.max_upsample || 1)) * finalWidthPx();
}
```

In `sizeInfeasibleForRegion`, the return line becomes:

```js
  return (r.native_resolution_m / (r.max_upsample || 1)) * finalWidthPx() > maxCropW;
```

In `presetInfeasibleForRegion`, the return line becomes:

```js
  return (r.native_resolution_m / (r.max_upsample || 1)) * preset.px[0] > maxCropW;
```

In `CLAUDE.md`, invariant 6 becomes:

```markdown
6. **The zoom cap at the final dpi, at most 2× upsampled.** A 422 past 2× (`MAX_UPSAMPLE`, `app/spec.py`) is correct. Default framing still aims for 1×.
```

- [ ] **Step 4: Run the checks**

Run: `.venv/bin/python -m pytest tests/test_spec.py tests/test_regions.py tests/test_docs.py -q && node --check app/static/canvas.js`
Expected: all pass, no output from node.

Then the fast suite: `.venv/bin/python -m pytest -n auto -m "not slow" -q`. Expected: only the baseline failure, if it runs in the fast set.

- [ ] **Step 5: Drive the studio once.** Start the studio as `docs/changing-things.md` › Work on the studio front end says. On lassen_ca at 18×24, drag the frame to about 40 km wide (7.4 m/px). Expected: the frame stroke stays gold, not red. Drag it to about 25 km (4.6 m/px). Expected: red, and the label says "too tight to print sharp".

- [ ] **Step 6: Commit**

```bash
git add app/spec.py app/regions.py app/static/canvas.js CLAUDE.md tests/test_spec.py tests/test_regions.py
git commit -m "spec: the zoom cap allows 2x upsampling, so an order's terrain can meet its print size"
```

---

### Task 3: `region_prep.py` fetches one layer onto a different grid

**Goal:** `plan_build` and the CLI take a grid resolution and a separate, finer-or-equal source resolution, and write the region under any root.

**Files:**
- Modify: `region_prep.py` (`plan_build` ~line 71, new `warp_resampling` and `_resolution_arg`, `build_dem_cog` ~line 250, `write_sources_manifest` ~line 321, `main` ~line 373)
- Test: `tests/test_region_prep.py`

**Acceptance Criteria:**
- [ ] `plan_build(..., resolution_m=60, source_resolution_m=10)` sizes slices by the 10 m source grid.
- [ ] A source coarser than the grid raises `ValueError`.
- [ ] `warp_resampling` returns `Resampling.average` when the grid is coarser than the source, else `Resampling.bilinear`.
- [ ] `--resolution` takes `auto` or any positive number. `--source-resolution` and `--out-root` exist, with defaults that keep today's behaviour.
- [ ] `region.json` gains `source_resolution_m`. `sources.json` names the fetched layer and its `rebuild` line carries `--source-resolution` when it differs.
- [ ] Existing `tests/test_region_prep.py` tests still pass unchanged.

**Verify:** `.venv/bin/python -m pytest tests/test_region_prep.py -q` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing tests** at the end of `tests/test_region_prep.py`:

```python
import argparse


def test_source_defaults_to_the_grid():
    plan = rp.plan_build(LASSEN, "EPSG:32610", resolution_m=10)
    assert plan["source_resolution_m"] == 10
    assert plan["source_mpx"] == plan["grid_mpx"]


def test_finer_source_sizes_the_slices():
    # a 60 m grid fed from the 10 m layer fetches ~36x the cells; slices follow the source
    plan = rp.plan_build(CORRIDOR, "EPSG:32611", resolution_m=60, source_resolution_m=10)
    assert plan["resolution_m"] == 60 and plan["source_resolution_m"] == 10
    assert plan["source_mpx"] > 30 * plan["grid_mpx"]
    assert plan["source_mpx"] / plan["n_slices"] <= rp.SLICE_BUDGET_MPX


def test_source_coarser_than_grid_is_refused():
    with pytest.raises(ValueError):
        rp.plan_build(LASSEN, "EPSG:32610", resolution_m=10, source_resolution_m=30)


def test_warp_resampling_averages_when_the_grid_is_coarser():
    from rasterio.enums import Resampling
    assert rp.warp_resampling(25, 10) == Resampling.average
    assert rp.warp_resampling(10, 10) == Resampling.bilinear
    assert rp.warp_resampling(3, 3) == Resampling.bilinear


def test_resolution_arg():
    assert rp._resolution_arg("auto") is None
    assert rp._resolution_arg("2.5") == 2.5
    with pytest.raises(argparse.ArgumentTypeError):
        rp._resolution_arg("0")


def test_sources_manifest_names_the_fetched_layer(tmp_path):
    m = rp.write_sources_manifest(str(tmp_path), "order_x", (-116.3, 35.8, -116.2, 35.9),
                                  "EPSG:32611", built="2026-09-24",
                                  resolution_m=25.0, source_resolution_m=10)
    assert m["sources"][0]["dataset"] == "USGS 3DEP 10 m DEM"
    assert "--resolution 25.0 --source-resolution 10" in m["rebuild"]


def test_sources_manifest_unchanged_when_source_is_the_grid(tmp_path):
    m = rp.write_sources_manifest(str(tmp_path), "r", (-116.3, 35.8, -116.2, 35.9),
                                  "EPSG:32611", built="2026-09-24", resolution_m=10)
    assert m["sources"][0]["dataset"] == "USGS 3DEP 10 m DEM"
    assert "--source-resolution" not in m["rebuild"]
```

- [ ] **Step 2: Run and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_region_prep.py -q`
Expected: the seven new tests FAIL (`KeyError: 'source_resolution_m'`, `AttributeError: ... warp_resampling`, `TypeError` on the new keyword).

- [ ] **Step 3: Implement `plan_build`.** Change the signature and docstring, and compute the source grid:

```python
def plan_build(bbox_4326, dst_crs, resolution_m=None, source_resolution_m=None):
    """Everything main() needs to know before fetching: the DEM resolution (auto =
    finest of DEM_RES_CHOICES whose grid fits GRID_BUDGET_MPX; explicit overrides
    but is flagged when over budget), the slice count that keeps peak memory
    bounded, the landcover resolution, and honest size estimates.

    `source_resolution_m` is the 3DEP layer fetched; it defaults to the grid. An order
    plate fetches a finer layer and averages it onto a coarser grid, so the slices are
    sized by whichever of the two grids holds more cells."""
```

Keep the auto-selection block as it is. After `mpx = w * h / 1e6`, add:

```python
    source = resolution_m if source_resolution_m is None else source_resolution_m
    if source > resolution_m:
        raise ValueError(f"source layer {source} m is coarser than the "
                         f"{resolution_m} m grid; fetch a finer layer or coarsen the grid")
    if source == resolution_m:
        src_mpx = mpx
    else:
        sw, sh, _ = projected_grid(bbox_4326, dst_crs, source)
        src_mpx = sw * sh / 1e6
```

Replace the `n_slices` line and the return dict:

```python
    n_slices = max(1, int(np.ceil(max(mpx, src_mpx) / SLICE_BUDGET_MPX)))
    return {"resolution_m": resolution_m, "auto": auto,
            "source_resolution_m": source, "source_mpx": src_mpx,
            "grid": (w, h), "transform": transform, "grid_mpx": mpx,
            "over_budget": mpx > GRID_BUDGET_MPX,
            "n_slices": n_slices,
            "landcover_resolution_m": lc_res,
            "est_dem_mb": mpx * 4,           # float32; terrain barely deflates
            "est_peak_gb": max(mpx, src_mpx) / n_slices * 4 * 10 / 1024}
```

- [ ] **Step 4: Add `warp_resampling` and `_resolution_arg`** directly after `plan_build`:

```python
def warp_resampling(grid_m, source_m):
    """Average when the grid is coarser than the source: many source cells fall in
    one grid cell, and bilinear would sample a few of them and alias the ridgelines.
    Bilinear otherwise (equal cells, or the 2x upsample an order may need)."""
    return Resampling.average if grid_m > source_m * 1.01 else Resampling.bilinear


def _resolution_arg(value):
    """--resolution: 'auto' (None) or a positive number of metres."""
    if value == "auto":
        return None
    try:
        res = float(value)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from ex
    if not res > 0:
        raise argparse.ArgumentTypeError("resolution must be 'auto' or more than 0 m")
    return res
```

- [ ] **Step 5: Use the source in `build_dem_cog`.** Replace `da = fetch_dem(sb, res)` with:

```python
            da = fetch_dem(sb, plan["source_resolution_m"])
```

In the same loop, replace `resampling=Resampling.bilinear)` in the `reproject(...)` call with:

```python
                      resampling=warp_resampling(res, plan["source_resolution_m"]))
```

- [ ] **Step 6: Name the fetched layer in `write_sources_manifest`.** Change the signature, and compute the source before `manifest = {`:

```python
def write_sources_manifest(out_dir, region_id, bbox_4326, dst_crs, built=None,
                           resolution_m=10, source_resolution_m=None):
```

```python
    source = resolution_m if source_resolution_m is None else source_resolution_m
    rebuild = (f"python region_prep.py --id {region_id} --name <name> "
               f"--bbox {' '.join(str(v) for v in bbox_4326)} "
               f"--epsg {dst_crs.split(':')[1]} --resolution {resolution_m}")
    if source != resolution_m:
        rebuild += f" --source-resolution {source}"
```

In the dict, set `"rebuild": rebuild,` and change the first source entry to:

```python
            {"dataset": f"USGS 3DEP {source:g} m DEM", "via": "py3dep.get_dem",
             "license": "Public domain (USGS)"},
```

- [ ] **Step 7: Update `main`.** Replace the `--resolution` argument and add two more:

```python
    ap.add_argument("--resolution", default=None, type=_resolution_arg,
                    help="DEM grid in metres, or 'auto' (default): the finest of "
                         "10/30/60 that fits the grid budget, so a huge bbox can't "
                         "OOM the build")
    ap.add_argument("--source-resolution", type=float, default=None,
                    help="3DEP layer to fetch, in metres; defaults to the grid. Order "
                         "plates fetch a finer layer and average it onto the grid")
    ap.add_argument("--out-root", default="regions",
                    help="directory the region folder is written under")
```

Replace `out_dir = os.path.join("regions", args.id)` with `out_dir = os.path.join(args.out_root, args.id)`.

Replace the `plan = plan_build(...)` call with:

```python
    plan = plan_build(tuple(args.bbox), dst_crs, args.resolution, args.source_resolution)
```

In the `print(f"Build plan: ...")` call, after the resolution, add the source: change `f"{' (auto)' if plan['auto'] else ''} -> grid {gw}x{gh} "` to

```python
          f"{' (auto)' if plan['auto'] else ''}"
          f" from the {plan['source_resolution_m']:g} m layer -> grid {gw}x{gh} "
```

In the `region` dict, after `"native_resolution_m": plan["resolution_m"],` add:

```python
        "source_resolution_m": plan["source_resolution_m"],
```

Replace the `write_sources_manifest(...)` call with:

```python
    write_sources_manifest(out_dir, args.id, tuple(args.bbox), dst_crs,
                           resolution_m=plan["resolution_m"],
                           source_resolution_m=plan["source_resolution_m"])
```

Update the module docstring's second paragraph: after "pass an explicit --resolution only to override the planner.", add "An order plate passes --resolution, --source-resolution and --out-root together (app/orderprep.py)."

- [ ] **Step 8: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_region_prep.py tests/test_regionbuild.py -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add region_prep.py tests/test_region_prep.py
git commit -m "region_prep: fetch one 3DEP layer onto a separate grid, so an order plate is sized to its print"
```

---

### Task 4: 3DEP coverage per layer

**Goal:** A `.venv-prep` script reports, for a lon/lat bbox, the share of it each 3DEP layer covers, so planning never trusts a layer the dynamic service would silently fill.

**Files:**
- Modify: `region_prep.py` (new `COVERAGE_LAYERS_M`, `coverage_fraction`, `layer_coverage`, after `fetch_dem`)
- Create: `scripts/dem_coverage.py`
- Test: `tests/test_dem_coverage.py`

**Acceptance Criteria:**
- [ ] `coverage_fraction` returns 1.0, 0.5 and 0.0 for full, half and no overlap, and 0.0 for no footprints.
- [ ] `scripts/dem_coverage.py` with the wrong number of arguments exits with code 2 and a usage line.
- [ ] On Dom's Mac, the script on the Tecopa probe bbox prints a JSON object with keys `1 3 10 30 60`, `1` above 0.99 and `3` at 0.0.

**Verify:** `.venv/bin/python -m pytest tests/test_dem_coverage.py -q` → all pass. Then `.venv-prep/bin/python scripts/dem_coverage.py -116.27 35.88 -116.24 35.91` → `{"1": 1.0, "3": 0.0, "10": 1.0, "30": 1.0, "60": …}`.

**Steps:**

- [ ] **Step 1: Write the failing tests** in a new `tests/test_dem_coverage.py`:

```python
# tests/test_dem_coverage.py
# Coverage is what keeps an order honest: the 3DEP dynamic service fills gaps in a
# fine layer with resampled coarse data and says nothing. The pure fraction runs in
# CI; the network query is checked by hand on the Mac (plan Task 4).
import subprocess
import sys

import pytest
from shapely.geometry import box

rp = pytest.importorskip("region_prep")
BBOX = (0.0, 0.0, 2.0, 1.0)


def test_full_cover():
    assert rp.coverage_fraction([box(-1, -1, 3, 2)], BBOX) == pytest.approx(1.0)


def test_half_cover_from_two_overlapping_footprints():
    parts = [box(0, 0, 0.8, 1), box(0.5, 0, 1.0, 1)]      # union is x 0..1
    assert rp.coverage_fraction(parts, BBOX) == pytest.approx(0.5)


def test_no_cover():
    assert rp.coverage_fraction([box(5, 5, 6, 6)], BBOX) == 0.0
    assert rp.coverage_fraction([], BBOX) == 0.0


def test_cli_usage_error_exits_2():
    out = subprocess.run([sys.executable, "scripts/dem_coverage.py", "1", "2"],
                         capture_output=True, text=True)
    assert out.returncode == 2
    assert "usage" in out.stderr
```

- [ ] **Step 2: Run and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_dem_coverage.py -q`
Expected: FAIL, `AttributeError: module 'region_prep' has no attribute 'coverage_fraction'`, and the CLI test fails because the script does not exist.

- [ ] **Step 3: Add the helpers to `region_prep.py`**, directly after `fetch_dem`:

```python
# The 3DEP layers an order can draw from, in metres. 3 m (1/9 arc-second) is being
# retired and is missing in many places (Tecopa has none), so coverage is measured,
# never assumed.
COVERAGE_LAYERS_M = (1, 3, 10, 30, 60)


def coverage_fraction(footprints, bbox_4326):
    """Share of the bbox (EPSG:4326) inside the union of the 3DEP source footprints
    (shapely geometries, EPSG:4326). Measured in degrees: only the ratio matters, and
    on a plate-sized box the distortion is well under 1%."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    target = box(*bbox_4326)
    geoms = list(footprints)
    if not geoms:
        return 0.0
    return float(unary_union(geoms).intersection(target).area / target.area)


def layer_coverage(bbox_4326):
    """{layer metres: covered share} for every COVERAGE_LAYERS_M layer. Queries the
    3DEP source index over the network; a layer with no footprints is 0.0. Network
    errors raise: a failed query must never read as 'no data here'."""
    import py3dep
    names = {f"{r}m": r for r in COVERAGE_LAYERS_M}
    gdf = py3dep.query_3dep_sources(tuple(bbox_4326), res=list(names))
    out = {}
    for name, r in names.items():
        geoms = [] if gdf is None else list(gdf.loc[gdf["dem_res"] == name, "geometry"])
        out[r] = coverage_fraction(geoms, bbox_4326)
    return out
```

- [ ] **Step 4: Create `scripts/dem_coverage.py`**

```python
"""Print how much of a lon/lat bbox each 3DEP layer covers, as one line of JSON:

    {"1": 0.9981, "3": 0.0, "10": 1.0, "30": 1.0, "60": 1.0}

Runs in .venv-prep (py3dep). Order planning (app/orderprep.py) calls it as a
subprocess, so the fetch stack never enters .venv (invariant 13).

    .venv-prep/bin/python scripts/dem_coverage.py <west> <south> <east> <north>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main(argv):
    if len(argv) != 4:
        print("usage: dem_coverage.py <west> <south> <east> <north>", file=sys.stderr)
        return 2
    import region_prep   # sets SSL_CERT_FILE before anything imports aiohttp
    bbox = tuple(float(v) for v in argv)
    cov = region_prep.layer_coverage(bbox)
    print(json.dumps({str(k): round(v, 4) for k, v in cov.items()}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_dem_coverage.py tests/test_region_prep.py -q`
Expected: all pass.

- [ ] **Step 6: Check it on the network** (Dom's Mac)

Run: `.venv-prep/bin/python scripts/dem_coverage.py -116.27 35.88 -116.24 35.91`
Expected: `"1"` above 0.99, `"3"` 0.0, `"10"` 1.0. A traceback means the network query changed. Stop and report it.

- [ ] **Step 7: Commit**

```bash
git add region_prep.py scripts/dem_coverage.py tests/test_dem_coverage.py
git commit -m "region_prep: measure 3DEP coverage per layer, because the dynamic service fills gaps silently"
```

---

### Task 5: `run_build` and the labels bake work outside `regions/`

**Goal:** `regionbuild.run_build` passes a grid, a source layer, an output root and an environment through to `region_prep.py` and `scripts/build_labels.py`, without changing the in-app build.

**Files:**
- Modify: `app/regionbuild.py` (`run_build`)
- Modify: `scripts/build_labels.py` (`main`)
- Test: `tests/test_regionbuild.py`, `tests/test_build_labels.py`

**Acceptance Criteria:**
- [ ] With `resolution`, `source_resolution` and `out_root` in `params`, the prep command carries `--resolution`, `--source-resolution` and `--out-root`, and the labels command carries `--root`.
- [ ] Without them, both commands are exactly as today (the three existing stub tests pass unchanged).
- [ ] `env` reaches both subprocesses.
- [ ] `build_labels.py --root <dir> <id>` builds `<dir>/<id>`.

**Verify:** `.venv/bin/python -m pytest tests/test_regionbuild.py tests/test_build_labels.py -q` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing tests.** At the end of `tests/test_regionbuild.py`:

```python
STUB_ORDER_PREP = """
import argparse, json, os
ap = argparse.ArgumentParser()
for a in ("--id", "--name", "--epsg", "--resolution", "--source-resolution", "--out-root"):
    ap.add_argument(a, required=True)
ap.add_argument("--bbox", nargs=4, type=float, required=True)
a = ap.parse_args()
out = os.path.join(a.out_root, a.id)
os.makedirs(out, exist_ok=True)
json.dump({"resolution": a.resolution, "source": a.source_resolution},
          open(os.path.join(out, "region.json"), "w"))
print("cache=" + os.environ.get("HYRIVER_CACHE_NAME", ""))
"""

STUB_LABELS_ARGV = """
import json, os, sys
open(os.environ["LABELS_ARGV_OUT"], "w").write(json.dumps(sys.argv[1:]))
"""


def test_run_build_passes_order_arguments_and_env(tmp_path):
    prep = tmp_path / "order_prep.py"
    prep.write_text(STUB_ORDER_PREP)
    labels = tmp_path / "labels_argv.py"
    labels.write_text(STUB_LABELS_ARGV)
    root = tmp_path / "work" / "plate"
    params = dict(_params(), resolution=4.0, source_resolution=4.0, out_root=str(root))
    env = dict(os.environ, HYRIVER_CACHE_NAME="/tmp/cache.sqlite",
               LABELS_ARGV_OUT=str(tmp_path / "argv.json"))
    lines = []
    rb.run_build(params, repo_root=".", regions_root=str(root),
                 prep_python=sys.executable, prep_script=str(prep),
                 labels_script=str(labels), set_progress=lines.append, env=env)
    got = _json.load(open(root / "stub_region" / "region.json"))
    assert got == {"resolution": "4.0", "source": "4.0"}
    assert "cache=/tmp/cache.sqlite" in lines
    assert _json.load(open(tmp_path / "argv.json")) == ["--root", str(root), "stub_region"]
```

Add `import os` next to `import sys` in that section of the file.

In `tests/test_build_labels.py`, add at the end:

```python
def test_main_takes_a_root(monkeypatch):
    import sys
    from scripts import build_labels as bl
    seen = []
    monkeypatch.setattr(bl, "build_region", seen.append)
    monkeypatch.setattr(sys, "argv", ["build_labels.py", "--root", "/o/work/plate", "order_x"])
    bl.main()
    assert seen == [os.path.join("/o/work/plate", "order_x")]


def test_main_default_root_is_regions(monkeypatch):
    import sys
    from scripts import build_labels as bl
    seen = []
    monkeypatch.setattr(bl, "build_region", seen.append)
    monkeypatch.setattr(sys, "argv", ["build_labels.py", "lassen_ca"])
    bl.main()
    assert seen == [os.path.join("regions", "lassen_ca")]
```

- [ ] **Step 2: Run and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_regionbuild.py tests/test_build_labels.py -q`
Expected: `test_run_build_passes_order_arguments_and_env` FAILS with `TypeError: run_build() got an unexpected keyword argument 'env'`. `test_main_takes_a_root` FAILS because `--root` is treated as a region id.

- [ ] **Step 3: Implement `run_build`.** Change the signature:

```python
def run_build(params: dict, repo_root: str, regions_root: str,
              prep_python: str, prep_script: str, labels_script: str,
              set_progress, env: dict | None = None) -> dict:
```

Add to the docstring: "An order build adds `resolution`, `source_resolution` and `out_root` to params, and passes `env` (the shared HyRiver cache). Without them the commands are exactly the in-app build's."

After the `cmd = [...]` list, add:

```python
    if params.get("resolution") is not None:
        cmd += ["--resolution", str(params["resolution"])]
    if params.get("source_resolution") is not None:
        cmd += ["--source-resolution", str(params["source_resolution"])]
    if params.get("out_root"):
        cmd += ["--out-root", params["out_root"]]
```

Add `env=env` to the `subprocess.Popen(...)` call. Replace the labels `subprocess.run(...)` call with:

```python
    lab_cmd = [prep_python, labels_script]
    if params.get("out_root"):
        lab_cmd += ["--root", params["out_root"]]
    lab_cmd.append(rid)
    lab = subprocess.run(lab_cmd, cwd=repo_root, capture_output=True, text=True, env=env)
```

- [ ] **Step 4: Implement `build_labels.main`**

```python
def main():
    args = sys.argv[1:]
    root = "regions"
    if args[:1] == ["--root"]:
        if len(args) < 2:
            sys.exit("usage: build_labels.py [--root DIR] [id ...]")
        root, args = args[1], args[2:]
    ids = args or sorted(d for d in os.listdir(root)
                         if os.path.isdir(os.path.join(root, d)))
    for rid in ids:
        build_region(os.path.join(root, rid))
```

Add to the module docstring's usage lines:

```
    python scripts/build_labels.py --root <dir> <id>   # a plate outside regions/ (orders)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_regionbuild.py tests/test_build_labels.py tests/test_region_endpoints.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/regionbuild.py scripts/build_labels.py tests/test_regionbuild.py tests/test_build_labels.py
git commit -m "regionbuild: pass grid, source layer, root and env through, so an order builds its plate in its own folder"
```

---

### Task 6: Pure plate planning for an order

**Goal:** `app/orderplate.py` frames tracks nestled, sizes the plate, picks the projection, chooses the grid and layer from coverage, widens a frame the data cannot hold, and finds a curated plate that already fits.

**Files:**
- Create: `app/orderplate.py`
- Test: `tests/test_orderplate.py`

**Acceptance Criteria:**
- [ ] `nestled_frame` puts the tracks at exactly `NESTLE_FILL` on their fuller side, centred, at the print's aspect, and never under `MIN_FRAME_M` wide.
- [ ] `order_epsg` gives UTM for Tecopa and 5070 for a frame wider than 600 km.
- [ ] `choose_grid` covers: lidar under 10 m, no lidar (upsample within 2×), past 2× (`widen`), large frames (static source under a coarser grid), no coverage (`PlateError`), and `USE_DYNAMIC_FINE = False`.
- [ ] `widen_for_upsample` leaves the upsample just under 2×.
- [ ] `curated_fit` returns a plate only when the frame is inside it and its data is at least as fine as the print needs.
- [ ] `USE_DYNAMIC_FINE` matches the Task 1 result.

**Verify:** `.venv/bin/python -m pytest tests/test_orderplate.py -q` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing tests** in a new `tests/test_orderplate.py`:

```python
# tests/test_orderplate.py
# Plate planning for one order: the spec's sections 2 and 3 as pure functions.
import pytest

from app import orderplate as op

TECOPA = (-116.3, 35.8, -116.1, 36.0)
LIDAR = {1: 1.0, 3: 0.0, 10: 1.0, 30: 1.0, 60: 1.0}
NO_LIDAR = {1: 0.0, 3: 0.0, 10: 1.0, 30: 1.0, 60: 1.0}
PORTRAIT = 12 / 18


def test_conus_only():
    assert op.conus_covered(TECOPA)
    assert not op.conus_covered((-150.1, 61.1, -149.7, 61.3))     # Anchorage
    assert not op.conus_covered((-123.5, 48.8, -122.5, 49.8))     # over the border


def test_order_epsg_utm_then_albers():
    assert op.order_epsg(TECOPA) == 32611
    assert op.order_epsg((-120.0, 39.3, -111.9, 40.7)) == 5070     # Reno to Salt Lake, ~690 km


def test_nestled_frame_wide_tracks():
    f = op.nestled_frame((0.0, 0.0, 10000.0, 5000.0), PORTRAIT)
    assert (f[2] - f[0]) / (f[3] - f[1]) == pytest.approx(PORTRAIT)
    assert op.track_fill((0.0, 0.0, 10000.0, 5000.0), f) == pytest.approx(op.NESTLE_FILL)
    assert ((f[0] + f[2]) / 2, (f[1] + f[3]) / 2) == pytest.approx((5000.0, 2500.0))


def test_nestled_frame_tall_tracks():
    t = (0.0, 0.0, 4000.0, 30000.0)
    f = op.nestled_frame(t, PORTRAIT)
    assert (f[3] - f[1]) == pytest.approx(30000.0 / op.NESTLE_FILL)
    assert op.track_fill(t, f) == pytest.approx(op.NESTLE_FILL)


def test_nestled_frame_minimum():
    f = op.nestled_frame((0.0, 0.0, 100.0, 100.0), PORTRAIT)
    assert f[2] - f[0] == pytest.approx(op.MIN_FRAME_M)


def test_plate_bounds_and_needed_resolution():
    assert op.plate_bounds((0.0, 0.0, 10000.0, 15000.0)) == pytest.approx(
        (-1000.0, -1500.0, 11000.0, 16500.0))
    assert op.needed_resolution((0.0, 0.0, 18000.0, 27000.0), 12) == pytest.approx(5.0)


def test_lonlat_round_trip_contains_the_input():
    ll = op.to_lonlat_bbox(op.project_bbox(TECOPA, 32611), 32611)
    assert ll[0] <= TECOPA[0] and ll[1] <= TECOPA[1]
    assert ll[2] >= TECOPA[2] and ll[3] >= TECOPA[3]


def test_grid_under_10m_with_lidar():
    g = op.choose_grid(4.63, LIDAR)
    assert g == {"grid_m": 4.0, "source_m": 4.0, "layer_m": 1, "upsample": 1.0,
                 "widen": False}


def test_grid_without_lidar_upsamples_within_2x():
    g = op.choose_grid(6.0, NO_LIDAR)
    assert (g["grid_m"], g["source_m"], g["layer_m"]) == (10.0, 10.0, 10)
    assert g["upsample"] == pytest.approx(10 / 6)
    assert not g["widen"]


def test_grid_past_2x_asks_to_widen():
    g = op.choose_grid(4.0, NO_LIDAR)
    assert g["widen"] and g["layer_m"] == 10


def test_large_frame_uses_a_static_layer_under_a_coarser_grid():
    g = op.choose_grid(25.0, LIDAR)
    assert g["grid_m"] == 25.0
    assert (g["source_m"], g["layer_m"]) == (10, 10)
    g = op.choose_grid(163.0, NO_LIDAR)
    assert (g["grid_m"], g["source_m"]) == (160.0, 60)


def test_12m_need_uses_the_10m_layer_even_with_lidar():
    g = op.choose_grid(12.0, LIDAR)
    assert (g["grid_m"], g["source_m"]) == (10.0, 10)


def test_partial_coverage_does_not_count():
    g = op.choose_grid(4.0, {1: 0.9, 3: 0.0, 10: 1.0, 30: 1.0, 60: 1.0})
    assert g["layer_m"] == 10


def test_no_coverage_is_a_plate_error():
    with pytest.raises(op.PlateError):
        op.choose_grid(10.0, {1: 0.0, 3: 0.0, 10: 0.0, 30: 0.0, 60: 0.0})


def test_dynamic_fine_off_ignores_lidar(monkeypatch):
    monkeypatch.setattr(op, "USE_DYNAMIC_FINE", False)
    g = op.choose_grid(6.0, LIDAR)
    assert g["layer_m"] == 10 and g["grid_m"] == 10.0


def test_widen_for_upsample_lands_just_under_2x():
    f = op.widen_for_upsample((0.0, 0.0, 6000.0, 9000.0), 10, 12)
    need = op.needed_resolution(f, 12)
    assert 10 / need < op.MAX_UPSAMPLE
    assert 10 / need == pytest.approx(op.MAX_UPSAMPLE)
    assert (f[2] - f[0]) / (f[3] - f[1]) == pytest.approx(PORTRAIT)


def _curated(native=10, bounds=(400000.0, 3800000.0, 700000.0, 4200000.0)):
    return [{"id": "big", "crs": "EPSG:32611", "bounds": list(bounds),
             "native_resolution_m": native}]


def test_curated_fit_reuses_a_plate_that_holds_the_print():
    tracks = (-116.4, 35.7, -116.0, 36.1)          # ~36 x 44 km: needs ~16.7 m/px at 12x18
    fit = op.curated_fit(tracks, PORTRAIT, 12, _curated())
    assert fit["region"]["id"] == "big" and fit["epsg"] == 32611
    assert fit["need_m"] >= 10


def test_curated_fit_refuses_coarse_or_small_plates():
    tracks = (-116.4, 35.7, -116.0, 36.1)
    assert op.curated_fit(tracks, PORTRAIT, 12, _curated(native=30)) is None
    assert op.curated_fit(tracks, PORTRAIT, 12,
                          _curated(bounds=(570000.0, 3960000.0, 580000.0, 3970000.0))) is None
```

- [ ] **Step 2: Run and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_orderplate.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'app.orderplate'`.

- [ ] **Step 3: Create `app/orderplate.py`.** Set `USE_DYNAMIC_FINE` from the Task 1 result.

```python
# app/orderplate.py
"""Plate planning for one customer order (order pipeline spec, sections 2 and 3).

Frame the tracks "nestled", size the plate around the frame, and choose the DEM grid
and the 3DEP layer so the print is sharp without building terrain it cannot show.
Pure logic: pyproj and math only. The coverage query and the build itself run in
.venv-prep as subprocesses (app/orderprep.py)."""
from __future__ import annotations

import math

from pyproj import Transformer

from app.regionbuild import utm_epsg
from app.spec import MAX_UPSAMPLE

DPI = 300
NESTLE_FILL = 0.60        # tracks span this share of the frame, on the side they fill more
FILL_WARN = 0.40          # below this the tracks no longer read as nestled
PLATE_MARGIN = 0.10       # the plate is the frame grown by this share on every side
PLATE_PAD_M = 1000.0      # extra ground under region_prep's 500 m grid inset
MIN_FRAME_M = 2000.0      # a walk round the block still gets a 2 km frame
ALBERS_EPSG = 5070
ALBERS_ABOVE_M = 600_000.0
COVERAGE_MIN = 0.995      # a layer counts only if it covers this share of the plate
STATIC_LAYERS_M = (10, 30, 60)   # py3dep's fast static tiles
# Below 10 m the grid is fetched from the 3DEP dynamic service, which resamples the
# finest source it holds. Plan Task 1 measured whether that is real lidar detail.
USE_DYNAMIC_FINE = True
CONUS = (-125.5, 24.3, -66.8, 49.5)
_M_PER_DEG = 111320.0


class PlateError(ValueError):
    """An order's plate cannot be planned or built. The message is for Dom."""


def conus_covered(bbox) -> bool:
    w, s, e, n = bbox
    return w >= CONUS[0] and s >= CONUS[1] and e <= CONUS[2] and n <= CONUS[3]


def order_epsg(bbox) -> int:
    """The UTM zone of the tracks' centre; CONUS Albers when they span over 600 km."""
    w, s, e, n = bbox
    width_m = (e - w) * _M_PER_DEG * math.cos(math.radians((s + n) / 2.0))
    return ALBERS_EPSG if width_m > ALBERS_ABOVE_M else utm_epsg(bbox)


def _ring(bbox, n=41):
    """Points along all four edges: edges curve under projection, corners don't bound."""
    w, s, e, nn = bbox
    t = [i / (n - 1) for i in range(n)]
    xs = [w + f * (e - w) for f in t] * 2 + [w] * n + [e] * n
    ys = [s] * n + [nn] * n + [s + f * (nn - s) for f in t] * 2
    return xs, ys


def project_bbox(bbox_lonlat, epsg) -> tuple:
    fwd = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    xs, ys = fwd.transform(*_ring(bbox_lonlat))
    return (min(xs), min(ys), max(xs), max(ys))


def to_lonlat_bbox(bounds_m, epsg, pad_m=0.0) -> tuple:
    minx, miny, maxx, maxy = bounds_m
    padded = (minx - pad_m, miny - pad_m, maxx + pad_m, maxy + pad_m)
    inv = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    lons, lats = inv.transform(*_ring(padded))
    return (min(lons), min(lats), max(lons), max(lats))


def _centred(cx, cy, w, h) -> tuple:
    return (cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)


def nestled_frame(track_bounds_m, aspect, fill=NESTLE_FILL) -> tuple:
    """A frame centred on the tracks, `aspect` (width / height), in which the tracks
    span `fill` of the frame on the side they fill more."""
    minx, miny, maxx, maxy = track_bounds_m
    w = max((maxx - minx) / fill, (maxy - miny) / fill * aspect, MIN_FRAME_M)
    return _centred((minx + maxx) / 2.0, (miny + maxy) / 2.0, w, w / aspect)


def track_fill(track_bounds_m, frame) -> float:
    tw = track_bounds_m[2] - track_bounds_m[0]
    th = track_bounds_m[3] - track_bounds_m[1]
    return max(tw / (frame[2] - frame[0]), th / (frame[3] - frame[1]))


def widen_frame(frame, width_m) -> tuple:
    """The same centre and aspect, `width_m` wide. Never shrinks."""
    w0, h0 = frame[2] - frame[0], frame[3] - frame[1]
    if width_m <= w0:
        return tuple(frame)
    return _centred((frame[0] + frame[2]) / 2.0, (frame[1] + frame[3]) / 2.0,
                    width_m, width_m * h0 / w0)


def plate_bounds(frame, margin=PLATE_MARGIN) -> tuple:
    w, h = frame[2] - frame[0], frame[3] - frame[1]
    return (frame[0] - margin * w, frame[1] - margin * h,
            frame[2] + margin * w, frame[3] + margin * h)


def needed_resolution(frame, print_w_in, dpi=DPI) -> float:
    """Metres of ground per printed pixel: the finest detail the print can show."""
    return (frame[2] - frame[0]) / (print_w_in * dpi)


def _nice_floor(m) -> float:
    step = 5.0 if m < 100 else 10.0 if m < 500 else 50.0
    return step * math.floor(m / step)


def choose_grid(need_m, coverage) -> dict:
    """The plate's grid and the 3DEP layer behind it, for a print that needs `need_m`
    metres of ground per pixel. `coverage` maps layer metres to the covered share.

    grid_m is the plate's cell (its native_resolution_m). source_m is the cell size
    fetched. layer_m is the finest 3DEP layer the data comes from. upsample is
    grid_m / need_m, at least 1. widen is True when even the finest layer is past
    MAX_UPSAMPLE, so the caller must widen the frame."""
    covered = sorted(r for r, share in coverage.items()
                     if share >= COVERAGE_MIN
                     and (USE_DYNAMIC_FINE or r in STATIC_LAYERS_M))
    if not covered:
        raise PlateError("No 3DEP elevation layer fully covers this ground.")
    finest = covered[0]
    if finest <= need_m:
        if need_m >= STATIC_LAYERS_M[0]:
            grid = _nice_floor(need_m)
            source = max((r for r in covered if r in STATIC_LAYERS_M and r <= grid),
                         default=None)
            if source is None:
                raise PlateError("No static 3DEP layer covers this ground.")
            return {"grid_m": grid, "source_m": source, "layer_m": source,
                    "upsample": 1.0, "widen": False}
        grid = float(math.floor(need_m))
        return {"grid_m": grid, "source_m": grid, "layer_m": finest,
                "upsample": 1.0, "widen": False}
    upsample = finest / need_m
    return {"grid_m": float(finest), "source_m": float(finest), "layer_m": finest,
            "upsample": upsample, "widen": upsample > MAX_UPSAMPLE}


def widen_for_upsample(frame, layer_m, print_w_in, dpi=DPI) -> tuple:
    """Grow the frame until `layer_m` data is at most MAX_UPSAMPLE times too coarse.
    The 1e-6 headroom keeps validate()'s strict `<` from reading exactly 2x as too
    tight after float round-trips."""
    width = layer_m / MAX_UPSAMPLE * print_w_in * dpi * (1.0 + 1e-6)
    return widen_frame(frame, width)


def curated_fit(track_bbox_lonlat, aspect, print_w_in, regions):
    """The first curated plate that holds the nestled frame at the print's resolution
    with no upsampling. `regions` holds dicts with id, crs ("EPSG:n"), bounds (CRS
    metres) and native_resolution_m. Returns {"region", "frame", "need_m", "epsg"}
    or None."""
    for r in regions:
        epsg = int(str(r["crs"]).split(":")[1])
        frame = nestled_frame(project_bbox(track_bbox_lonlat, epsg), aspect)
        need = needed_resolution(frame, print_w_in)
        b = r["bounds"]
        inside = (frame[0] >= b[0] and frame[1] >= b[1]
                  and frame[2] <= b[2] and frame[3] <= b[3])
        if inside and r["native_resolution_m"] <= need:
            return {"region": r, "frame": frame, "need_m": need, "epsg": epsg}
    return None
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_orderplate.py -q`
Expected: all pass. If Task 1 failed and you set `USE_DYNAMIC_FINE = False`, `test_grid_under_10m_with_lidar` fails by design. Change that test to monkeypatch `USE_DYNAMIC_FINE` to `True`, and keep it.

- [ ] **Step 5: Commit**

```bash
git add app/orderplate.py tests/test_orderplate.py
git commit -m "orderplate: plan an order's plate from its tracks, so the frame is nestled and the terrain matches the print"
```

---

### Task 7: The order folder, `order.toml` and `state.json`

**Goal:** `app/order.py` loads an order folder, parses `order.toml`, lists the track files in `in/`, and merges `work/state.json` without ever erasing Dom's manual changes.

**Files:**
- Create: `app/order.py`
- Test: `tests/test_order.py`

**Acceptance Criteria:**
- [ ] `parse_size` returns short side first, and refuses a short side over 17 in, zero, or text that is not a size.
- [ ] `load` refuses a missing `order.toml`, a missing title, and an unknown orientation. Orientation defaults to portrait and size to 12x18.
- [ ] `Order.id` is `order_` plus the slugified folder name.
- [ ] `track_files` returns only `.gpx`, `.kml`, `.kmz` (any case), and skips dotfiles.
- [ ] `write_state` never changes `manual`. Only `set_manual` does. Writes are atomic.
- [ ] `inputs_hash` changes when a track file or the size changes.
- [ ] `orders_root` honours `TECOPA_ORDERS_DIR`.

**Verify:** `.venv/bin/python -m pytest tests/test_order.py -q` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing tests** in a new `tests/test_order.py`:

```python
# tests/test_order.py
import pytest

from app import order as od

TOML = 'title = "Smith home ground"\nsize = "12x18"\n'


def _order(tmp_path, toml=TOML, files=("trip.gpx",)):
    d = tmp_path / "2026-10-001-smith"
    (d / "in").mkdir(parents=True)
    for name in files:
        (d / "in" / name).write_bytes(b"<gpx/>")
    if toml is not None:
        (d / "order.toml").write_text(toml)
    return d


def test_parse_size_short_side_first():
    assert od.parse_size("18x12") == (12.0, 18.0)
    assert od.parse_size(" 8.5 × 11 ") == (8.5, 11.0)


def test_parse_size_refuses_wider_than_the_printer():
    with pytest.raises(od.OrderError, match="17"):
        od.parse_size("18x24")


@pytest.mark.parametrize("bad", ["big", "0x10", "12", ""])
def test_parse_size_refuses_bad_text(bad):
    with pytest.raises(od.OrderError):
        od.parse_size(bad)


def test_load_and_defaults(tmp_path):
    o = od.load(str(_order(tmp_path, toml='title = "Smith home ground"\n')))
    assert o.title == "Smith home ground"
    assert o.size == (12.0, 18.0) and o.orientation == "portrait"
    assert o.print_in() == (12.0, 18.0)
    assert o.id == "order_2026_10_001_smith"


def test_landscape_swaps_the_print(tmp_path):
    o = od.load(str(_order(tmp_path, toml=TOML + 'orientation = "landscape"\n')))
    assert o.print_in() == (18.0, 12.0)


@pytest.mark.parametrize("toml,match", [
    (None, "order.toml"),
    ('size = "12x18"\n', "title"),
    (TOML + 'orientation = "square"\n', "orientation"),
    ("title = \n", "parse"),
])
def test_load_refuses(tmp_path, toml, match):
    with pytest.raises(od.OrderError, match=match):
        od.load(str(_order(tmp_path, toml=toml)))


def test_track_files_skip_photos_and_dotfiles(tmp_path):
    files = ("b.GPX", "a.kml", "c.kmz", "IMG_1.HEIC", "._b.gpx", "notes.txt")
    o = od.load(str(_order(tmp_path, files=files)))
    assert [p.rsplit("/", 1)[1] for p in o.track_files()] == ["a.kml", "b.GPX", "c.kmz"]


def test_write_state_keeps_manual(tmp_path):
    o = od.load(str(_order(tmp_path)))
    od.set_manual(o, "frame", [1, 2, 3, 4])
    od.write_state(o, {"frame": [0, 0, 1, 1], "manual": {}})
    s = od.read_state(o)
    assert s["manual"] == {"frame": [1, 2, 3, 4]}
    assert s["frame"] == [0, 0, 1, 1]
    assert not (tmp_path / "2026-10-001-smith" / "work" / "state.json.tmp").exists()


def test_inputs_hash_follows_tracks_and_size(tmp_path):
    d = _order(tmp_path)
    h1 = od.load(str(d)).inputs_hash()
    (d / "in" / "trip.gpx").write_bytes(b"<gpx>changed</gpx>")
    h2 = od.load(str(d)).inputs_hash()
    (d / "order.toml").write_text('title = "Smith home ground"\nsize = "8x10"\n')
    h3 = od.load(str(d)).inputs_hash()
    assert len({h1, h2, h3}) == 3


def test_orders_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TECOPA_ORDERS_DIR", str(tmp_path))
    assert od.orders_root() == str(tmp_path)
    assert od.cache_path() == str(tmp_path / "_cache" / "aiohttp_cache.sqlite")
```

- [ ] **Step 2: Run and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_order.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'app.order'`.

- [ ] **Step 3: Create `app/order.py`**

```python
# app/order.py
"""One customer order on disk (order pipeline spec, section 1).

    ~/Tecopa Orders/<order>/in/         the customer's files; nothing writes here
                            order.toml  Dom's decisions: title, size, orientation
                            work/       plate/, state.json, report.txt
                            out/        print and customer files (later sub-projects)

Customer data stays outside the repo, which is public. TECOPA_ORDERS_DIR moves the
root. state.json holds what Prepare and the studio decide; its "manual" key holds
Dom's studio changes, and Prepare never erases them."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from dataclasses import dataclass

from app.regionbuild import slugify

ORDERS_ENV = "TECOPA_ORDERS_DIR"
TRACK_EXTS = (".gpx", ".kml", ".kmz")
MAX_WIDTH_IN = 17.0            # the PRO-1100 feeds at most 17 in wide
ORIENTATIONS = ("portrait", "landscape")
_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*$")


class OrderError(ValueError):
    """The order folder or its order.toml is not usable. The message is for Dom."""


def orders_root() -> str:
    return os.environ.get(ORDERS_ENV) or os.path.join(os.path.expanduser("~"),
                                                      "Tecopa Orders")


def cache_path() -> str:
    """The HyRiver request cache every order's plate build shares."""
    return os.path.join(orders_root(), "_cache", "aiohttp_cache.sqlite")


def parse_size(text) -> tuple:
    """'12x18' -> (12.0, 18.0), short side first."""
    m = _SIZE.match(str(text))
    if not m:
        raise OrderError(f"size {text!r} is not like 12x18")
    short, long_ = sorted((float(m.group(1)), float(m.group(2))))
    if short <= 0:
        raise OrderError(f"size {text!r} must be larger than zero")
    if short > MAX_WIDTH_IN:
        raise OrderError(f"size {text!r} is wider than the PRO-1100's "
                         f"{MAX_WIDTH_IN:g} in")
    return (short, long_)


@dataclass(frozen=True)
class Order:
    dir: str
    title: str
    subtitle: str
    size: tuple
    orientation: str
    notes: str

    @property
    def id(self) -> str:
        return "order_" + slugify(os.path.basename(os.path.normpath(self.dir)))

    @property
    def in_dir(self) -> str:
        return os.path.join(self.dir, "in")

    @property
    def work_dir(self) -> str:
        return os.path.join(self.dir, "work")

    @property
    def plate_root(self) -> str:
        return os.path.join(self.work_dir, "plate")

    @property
    def state_path(self) -> str:
        return os.path.join(self.work_dir, "state.json")

    def print_in(self) -> tuple:
        """(width, height) in inches as printed."""
        short, long_ = self.size
        return (short, long_) if self.orientation == "portrait" else (long_, short)

    def track_files(self) -> list:
        if not os.path.isdir(self.in_dir):
            return []
        return sorted(os.path.join(self.in_dir, f) for f in os.listdir(self.in_dir)
                      if not f.startswith(".") and f.lower().endswith(TRACK_EXTS))

    def payloads(self) -> list:
        """(bytes, filename) pairs, the shape app.ingest reads."""
        out = []
        for path in self.track_files():
            with open(path, "rb") as f:
                out.append((f.read(), os.path.basename(path)))
        return out

    def inputs_hash(self) -> str:
        """Changes when a track file, the size or the orientation changes."""
        h = hashlib.sha256()
        for data, name in self.payloads():
            h.update(name.encode())
            h.update(hashlib.sha256(data).digest())
        h.update(repr((self.size, self.orientation)).encode())
        return h.hexdigest()


def load(folder) -> Order:
    folder = os.path.abspath(os.path.expanduser(str(folder)))
    toml_path = os.path.join(folder, "order.toml")
    if not os.path.isfile(toml_path):
        raise OrderError(f"no order.toml in {folder}")
    try:
        with open(toml_path, "rb") as f:
            cfg = tomllib.load(f)
    except tomllib.TOMLDecodeError as ex:
        raise OrderError(f"order.toml does not parse: {ex}") from ex
    title = str(cfg.get("title", "")).strip()
    if not title:
        raise OrderError("order.toml needs a title")
    orientation = str(cfg.get("orientation", "portrait")).lower()
    if orientation not in ORIENTATIONS:
        raise OrderError(f"orientation must be portrait or landscape, not {orientation!r}")
    return Order(dir=folder, title=title,
                 subtitle=str(cfg.get("subtitle", "")).strip(),
                 size=parse_size(cfg.get("size", "12x18")),
                 orientation=orientation, notes=str(cfg.get("notes", "")))


def read_state(order: Order) -> dict:
    try:
        with open(order.state_path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def write_state(order: Order, updates: dict) -> dict:
    """Merge `updates` into state.json. The "manual" key is skipped: only set_manual
    writes it, so Prepare can never erase a studio change."""
    state = read_state(order)
    for key, value in updates.items():
        if key != "manual":
            state[key] = value
    _dump(order, state)
    return state


def set_manual(order: Order, key: str, value) -> dict:
    state = read_state(order)
    state.setdefault("manual", {})[key] = value
    _dump(order, state)
    return state


def _dump(order: Order, state: dict) -> None:
    os.makedirs(order.work_dir, exist_ok=True)
    tmp = order.state_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, order.state_path)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_order.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/order.py tests/test_order.py
git commit -m "order: read an order folder and keep its state, so Prepare can run again without losing Dom's changes"
```

---

### Task 8: Prepare and the `order.py` command

**Goal:** `scripts/order.py prepare <folder>` reuses a curated plate or builds one under `work/plate/`, writes `work/state.json` and `work/report.txt`, and does nothing when the inputs have not changed.

**Files:**
- Create: `app/orderprep.py`
- Create: `scripts/order.py`
- Test: `tests/test_orderprep.py`

**Acceptance Criteria:**
- [ ] With lidar coverage, a 3.6 × 4.4 km track set builds a 1 m plate under `work/plate/order_<slug>/`, through the stubbed prep script.
- [ ] Without lidar, the frame widens to 18 km, the upsample is at most 2×, and the warnings name the widening and "a smaller print".
- [ ] The build subprocess gets `HYRIVER_CACHE_NAME` pointing at `<orders root>/_cache/aiohttp_cache.sqlite`.
- [ ] A second Prepare with the same inputs builds nothing and logs "Plate is current".
- [ ] A changed size, or a new manual frame, triggers exactly one rebuild, and the manual frame is kept.
- [ ] Tracks inside a curated plate that holds the print reuse it and build nothing.
- [ ] Tracks outside the lower 48 raise `PlateError`. A failing coverage script raises `PlateError` naming coverage.
- [ ] Nothing under `in/` changes.
- [ ] A failed build raises, removes the partial plate, and leaves every output line in `work/build.log`.
- [ ] `report.txt` names the plate, the grid, the fill and the warnings.
- [ ] `scripts/order.py prepare <missing folder>` returns 1 with the reason on stderr.

**Verify:** `.venv/bin/python -m pytest tests/test_orderprep.py -q` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing tests** in a new `tests/test_orderprep.py`:

```python
# tests/test_orderprep.py
# Prepare end to end with stub subprocesses (no network): the same trick as the
# stub region_prep in tests/test_regionbuild.py.
import json
import os
import sys

import pytest

from app import order as od
from app import orderplate as opl
from app import orderprep as op

LIDAR = {"1": 1.0, "3": 0.0, "10": 1.0, "30": 1.0, "60": 1.0}
NO_LIDAR = {"1": 0.0, "3": 0.0, "10": 1.0, "30": 1.0, "60": 1.0}
SMALL = (-116.21, 35.89, -116.17, 35.93)       # ~3.6 x 4.4 km near Tecopa
WIDE = (-116.4, 35.7, -116.0, 36.1)            # ~36 x 44 km

STUB_PREP = """
import argparse, json, os
ap = argparse.ArgumentParser()
for a in ("--id", "--name", "--epsg", "--resolution", "--source-resolution", "--out-root"):
    ap.add_argument(a, required=True)
ap.add_argument("--bbox", nargs=4, type=float, required=True)
a = ap.parse_args()
out = os.path.join(a.out_root, a.id)
os.makedirs(out, exist_ok=True)
json.dump({"id": a.id, "crs": "EPSG:" + a.epsg, "bbox": a.bbox,
           "native_resolution_m": float(a.resolution),
           "source_resolution_m": float(a.source_resolution)},
          open(os.path.join(out, "region.json"), "w"))
with open(os.path.join(a.out_root, "builds.log"), "a") as f:
    f.write(a.id + "\\n")
print("cache=" + os.environ.get("HYRIVER_CACHE_NAME", ""))
"""
STUB_COVERAGE = 'import os\nprint(os.environ["STUB_COVERAGE"])\n'
STUB_LABELS = "import sys\nsys.exit(0)\n"


def _gpx(w, s, e, n):
    pts = "".join(f'<trkpt lat="{lat}" lon="{lon}"/>' for lon, lat in ((w, s), (e, n)))
    return ('<?xml version="1.0"?><gpx version="1.1" creator="t" '
            'xmlns="http://www.topografix.com/GPX/1/1"><trk><name>t</name>'
            f"<trkseg>{pts}</trkseg></trk></gpx>")


@pytest.fixture
def tools(tmp_path, monkeypatch):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in (("prep.py", STUB_PREP), ("coverage.py", STUB_COVERAGE),
                       ("labels.py", STUB_LABELS)):
        (stubs / name).write_text(body)
    (tmp_path / "curated").mkdir()
    monkeypatch.setenv("TECOPA_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.setenv("STUB_COVERAGE", json.dumps(LIDAR))
    return op.Tools(prep_python=sys.executable, prep_script=str(stubs / "prep.py"),
                    labels_script=str(stubs / "labels.py"),
                    coverage_script=str(stubs / "coverage.py"),
                    repo_root=str(tmp_path), curated_root=str(tmp_path / "curated"))


def _make_order(tmp_path, bbox=SMALL, size="12x18"):
    d = tmp_path / "orders" / "2026-10-001-smith"
    (d / "in").mkdir(parents=True, exist_ok=True)
    (d / "in" / "trip.gpx").write_text(_gpx(*bbox))
    (d / "order.toml").write_text(f'title = "Smith home ground"\nsize = "{size}"\n')
    return d


def _builds(d):
    log = d / "work" / "plate" / "builds.log"
    return log.read_text().split() if log.exists() else []


def _snapshot(folder):
    return {p.name: p.read_bytes() for p in folder.iterdir()}


def test_builds_a_lidar_plate(tmp_path, tools):
    d = _make_order(tmp_path)
    before = _snapshot(d / "in")
    lines = []
    state = op.prepare(str(d), tools, log=lines.append)
    plate = state["plate"]
    assert plate["kind"] == "built" and plate["id"] == "order_2026_10_001_smith"
    assert (plate["grid_m"], plate["layer_m"]) == (1.0, 1)
    region = json.load(open(d / "work" / "plate" / plate["id"] / "region.json"))
    assert region["native_resolution_m"] == 1.0
    assert f"cache={od.cache_path()}" in lines
    assert state["fill"] == pytest.approx(opl.NESTLE_FILL, abs=0.01)
    assert _snapshot(d / "in") == before
    report = (d / "work" / "report.txt").read_text()
    assert "Plate: order_2026_10_001_smith (built), 1 m grid" in report


def test_no_lidar_widens_the_frame(tmp_path, tools, monkeypatch):
    monkeypatch.setenv("STUB_COVERAGE", json.dumps(NO_LIDAR))
    d = _make_order(tmp_path)
    state = op.prepare(str(d), tools, log=lambda s: None)
    frame = state["frame"]
    assert frame[2] - frame[0] == pytest.approx(18000.0, rel=1e-3)
    assert state["plate"]["grid_m"] == 10.0
    assert state["plate"]["upsample"] <= opl.MAX_UPSAMPLE
    assert any("widened" in w for w in state["warnings"])
    assert any("smaller print" in w for w in state["warnings"])


def test_second_prepare_builds_nothing(tmp_path, tools):
    d = _make_order(tmp_path)
    op.prepare(str(d), tools, log=lambda s: None)
    lines = []
    op.prepare(str(d), tools, log=lines.append)
    assert len(_builds(d)) == 1
    assert any("Plate is current" in l for l in lines)


def test_changed_size_rebuilds_once(tmp_path, tools):
    d = _make_order(tmp_path)
    op.prepare(str(d), tools, log=lambda s: None)
    _make_order(tmp_path, size="8x10")
    op.prepare(str(d), tools, log=lambda s: None)
    op.prepare(str(d), tools, log=lambda s: None)
    assert len(_builds(d)) == 2


def test_manual_frame_is_kept(tmp_path, tools):
    d = _make_order(tmp_path)
    first = op.prepare(str(d), tools, log=lambda s: None)
    f = first["frame"]
    manual = [f[0] - 2000.0, f[1] - 3000.0, f[2] + 2000.0, f[3] + 3000.0]
    od.set_manual(od.load(str(d)), "frame", manual)
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert state["frame"] == pytest.approx(manual)
    assert state["manual"]["frame"] == manual
    op.prepare(str(d), tools, log=lambda s: None)
    assert len(_builds(d)) == 2


def test_reuses_a_curated_plate(tmp_path, tools):
    big = tmp_path / "curated" / "big"
    big.mkdir()
    json.dump({"crs": "EPSG:32611", "bounds": [400000.0, 3800000.0, 700000.0, 4200000.0],
               "native_resolution_m": 10}, open(big / "region.json", "w"))
    (big / "dem.tif").write_bytes(b"")
    d = _make_order(tmp_path, bbox=WIDE)
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert state["plate"]["kind"] == "curated" and state["plate"]["id"] == "big"
    assert _builds(d) == []


def test_curated_plate_without_a_dem_is_not_reused(tmp_path, tools):
    big = tmp_path / "curated" / "big"
    big.mkdir()
    json.dump({"crs": "EPSG:32611", "bounds": [400000.0, 3800000.0, 700000.0, 4200000.0],
               "native_resolution_m": 10}, open(big / "region.json", "w"))
    d = _make_order(tmp_path, bbox=WIDE)
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert state["plate"]["kind"] == "built"


def test_outside_the_lower_48(tmp_path, tools):
    d = _make_order(tmp_path, bbox=(-150.1, 61.1, -149.9, 61.2))
    with pytest.raises(opl.PlateError, match="lower 48"):
        op.prepare(str(d), tools, log=lambda s: None)


def test_coverage_failure_is_a_plate_error(tmp_path, tools):
    bad = tmp_path / "stubs" / "bad_coverage.py"
    bad.write_text('import sys\nsys.exit("boom")\n')
    tools = op.Tools(**{**tools.__dict__, "coverage_script": str(bad)})
    d = _make_order(tmp_path)
    with pytest.raises(opl.PlateError, match="coverage"):
        op.prepare(str(d), tools, log=lambda s: None)


def test_failed_build_keeps_the_log(tmp_path, tools):
    bad = tmp_path / "stubs" / "bad_prep.py"
    bad.write_text('import sys\nprint("Fetching 3DEP DEM...")\nsys.exit(3)\n')
    tools = op.Tools(**{**tools.__dict__, "prep_script": str(bad)})
    d = _make_order(tmp_path)
    with pytest.raises(RuntimeError, match="exit 3"):
        op.prepare(str(d), tools, log=lambda s: None)
    assert "Fetching 3DEP DEM" in (d / "work" / "build.log").read_text()
    assert not (d / "work" / "plate" / "order_2026_10_001_smith").exists()


def test_cli_reports_a_missing_order(tmp_path, capsys):
    from scripts import order as order_cli
    assert order_cli.main(["prepare", str(tmp_path / "nope")]) == 1
    assert "no order.toml" in capsys.readouterr().err
```

- [ ] **Step 2: Run and confirm they fail**

Run: `.venv/bin/python -m pytest tests/test_orderprep.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'app.orderprep'`.

- [ ] **Step 3: Create `app/orderprep.py`**

```python
# app/orderprep.py
"""Prepare, step 1 of an order (order pipeline spec, section 2). Sub-project 1 ships
the plate: read the tracks, frame them nestled, reuse a curated plate that already
holds the print, or build one under work/plate/. Writes work/state.json and
work/report.txt. Later sub-projects add the paper table, photos and the proof.

The fetch stack runs only as .venv-prep subprocesses (invariant 13): the coverage
query (scripts/dem_coverage.py) and the build (region_prep.py and
scripts/build_labels.py, through regionbuild.run_build). Tests swap in stubs."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass

from app.ingest import lonlat_extent
from app.order import OrderError, cache_path, load, read_state, write_state
from app.orderplate import (FILL_WARN, MAX_UPSAMPLE, PLATE_PAD_M, PlateError,
                            choose_grid, conus_covered, curated_fit, needed_resolution,
                            nestled_frame, order_epsg, plate_bounds, project_bbox,
                            to_lonlat_bbox, track_fill, widen_for_upsample)
from app.regionbuild import run_build


@dataclass(frozen=True)
class Tools:
    """The subprocesses Prepare calls, and where the curated plates live."""
    prep_python: str
    prep_script: str
    labels_script: str
    coverage_script: str
    repo_root: str
    curated_root: str


def default_tools(repo_root: str) -> Tools:
    return Tools(prep_python=os.path.join(repo_root, ".venv-prep", "bin", "python"),
                 prep_script=os.path.join(repo_root, "region_prep.py"),
                 labels_script=os.path.join(repo_root, "scripts", "build_labels.py"),
                 coverage_script=os.path.join(repo_root, "scripts", "dem_coverage.py"),
                 repo_root=repo_root,
                 curated_root=os.path.join(repo_root, "regions"))


def curated_regions(root: str) -> list:
    """Curated plates with a DEM on disk, as the dicts curated_fit reads."""
    out = []
    if not os.path.isdir(root):
        return out
    for rid in sorted(os.listdir(root)):
        path = os.path.join(root, rid, "region.json")
        if not os.path.isfile(path):
            continue
        with open(path) as f:
            cfg = json.load(f)
        if not os.path.exists(os.path.join(root, rid, cfg.get("dem_path", "dem.tif"))):
            continue
        out.append({"id": rid, "crs": cfg["crs"], "bounds": cfg["bounds"],
                    "native_resolution_m": cfg["native_resolution_m"]})
    return out


def read_coverage(tools: Tools, bbox, env) -> dict:
    run = subprocess.run([tools.prep_python, tools.coverage_script, *map(str, bbox)],
                         cwd=tools.repo_root, capture_output=True, text=True, env=env)
    if run.returncode != 0:
        raise PlateError("The 3DEP coverage check failed:\n" + run.stderr[-800:])
    try:
        raw = json.loads(run.stdout.strip().splitlines()[-1])
        return {int(k): float(v) for k, v in raw.items()}
    except (ValueError, IndexError) as ex:
        raise PlateError(f"The 3DEP coverage check printed no result: {ex}") from ex


def _plate_present(plate) -> bool:
    return bool(plate) and os.path.isfile(
        os.path.join(plate["root"], plate["id"], "region.json"))


def _plan_grid(tools, frame, epsg, print_w_in, env):
    """The grid for the frame, widening the frame once if the data is too coarse.
    Coverage is read again for the widened plate, which covers more ground."""
    for _ in range(2):
        cov = read_coverage(tools, to_lonlat_bbox(plate_bounds(frame), epsg), env)
        grid = choose_grid(needed_resolution(frame, print_w_in), cov)
        if not grid["widen"]:
            return frame, grid
        frame = widen_for_upsample(frame, grid["layer_m"], print_w_in)
    raise PlateError("The terrain data is still too coarse for this print size "
                     "after the frame was widened.")


def prepare(order_dir: str, tools: Tools, log=print) -> dict:
    order = load(order_dir)
    tracks = lonlat_extent(order.payloads())["bbox"]
    if tracks is None:
        raise OrderError(f"no track points in {order.in_dir}")
    if not conus_covered(tracks):
        raise PlateError("These tracks are outside the lower 48. "
                         "Alaska and Hawaii come later.")
    state = read_state(order)
    manual = state.get("manual", {})
    inputs = order.inputs_hash()
    frame_current = ("frame" not in manual
                     or list(manual["frame"]) == list(state.get("frame", [])))
    if (state.get("inputs_hash") == inputs and frame_current
            and _plate_present(state.get("plate"))):
        log(f"Plate is current: {state['plate']['id']}. Nothing to build.")
        return state

    pw, ph = order.print_in()
    warnings = []
    fit = None if "frame" in manual else curated_fit(
        tracks, pw / ph, pw, curated_regions(tools.curated_root))
    if fit:
        epsg, frame = fit["epsg"], fit["frame"]
        region = fit["region"]
        plate = {"id": region["id"], "root": tools.curated_root, "kind": "curated",
                 "grid_m": float(region["native_resolution_m"]), "upsample": 1.0}
        log(f"Reusing curated plate {region['id']}.")
    else:
        if "frame" in manual:
            epsg = state.get("epsg") or order_epsg(tracks)
            planned = tuple(manual["frame"])
        else:
            epsg = order_epsg(tracks)
            planned = nestled_frame(project_bbox(tracks, epsg), pw / ph)
        env = dict(os.environ, HYRIVER_CACHE_NAME=cache_path())
        os.makedirs(os.path.dirname(cache_path()), exist_ok=True)
        frame, grid = _plan_grid(tools, planned, epsg, pw, env)
        if frame != planned:
            fill = track_fill(project_bbox(tracks, epsg), frame)
            note = (f"The terrain here is {grid['layer_m']:g} m data, too coarse for a "
                    f"nestled {pw:g}x{ph:g}. The frame was widened, and the tracks now "
                    f"fill {fill:.0%} of it.")
            if fill < FILL_WARN:
                note += " A smaller print would keep them nestled."
            warnings.append(note)
        if grid["upsample"] > 1.0:
            warnings.append(f"Terrain is upsampled {grid['upsample']:.2f}x "
                            f"(the limit is {MAX_UPSAMPLE:g}x).")
        plate, labels_note = _build(order, tools, frame, epsg, grid, env, log)
        if labels_note:
            warnings.append(labels_note)

    track_m = project_bbox(tracks, epsg)
    state = write_state(order, {
        "inputs_hash": inputs, "epsg": epsg, "print_in": [pw, ph],
        "frame": list(frame), "track_bounds_m": list(track_m),
        "fill": round(track_fill(track_m, frame), 3),
        "need_m": round(needed_resolution(frame, pw), 3),
        "plate": plate, "warnings": warnings})
    write_report(order, state)
    return state


def _build(order, tools, frame, epsg, grid, env, log):
    rid = order.id
    params = {"id": rid, "name": order.title,
              "bbox": to_lonlat_bbox(plate_bounds(frame), epsg, pad_m=PLATE_PAD_M),
              "epsg": epsg, "resolution": grid["grid_m"],
              "source_resolution": grid["source_m"], "out_root": order.plate_root}
    os.makedirs(order.plate_root, exist_ok=True)
    shutil.rmtree(os.path.join(order.plate_root, rid), ignore_errors=True)
    log(f"Building plate {rid}: {grid['grid_m']:g} m grid from the "
        f"{grid['layer_m']:g} m 3DEP layer.")
    started = time.monotonic()
    # work/build.log keeps every line of the build, so a failure can be read after
    # run_build sweeps the partial plate.
    with open(os.path.join(order.work_dir, "build.log"), "w") as build_log:
        def progress(line):
            build_log.write(line + "\n")
            log(line)
        result = run_build(params, repo_root=tools.repo_root,
                           regions_root=order.plate_root,
                           prep_python=tools.prep_python, prep_script=tools.prep_script,
                           labels_script=tools.labels_script, set_progress=progress,
                           env=env)
    plate = {"id": rid, "root": order.plate_root, "kind": "built",
             "grid_m": grid["grid_m"], "source_m": grid["source_m"],
             "layer_m": grid["layer_m"], "upsample": round(grid["upsample"], 3),
             "build_seconds": round(time.monotonic() - started, 1)}
    return plate, result["labels_note"]


def write_report(order, state) -> str:
    plate, frame = state["plate"], state["frame"]
    grid = f"{plate['grid_m']:g} m grid"
    if plate.get("layer_m") is not None:
        grid += f" from the {plate['layer_m']:g} m 3DEP layer"
    lines = [f"Order: {order.title}",
             f"Print: {state['print_in'][0]:g} x {state['print_in'][1]:g} in",
             f"Plate: {plate['id']} ({plate['kind']}), {grid}",
             f"Frame: {(frame[2] - frame[0]) / 1000:.1f} x "
             f"{(frame[3] - frame[1]) / 1000:.1f} km, tracks fill {state['fill']:.0%}",
             f"Upsampling: {plate['upsample']:.2f}x (limit {MAX_UPSAMPLE:g}x)"]
    if plate.get("build_seconds") is not None:
        lines.append(f"Build time: {plate['build_seconds']:.0f} s")
    if state["warnings"]:
        lines.append("Warnings:")
        lines += [f"- {w}" for w in state["warnings"]]
    else:
        lines.append("Warnings: none")
    text = "\n".join(lines) + "\n"
    with open(os.path.join(order.work_dir, "report.txt"), "w") as f:
        f.write(text)
    return text
```

`MAX_UPSAMPLE` is imported from `app.orderplate`, which re-exports it from `app.spec`. That keeps one source of truth.

- [ ] **Step 4: Create `scripts/order.py`**

```python
"""Run one customer order. Sub-project 1 ships `prepare`: the plate, the frame,
work/state.json and work/report.txt. See docs/changing-things.md > Run an order.

    .venv/bin/python scripts/order.py prepare "~/Tecopa Orders/2026-10-001-smith"
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.order import OrderError  # noqa: E402
from app.orderplate import PlateError  # noqa: E402
from app.orderprep import default_tools, prepare  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="order.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="build or reuse the order's plate and frame the tracks")
    p.add_argument("folder", help="the order folder, holding in/ and order.toml")
    args = ap.parse_args(argv)
    folder = os.path.abspath(os.path.expanduser(args.folder))
    try:
        prepare(folder, default_tools(ROOT))
    except (OrderError, PlateError, RuntimeError) as ex:
        print(f"prepare stopped: {ex}", file=sys.stderr)
        return 1
    with open(os.path.join(folder, "work", "report.txt")) as f:
        print(f.read(), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_orderprep.py tests/test_order.py tests/test_orderplate.py -q`
Expected: all pass.

Then the fast suite: `.venv/bin/python -m pytest -n auto -m "not slow" -q`. Expected: only the baseline failure, if it runs in the fast set.

- [ ] **Step 6: Commit**

```bash
git add app/orderprep.py scripts/order.py tests/test_orderprep.py
git commit -m "order: prepare builds or reuses the plate for an order folder, so a customer's tracks become a plate in one command"
```

---

### Task 9: Three real orders on the Mac

**Goal:** Run Prepare against three real track sets on Dom's Mac, with the network, and record the build times and plate sizes.

**Files:**
- Create: `~/Tecopa Orders/_acceptance/` order folders (outside the repo, not committed)

**Acceptance Criteria:**
- [ ] Three orders prepare without error: a compact home ground, a long north–south trip, and an east–west road trip over 600 km.
- [ ] For each plate: `Region(<id>, <plate root>).readiness()["ready"]` is `True`, and `native_resolution_m` equals the report's grid.
- [ ] The road trip's `state.json` has `epsg` 5070.
- [ ] Each build time and each `dem.tif` size is written down for Task 10.
- [ ] Dom has seen the three `overview.png` files.

**Verify:** the readiness one-liner in Step 3 prints `True` three times.

**Steps:**

- [ ] **Step 1: Make the three orders.** Run from the repo root:

```bash
A="$HOME/Tecopa Orders/_acceptance"
KIT="$HOME/Documents/Claude/Artifacts/tecopa-sample-kit/00-source-gpx"
mkdir -p "$A/home-compact/in" "$A/north-south/in" "$A/east-west/in"
cp "$(ls -S "$KIT"/*.gpx | tail -1)" "$A/home-compact/in/"
printf 'title = "Home compact"\nsize = "12x18"\n' > "$A/home-compact/order.toml"
printf 'title = "North south"\nsize = "12x18"\n' > "$A/north-south/order.toml"
printf 'title = "East west"\nsize = "12x18"\norientation = "landscape"\n' > "$A/east-west/order.toml"
```

For the two long trips, use a real GPX from Dom if one exists. If not, write straight-line tracks. They test the plate, not the art:

```bash
.venv/bin/python - <<'EOF'
import os
A = os.path.expanduser("~/Tecopa Orders/_acceptance")
def gpx(pts):
    seg = "".join(f'<trkpt lat="{la}" lon="{lo}"/>' for lo, la in pts)
    return ('<?xml version="1.0"?><gpx version="1.1" creator="acceptance" '
            'xmlns="http://www.topografix.com/GPX/1/1"><trk><name>t</name>'
            f"<trkseg>{seg}</trkseg></trk></gpx>")
open(f"{A}/north-south/in/trip.gpx", "w").write(
    gpx([(-118.29, 36.58), (-118.60, 37.10), (-119.05, 37.65)]))   # Whitney to Mono
open(f"{A}/east-west/in/trip.gpx", "w").write(
    gpx([(-119.81, 39.53), (-116.40, 40.20), (-111.89, 40.76)]))   # Reno to Salt Lake
EOF
```

- [ ] **Step 2: Prepare each one and time it**

```bash
for o in home-compact north-south east-west; do
  /usr/bin/time -p .venv/bin/python scripts/order.py prepare "$HOME/Tecopa Orders/_acceptance/$o"
done
```

Expected: three reports. If a build fails, read `work/plate/` and the printed tail. Fix the cause, not the symptom.

- [ ] **Step 3: Check each plate**

```bash
.venv/bin/python - <<'EOF'
import json, os
from app.regions import Region
A = os.path.expanduser("~/Tecopa Orders/_acceptance")
for o in ("home-compact", "north-south", "east-west"):
    s = json.load(open(f"{A}/{o}/work/state.json"))
    p = s["plate"]
    r = Region(p["id"], p["root"])
    dem = os.path.join(r.dir, "dem.tif")
    print(o, r.readiness()["ready"], r.cfg["native_resolution_m"] == p["grid_m"],
          s["epsg"], p["grid_m"], p.get("layer_m"), p.get("build_seconds"),
          f"{os.path.getsize(dem) / 1e6:.0f} MB" if os.path.exists(dem) else "no dem")
EOF
```

Expected: `True True` on every line, and `5070` on the east-west line.

- [ ] **Step 4: Show Dom the overviews.** Send the three `work/plate/<id>/overview.png` files to Dom with the table from Step 3. Ask one question: does each plate look like the right ground?

No commit. The acceptance orders stay on the Mac.

---

### Task 10: Docs

**Goal:** The repo documents the order pipeline's first step to the documentation standard, and records the decisions and measurements from this plan.

**Files:**
- Modify: `CLAUDE.md` (router row)
- Modify: `docs/changing-things.md` (new section "Run an order", after "Build a new plate")
- Modify: `docs/architecture.md` (Module map rows)
- Modify: `docs/decisions.md` (new dated section)
- Modify: `docs/superpowers/specs/2026-09-24-order-pipeline-design.md` (section 3 bullets)

**Acceptance Criteria:**
- [ ] `CLAUDE.md` routes "An order, `scripts/order.py`" to the spec, then Run an order, and stays under its token budget.
- [ ] Run an order says how to make a folder, the command, what the report means, where the cache is, and what running again does.
- [ ] The Module map lists `app/order.py`, `app/orderplate.py` and `app/orderprep.py` with their tests.
- [ ] `docs/decisions.md` has a 2026-09-24 section with the 2× cap, the grid/source split, the Task 1 numbers, the missing 3 m layer at Tecopa, and the Task 9 build times.
- [ ] The spec's section 3 matches what was built.
- [ ] `tests/test_docs.py` passes.

**Verify:** `.venv/bin/python -m pytest tests/test_docs.py -q` → pass. Then the full suite: `.venv/bin/python -m pytest -n auto -q` → only the baseline failure.

**Steps:**

- [ ] **Step 1: `CLAUDE.md`.** Add this row to "Read this before changing that", after the "A plate, `region_prep.py` …" row:

```markdown
| An order, `scripts/order.py` | `docs/superpowers/specs/2026-09-24-order-pipeline-design.md`, then Run an order |
```

- [ ] **Step 2: `docs/changing-things.md`.** Insert after the "Build a new plate" section, before "## Add a relief technique":

```markdown
## Run an order

Read `superpowers/specs/2026-09-24-order-pipeline-design.md` first. Sub-project 1 ships
Prepare's plate step only.

1. Make the order folder under `~/Tecopa Orders/` (or `$TECOPA_ORDERS_DIR`). Never
   inside the repo: it is public. Put the customer's GPX, KML or KMZ files in `in/`.
2. Write `order.toml`: `title` (required), `size` such as `"12x18"` (short side at most
   17 in, the PRO-1100's width), `orientation` (`portrait` or `landscape`).
3. Run `.venv/bin/python scripts/order.py prepare "<folder>"`. It needs `.venv-prep`.
4. Read the report. "Upsampling" above 1.00x means the terrain data is coarser than the
   print can show, up to the 2x limit. A widened frame means the data could not hold
   the nestled look at this size, and the warning names a smaller print.

Running Prepare again with the same tracks, size and orientation builds nothing. A
changed input, or a new manual frame in `state.json`, rebuilds the plate. `in/` is
never written. The plate lives in `work/plate/<id>/`. The HyRiver request cache is
`~/Tecopa Orders/_cache/`. It holds NHD, NLCD and dynamic-service requests. The static
10, 30 and 60 m tiles are read by GDAL and are not cached.

Traps already paid for:

- The 3DEP dynamic service fills a missing fine layer with resampled coarse data and
  says nothing. `scripts/dem_coverage.py` measures each layer first. Tecopa has 1 m
  lidar and no 3 m data.
- An order passes an explicit grid and source layer. `DEM_RES_CHOICES` is only the
  in-app auto planner's list, so adding 1 m there would make small in-app plates
  enormous.

Tests: `tests/test_orderplate.py`, `tests/test_order.py`, `tests/test_orderprep.py`
(stub subprocesses, no network), `tests/test_dem_coverage.py`.
```

- [ ] **Step 3: `docs/architecture.md`.** Add these rows to the Module map table, after the `app/regions.py` row:

```markdown
| `app/order.py` | One order folder: `order.toml`, the track files in `in/`, `work/state.json` and its `manual` key. `orders_root`, `cache_path`. | `tests/test_order.py` |
| `app/orderplate.py` | Pure plate planning for an order: nestled framing, projection, `choose_grid` from 3DEP coverage, widening, curated reuse. | `tests/test_orderplate.py` |
| `app/orderprep.py` | Prepare: reuse or build the order's plate through `.venv-prep` subprocesses, write state and the report. `scripts/order.py` is its command line. | `tests/test_orderprep.py` |
```

- [ ] **Step 4: `docs/decisions.md`.** Add a new section at the end of the decisions table area, following the file's existing dated-section format. Never edit an earlier row. Fill each bracket from your Task 1 and Task 9 notes. These are measurements, not placeholders.

```markdown
## 2026-09-24 (order plates)

| Decision | Why | Source |
|---|---|---|
| The zoom cap allows 2x upsampling (`MAX_UPSAMPLE`). Default framing still aims for 1x. | An order's size is what the customer paid for. Bilinear DEM reads keep 2x smooth. | Order pipeline spec, Amendments |
| An order plate's grid and its fetched 3DEP layer are separate (`--resolution`, `--source-resolution`). `DEM_RES_CHOICES` stays 10/30/60. | Adding 1 m to the auto list would make small in-app plates enormous. A plate sized to its print stays near 1.44x the print's pixels. | Plan 2026-09-24-order-plate-per-order, decision 1 |
| Sub-10 m grids come from the 3DEP dynamic service: [PASS or FAIL]. Laplacian ratio [ratio], NaN share [share], at the Tecopa probe bbox. | [PASS: it holds lidar detail. FAIL: `USE_DYNAMIC_FINE = False`, static layers only.] | Plan Task 1 |
| Coverage is measured per layer before use. Tecopa has 1 m and no 3 m. | The dynamic service fills gaps silently. | Plan Task 4 |
| Order plate build times on the Mac: home compact [s], north–south [s], east–west [s]. DEM sizes [MB each]. | The spec's target was under 10 minutes. | Plan Task 9 |
```

- [ ] **Step 5: The spec.** In `docs/superpowers/specs/2026-09-24-order-pipeline-design.md`, section 3, replace these two bullets:

```markdown
- Add 3 m and 1 m to `DEM_RES_CHOICES`. Pick the coarsest layer that meets the need.
```

```markdown
- Large frames fetch at the needed resolution. An 800 km road trip needs about
  160 m per pixel, not 10 m. The existing `GRID_BUDGET_MPX` still applies.
```

with:

```markdown
- The plate's grid follows the need: whole metres below 10 m, 5 m steps up to 100 m.
  Below 10 m the grid comes from the 3DEP dynamic service, backed by a finer layer
  that fully covers the plate. From 10 m up, the coarsest static layer (10, 30 or
  60 m) at or under the grid is fetched and averaged onto it. An 800 km road trip
  gets a 160 m grid from the 60 m layer. `DEM_RES_CHOICES` does not change.
  (Revised during planning, 2026-09-24.)
```

- [ ] **Step 6: Run the checks**

Run: `.venv/bin/python -m pytest tests/test_docs.py -q`, then `.venv/bin/python -m pytest -n auto -q`
Expected: docs pass. Full suite: only the baseline failure.

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md docs/changing-things.md docs/architecture.md docs/decisions.md docs/superpowers/specs/2026-09-24-order-pipeline-design.md
git commit -m "docs: run an order, and record the 2x cap, the grid and source split, and the order build times"
```

---

## Not in this plan

These belong to later sub-projects or were left out on purpose:

- The playa bake for order plates (`scripts/bake_playa.py` still reads `regions/`).
- The paper table, automatic orientation and size scoring (sub-project 2).
- Rendering a proof from an order plate. The registry reads only `regions/`, so the studio cannot open an order plate yet (sub-projects 2 and 3).
- Photos, the studio's order view and Approve (sub-project 3).
- The TIFF, `PRINT.txt` and the soft proof (sub-project 4).
- The customer package and the `docs/scope.md` amendment (sub-project 5).
