# tests/test_region_prep.py
# The build planner: resolution auto-selection, memory-bounding slice counts, and
# grid geometry -- all pure logic (pyproj + numpy, no fetch stack), so the guard
# against another 15.8 GB accidental build runs in the core CI env.
import numpy as np
import pytest
rp = pytest.importorskip("region_prep")

LASSEN = (-120.90, 40.33, -120.50, 40.78)          # county-scale (~34 x 50 km)
CORRIDOR = (-116.95, 39.20, -111.35, 42.05)        # elko_bonneville (~483 x 331 km)


def test_auto_picks_fine_grid_for_county_scale():
    plan = rp.plan_build(LASSEN, "EPSG:32610")
    assert plan["auto"] and plan["resolution_m"] == 10
    assert plan["n_slices"] == 1                    # small builds stay one-shot
    assert not plan["over_budget"]
    assert plan["landcover_resolution_m"] == 30


def test_auto_coarsens_corridor_scale_and_slices_it():
    plan = rp.plan_build(CORRIDOR, "EPSG:32611")
    assert plan["auto"] and plan["resolution_m"] == 30   # 10 m would be ~1.6 Gpx
    assert plan["grid_mpx"] <= rp.GRID_BUDGET_MPX
    assert plan["n_slices"] > 1                     # the memory cap engages
    assert plan["grid_mpx"] / plan["n_slices"] <= rp.SLICE_BUDGET_MPX
    assert plan["landcover_resolution_m"] == 60     # 30 m NLCD merge is the OOM


def test_explicit_resolution_is_honored_but_flagged():
    plan = rp.plan_build(CORRIDOR, "EPSG:32611", resolution_m=10)
    assert not plan["auto"] and plan["resolution_m"] == 10
    assert plan["over_budget"], "a ~1.6 Gpx build must be loudly flagged"
    # even forced-fine, slicing keeps the per-slice cost bounded
    assert plan["grid_mpx"] / plan["n_slices"] <= rp.SLICE_BUDGET_MPX


def test_projected_grid_matches_bbox_ground_size():
    w, h, transform = rp.projected_grid(CORRIDOR, "EPSG:32611", 30)
    # the elko_bonneville region was built on exactly this logic: ~483 x 331 km
    assert abs(w * 30 - 483_000) < 5_000
    assert abs(h * 30 - 331_000) < 5_000
    assert transform.a == 30 and transform.e == -30  # square pixels, north-up
    # grid-snapped origin (registration correctness downstream)
    assert transform.c % 30 == 0 and transform.f % 30 == 0


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


# ---- code review on 1652457: seam masking, overlap scaling, dynamic oversample ----

def test_sources_manifest_names_a_dynamic_layer(tmp_path):
    # 25 m is off DEM_RES_CHOICES -- the dynamic 3DEP service, not a static layer
    m = rp.write_sources_manifest(str(tmp_path), "order_y", (-116.3, 35.8, -116.2, 35.9),
                                  "EPSG:32611", built="2026-09-24",
                                  resolution_m=25, source_resolution_m=25)
    assert m["sources"][0]["dataset"] == "USGS 3DEP dynamic service, 25 m"


def test_dynamic_source_mpx_is_oversampled():
    # a static layer (30, in DEM_RES_CHOICES) and a dynamic one (25) asked over the
    # same bbox: only the dynamic estimate carries DYNAMIC_OVERSAMPLE
    PLATE = (-116.30, 35.80, -116.22, 35.87)
    static = rp.plan_build(PLATE, "EPSG:32611", resolution_m=30, source_resolution_m=30)
    dynamic = rp.plan_build(PLATE, "EPSG:32611", resolution_m=25, source_resolution_m=25)
    raw_w, raw_h, _ = rp.projected_grid(PLATE, "EPSG:32611", 25)
    assert dynamic["source_mpx"] == pytest.approx(
        raw_w * raw_h / 1e6 * rp.DYNAMIC_OVERSAMPLE, rel=1e-6)
    # sanity: the static path never gets the multiplier baked in silently
    raw_w2, raw_h2, _ = rp.projected_grid(PLATE, "EPSG:32611", 30)
    assert static["source_mpx"] == pytest.approx(raw_w2 * raw_h2 / 1e6, rel=1e-6)


def test_fetched_cell_m_takes_the_larger_actual_dimension():
    class _Rio:
        def resolution(self):
            return (3.25, -3.47)          # probed: 4 m asked, 3.25 x 3.47 m actual
    class _Da:
        rio = _Rio()
    assert rp._fetched_cell_m(_Da()) == pytest.approx(3.47)


def test_slice_overlap_deg_scales_with_source_and_is_clamped():
    assert rp.slice_overlap_deg(0.5) == rp.SLICE_OVERLAP_MIN_DEG      # floor
    assert rp.slice_overlap_deg(60) == rp.SLICE_OVERLAP_MAX_DEG        # old fixed ceiling
    assert rp.slice_overlap_deg(1) == pytest.approx(300 * 1 / 111_320.0)
    # a fine source gets a much smaller buffer than a coarse one
    assert rp.slice_overlap_deg(1) < rp.slice_overlap_deg(10) < rp.slice_overlap_deg(60)


