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
import math


# ---- order plates: every grid is fetched at its own cell size ----

def test_auto_plans_are_unchanged_from_the_original_planner():
    # values computed by region_prep at 47b0719, before any order-plate change
    lassen = rp.plan_build(LASSEN, "EPSG:32610")
    assert lassen["resolution_m"] == 10 and lassen["n_slices"] == 1
    assert lassen["grid"] == (3416, 4984)
    assert lassen["dynamic"] is False
    corridor = rp.plan_build(CORRIDOR, "EPSG:32611")
    assert corridor["resolution_m"] == 30 and corridor["n_slices"] == 5
    assert corridor["grid"] == (16096, 11027)
    assert corridor["dynamic"] is False


def test_dynamic_plan_sizes_slices_for_the_oversampled_fetch():
    # 4 m is off DEM_RES_CHOICES: the dynamic service returns more cells than asked
    plan = rp.plan_build(LASSEN, "EPSG:32610", resolution_m=4.0)
    assert plan["dynamic"] is True
    assert plan["n_slices"] == math.ceil(
        plan["grid_mpx"] * rp.DYNAMIC_OVERSAMPLE / rp.SLICE_BUDGET_MPX)


def test_slice_overlap_deg_keeps_0_03_for_static_and_scales_below_10_m():
    assert rp.slice_overlap_deg(10) == 0.03
    assert rp.slice_overlap_deg(60) == 0.03
    assert rp.slice_overlap_deg(0.5) == 0.002                  # floor
    assert rp.slice_overlap_deg(4) == pytest.approx(300 * 4 / 111_320)   # ~0.0108


def test_resolution_arg():
    assert rp._resolution_arg("auto") is None
    assert rp._resolution_arg("2.5") == 2.5
    # a static layer stays the int it always was, so manifests don't change
    assert rp._resolution_arg("10") == 10 and isinstance(rp._resolution_arg("10"), int)


def test_resolution_arg_rejects_bad_values():
    for bad in ("0", "-5", "not-a-number", "inf", "nan"):
        with pytest.raises(argparse.ArgumentTypeError):
            rp._resolution_arg(bad)


def test_sources_manifest_names_a_static_layer(tmp_path):
    m = rp.write_sources_manifest(str(tmp_path), "r", (-116.3, 35.8, -116.2, 35.9),
                                  "EPSG:32611", built="2026-09-24", resolution_m=10)
    assert m["sources"][0]["dataset"] == "USGS 3DEP 10 m DEM"
    assert m["rebuild"].endswith("--resolution 10")
    assert "--source-resolution" not in m["rebuild"]


def test_sources_manifest_names_the_dynamic_service(tmp_path):
    m = rp.write_sources_manifest(str(tmp_path), "order_y", (-116.3, 35.8, -116.2, 35.9),
                                  "EPSG:32611", built="2026-09-24", resolution_m=25.0)
    assert m["sources"][0]["dataset"] == "USGS 3DEP dynamic service, 25 m"
    assert "--resolution 25.0" in m["rebuild"]
    assert "--source-resolution" not in m["rebuild"]
