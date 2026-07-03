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