def test_small_order_plate_keeps_the_real_per_slice_fetch_in_budget():
    # ~9 x 8 km at 1 m: the old fixed 0.03 deg overlap alone would have blown well
    # past SLICE_BUDGET_MPX just in buffer; the real (overlap-inclusive) per-slice
    # fetch must fit
    PLATE = (-116.30, 35.80, -116.22, 35.87)
    plan = rp.plan_build(PLATE, "EPSG:32611", resolution_m=1, source_resolution_m=1)
    assert plan["slice_mpx"] <= rp.SLICE_BUDGET_MPX
    assert rp._slice_source_mpx(PLATE, "EPSG:32611", 1, plan["n_slices"]) <= rp.SLICE_BUDGET_MPX


def test_corridor_60_10_still_bounds_the_real_per_slice_fetch():
    plan = rp.plan_build(CORRIDOR, "EPSG:32611", resolution_m=60, source_resolution_m=10)
    assert plan["slice_mpx"] <= rp.SLICE_BUDGET_MPX


def test_resolution_arg_rejects_inf_and_nan():
    for bad in ("0", "-5", "not-a-number", "inf", "nan"):
        with pytest.raises(argparse.ArgumentTypeError):
            rp._resolution_arg(bad)


def test_source_resolution_arg_rejects_bad_values_and_auto():
    for bad in ("0", "-1", "not-a-number", "inf", "nan", "auto"):
        with pytest.raises(argparse.ArgumentTypeError):
            rp._source_resolution_arg(bad)
    assert rp._source_resolution_arg("2.5") == 2.5


# ---- the CRITICAL fix: a dest cell only partly covered by a slice's own raster
# must never come back as a finite (wrong) value, or the later slice's partial edge
# silently overwrites an earlier slice's correct one and draws a seam. No
# xarray/rioxarray in .venv (region_prep runs those in .venv-prep, invariant 13), so
# this drives the extracted pure helper directly with hand-built numpy arrays and
# rasterio transforms -- a planar ramp z=x, two overlapping "slices" fetched at a
# fine source resolution and merged onto a coarser grid, exactly the 10 m -> 160 m
# case region_prep's fine-source order plates hit.

def test_partial_edge_cells_are_masked_not_averaged():
    from rasterio.transform import from_origin
    from rasterio.enums import Resampling
    crs = "EPSG:32611"

    def ramp(x0, x1, y0, y1, res):
        ncols = int(round((x1 - x0) / res))
        nrows = int(round((y1 - y0) / res))
        xs = x0 + (np.arange(ncols) + 0.5) * res
        arr = np.tile(xs, (nrows, 1)).astype("float32")
        return arr, from_origin(x0, y1, res, res)

    # slice A's raster genuinely stops at x=1810; slice B's genuinely starts at
    # x=1670 -- the 140 m of mutual overlap is what a scaled slice_overlap_deg
    # buffer is for, and it's what lets the fix pick a FULLY covered value
    a, ta = ramp(0, 1810, -100, 580, 10)
    b, tb = ramp(1670, 3200, -100, 580, 10)

    dst_transform = from_origin(0, 480, 160, 160)
    dst_shape = (3, 20)
    masked_a = rp._warp_slice(a, ta, crs, dst_transform, dst_shape, crs,
                              Resampling.average)
    masked_b = rp._warp_slice(b, tb, crs, dst_transform, dst_shape, crs,
                              Resampling.average)

    # column 10 (x 1600-1760) is fully inside A, only 56% inside B
    assert np.isfinite(masked_a[0, 10]) and np.isnan(masked_b[0, 10])
    # column 11 (x 1760-1920) is fully inside B, only 31% inside A
    assert np.isnan(masked_a[0, 11]) and np.isfinite(masked_b[0, 11])


def test_merged_slices_have_no_seam_and_match_the_true_ramp():
    from rasterio.transform import from_origin
    from rasterio.enums import Resampling
    crs = "EPSG:32611"

    def ramp(x0, x1, y0, y1, res):
        ncols = int(round((x1 - x0) / res))
        nrows = int(round((y1 - y0) / res))
        xs = x0 + (np.arange(ncols) + 0.5) * res
        arr = np.tile(xs, (nrows, 1)).astype("float32")
        return arr, from_origin(x0, y1, res, res)

    a, ta = ramp(0, 1810, -100, 580, 10)
    b, tb = ramp(1670, 3200, -100, 580, 10)
    dst_transform = from_origin(0, 480, 160, 160)
    dst_shape = (3, 20)

    masked_a = rp._warp_slice(a, ta, crs, dst_transform, dst_shape, crs,
                              Resampling.average)
    masked_b = rp._warp_slice(b, tb, crs, dst_transform, dst_shape, crs,
                              Resampling.average)
    # build_dem_cog's own merge: process A, then let B win only where B is finite
    merged = np.where(np.isnan(masked_b), masked_a, masked_b)

    true_centers = (np.arange(20) + 0.5) * 160
    assert not np.isnan(merged[0]).any()             # no gap at the seam column
    assert np.max(np.abs(merged[0] - true_centers)) < 1e-3   # and no seam-line bias
