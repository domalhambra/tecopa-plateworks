# tests/test_region_prep.py
# The build planner: resolution auto-selection, memory-bounding slice counts, and
# grid geometry -- all pure logic (pyproj + numpy, no fetch stack), so the guard
# against another 15.8 GB accidental build runs in the core CI env.
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
