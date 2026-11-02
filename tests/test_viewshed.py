# tests/test_viewshed.py
"""Line of sight over a plate: app/viewshed.py. Pure NumPy in, a bool mask out."""
from __future__ import annotations
import math
import time

import numpy as np
import pytest
from scipy.ndimage import gaussian_filter

from app import viewshed
from app.viewshed import (EARTH_R_M, EYE_M, GRID_BUDGET_CELLS, REFRACTION,
                          SAMPLE_BUDGET, grid_res_m, seen_mask)


def _rough(n: int, relief_m: float = 1500.0, seed: int = 7) -> np.ndarray:
    """Mountains at two scales, deterministic, as float32 like a plate."""
    rng = np.random.default_rng(seed)
    z = gaussian_filter(rng.standard_normal((n, n)), n / 40) * (n / 40)
    z += 0.15 * gaussian_filter(rng.standard_normal((n, n)), n / 300) * (n / 300)
    z = (z - z.min()) / (z.max() - z.min()) * relief_m
    return z.astype(np.float32)


def _cone(n: int, res_m: float, height_m: float, base_radius_m: float) -> np.ndarray:
    yy, xx = np.indices((n, n), dtype=np.float32)
    d = np.hypot(xx - n // 2, yy - n // 2) * res_m
    return np.maximum(0.0, height_m * (1 - d / base_radius_m)).astype(np.float32)


def _radius_along(mask, cx, cy, ux, uy, res_m) -> float:
    """Ground metres from the centre to the first unseen cell along a direction."""
    step = 0
    while True:
        x, y = round(cx + ux * (step + 1)), round(cy + uy * (step + 1))
        if not (0 <= y < mask.shape[0] and 0 <= x < mask.shape[1]) or not mask[y, x]:
            return step * math.hypot(ux, uy) * res_m
        step += 1


def test_the_constants_are_the_spec_s():
    assert EYE_M == 1.7
    assert EARTH_R_M == 6_371_000.0
    assert REFRACTION == 0.87
    assert GRID_BUDGET_CELLS == 4_000_000


def test_the_grid_holds_the_budget_and_never_beats_the_plate():
    res = grid_res_m(483_000, 331_000, 30.0)
    assert res == pytest.approx(math.sqrt(483_000 * 331_000 / GRID_BUDGET_CELLS))
    assert (483_000 / res) * (331_000 / res) == pytest.approx(GRID_BUDGET_CELLS)
    assert grid_res_m(10_000, 10_000, 30.0) == 30.0


def test_a_ridge_blocks_the_view():
    dem = np.zeros((200, 400), dtype=np.float32)
    dem[:, 200:204] = 200.0                       # a 200 m wall at 30 m cells
    mask = seen_mask(dem, 30.0, [(150.0, 100.0)])
    assert mask.dtype == np.bool_ and mask.shape == dem.shape
    assert mask[100, 200]                         # the ridge's face
    assert not mask[100, 210:].any()              # the ground behind it
    assert mask[100, 150:190].all()               # the ground in front of it


def test_a_flat_plain_is_a_round_5_km():
    n, res = 801, 30.0
    mask = seen_mask(np.zeros((n, n), dtype=np.float32), res, [(n // 2, n // 2)])
    dirs = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
    radii = [_radius_along(mask, n // 2, n // 2, ux, uy, res) for ux, uy in dirs]
    assert all(4_000 <= r <= 6_500 for r in radii), radii
    assert max(radii) <= 1.10 * min(radii), radii
    # It is a filled disc: no ground short of the horizon is left out.
    yy, xx = np.indices(mask.shape)
    d = np.hypot(xx - n // 2, yy - n // 2) * res
    assert mask[d < 0.95 * min(radii)].all()
    assert not mask[d > 1.05 * max(radii)].any()


def test_rays_read_the_ground_bilinearly():
    """Decision 6. A plain tilted plate: truncating a ray's sample to a cell makes stairs,
    and each stair hides the ground behind it, in false edges along the axes."""
    n, res = 401, 30.0
    yy, xx = np.indices((n, n), dtype=np.float32)
    dem = ((xx + 0.37 * yy) * res * 0.05).astype(np.float32)
    at = (200.5, 200.25)
    mask = seen_mask(dem, res, [at])
    uphill = np.hypot(xx - at[0], yy - at[1]) < 150
    uphill &= (xx - at[0]) + 0.37 * (yy - at[1]) > 10
    assert mask[uphill].all(), f"{(~mask[uphill]).sum()} false edges"


def test_a_high_summit_sees_past_100_km():
    n, res = 1001, 500.0
    dem = _cone(n, res, 4_300.0, 30_000.0)
    mask = seen_mask(dem, res, [(n // 2, n // 2)])
    yy, xx = np.indices(mask.shape)
    d = np.hypot(xx - n // 2, yy - n // 2) * res
    assert mask[d > 100_000].any()
    # The horizon of a 4,300 m summit is about 250 km, and it is the curve that sets it.
    assert not mask[d > 262_000].any()


def test_a_far_view_has_no_spokes():
    """A mark that sees 200 km on a full-budget grid: rays are far apart out there, and
    every cell in sight is still True, right out to the plate's edge."""
    n, res = 2000, 250.0
    dem = _cone(n, res, 8_000.0, 40_000.0)
    cx = cy = n // 2
    mask = seen_mask(dem, res, [(float(cx), float(cy))])
    yy, xx = np.indices(mask.shape)
    d = np.hypot(xx - cx, yy - cy) * res
    horizon = math.sqrt(8_001.7 * 2 * EARTH_R_M / REFRACTION)      # ~342 km
    for ring_m in (60_000, 120_000, 180_000, 240_000):
        ring = np.abs(d - ring_m) < res
        assert mask[ring].all(), f"{(~mask[ring]).sum()} holes at {ring_m} m"
    disc = (d > 45_000) & (d < 0.97 * horizon)     # includes the plate's corners' reach
    assert mask[disc].all(), f"{(~mask[disc]).sum()} holes in the disc"


@pytest.mark.parametrize("shape,at", [((2000, 2000), (1000.0, 1000.0)),
                                      ((2000, 2000), (3.25, 1996.5)),
                                      ((1656, 2415), (2414.0, 0.0)),
                                      ((1656, 2415), (611.5, 1200.25))])
def test_a_mark_that_sees_everything_paints_every_cell(shape, at):
    """A deep bowl: all of it is in sight from anywhere in it. A hole here, at any
    distance or along the plate's edge, is a coverage bug, not a terrain answer."""
    h, w = shape
    res = 200.0
    yy, xx = np.indices(shape, dtype=np.float32)
    d = np.hypot(xx - w / 2, yy - h / 2) * res
    mask = seen_mask((d * d * 2e-4).astype(np.float32), res, [at])
    assert mask.all(), f"{(~mask).sum()} cells missing"


def _truly_seen(dem, res_m, x0, y0, x, y) -> bool:
    """Brute force: one line of sight to one cell, at half-cell steps."""
    span = math.hypot(x - x0, y - y0)
    if span < 1.0:
        return True
    t = np.append(np.arange(0.5, span, 0.5), span)
    px, py = x0 + (x - x0) * t / span, y0 + (y - y0) * t / span
    ix = np.minimum(px.astype(np.int64), dem.shape[1] - 2)
    iy = np.minimum(py.astype(np.int64), dem.shape[0] - 2)
    fx, fy = px - ix, py - iy
    top = dem[iy, ix] * (1 - fx) + dem[iy, ix + 1] * fx
    bottom = dem[iy + 1, ix] * (1 - fx) + dem[iy + 1, ix + 1] * fx
    z = top * (1 - fy) + bottom * fy
    metres = t * res_m
    eye = dem[int(y0), int(x0)] + EYE_M
    slope = (z - eye - REFRACTION * metres * metres / (2 * EARTH_R_M)) / metres
    return bool(slope[-1] >= slope.max())


def test_the_mask_claims_about_what_brute_force_finds():
    """The wash must not claim more than it knows: far from the mark, where painting is
    coarse, seen ground stays close to the truth in area and in place."""
    n, res = 600, 100.0
    dem = _rough(n, relief_m=2_000.0).astype(np.float64)
    y0, x0 = np.unravel_index(np.argmax(dem), dem.shape)
    x0, y0 = float(x0), float(y0)
    mask = seen_mask(dem, res, [(x0, y0)])
    rng = np.random.default_rng(23)
    xs, ys = rng.integers(0, n, 8_000), rng.integers(0, n, 8_000)
    truth = np.array([_truly_seen(dem, res, x0, y0, x, y) for x, y in zip(xs, ys)])
    fan = mask[ys, xs]
    far = np.hypot(xs - x0, ys - y0) > 250        # where painting has gone coarse
    assert truth[far].sum() > 150                  # enough seen ground to judge
    assert abs(fan.sum() - truth.sum()) <= 0.25 * truth.sum(), (fan.sum(), truth.sum())
    assert abs(fan[far].sum() - truth[far].sum()) <= 0.25 * truth[far].sum(), \
        (fan[far].sum(), truth[far].sum())
    seen_y, seen_x = np.nonzero(mask)
    pick = rng.integers(0, len(seen_y), 400)
    near = 0
    for y, x in zip(seen_y[pick], seen_x[pick]):
        window = ((a, b) for b in range(max(0, y - 3), min(n, y + 4))
                  for a in range(max(0, x - 3), min(n, x + 4)))
        near += any(_truly_seen(dem, res, x0, y0, a, b) for a, b in window)
    assert near >= 0.97 * len(pick), f"{near} of {len(pick)} within 3 cells"


def _notched_bowl(n, res, wall_r, notch_deg, notch_at):
    """A deep bowl (every cell in sight from its centre) with a wall round it at `wall_r`
    cells, tall enough to hide everything behind it, except a notch `notch_deg` wide that
    points `notch_at` degrees. Returns the DEM, each cell's distance from the centre in
    cells, and its angle from the notch's axis."""
    yy, xx = np.indices((n, n), dtype=np.float32)
    d = np.hypot(xx - n / 2, yy - n / 2)
    angle = np.degrees(np.arctan2(yy - n / 2, xx - n / 2))
    off_axis = (angle - notch_at + 180.0) % 360.0 - 180.0
    wall = (np.abs(d - wall_r) < 1.5) & (np.abs(off_axis) > notch_deg / 2)
    dem = (d * res) ** 2 * 2e-4
    return np.where(wall, dem + 1e7, dem).astype(np.float32), d, off_axis


@pytest.mark.parametrize("notch_at", [0.0, 33.7, 118.2])
def test_the_edge_of_what_a_notch_shows_is_not_pushed_out_by_a_tile(notch_at):
    """The across half of the four-neighbour rule. Far out, a seen sample paints a tile
    only when the samples on both sides of it, along the ray and across it, are seen too.
    Drop the across half and the samples on the flank of a notch paint whole tiles that
    reach past the notch's edge. Seen ground behind the wall may lie no more than a cell and
    a half outside the notch's angle. (Removing the across half put 100 to 600 cells there.)"""
    n, res, wall_r, notch_deg = 2000, 200.0, 300, 20.0
    dem, d, off_axis = _notched_bowl(n, res, wall_r, notch_deg, notch_at)
    mask = seen_mask(dem, res, [(n / 2, n / 2)])
    behind = d > wall_r + 3
    assert (mask & behind).sum() > 100_000          # the notch shows a real wedge
    slack = np.degrees(1.5 / np.maximum(d, 1.0))    # a cell and a half, as an angle
    outside = mask & behind & (np.abs(off_axis) > notch_deg / 2 + slack)
    assert outside.sum() == 0, f"{outside.sum()} seen cells lie outside the notch"


def test_a_far_ridge_one_cell_wide_is_not_stepped_over():
    """Ray samples grow apart with distance. A thin far ridge still blocks."""
    n, res = 2000, 100.0
    dem = _cone(n, res, 6_000.0, 20_000.0)
    dem[:, 1900] = 3_000.0                         # 90 km from the summit
    mask = seen_mask(dem, res, [(1000.0, 1000.0)])
    assert mask[1000, 1890:1900].any() or mask[1000, 1900]
    assert not mask[1000, 1960:].any()


def test_a_ray_stops_when_the_curve_hides_the_highest_ground():
    """A flat plate: the horizon is 5 km, the plate's edge is 250 km."""
    n, res = 2000, 250.0
    dem = np.zeros((n, n), dtype=np.float32)
    mask, samples = viewshed._sweep(dem, res, [(float(n // 2), float(n // 2))])
    per_ray = samples / viewshed.RAYS
    assert per_ray < 0.05 * (n // 2)               # a ray to the edge is 1,000 cells
    # And the rings really are cut short, not merely spread out.
    full = viewshed._fan(n, n).radii.searchsorted(n // 2)
    assert per_ray < 0.25 * full
    assert mask[n // 2, n // 2]


def test_high_ground_keeps_a_ray_going():
    """The stop is the plate's highest ground, not a fixed range: the same plate with a
    far peak runs its rays out to where that peak could still show."""
    n, res = 2000, 250.0
    flat = np.zeros((n, n), dtype=np.float32)
    peak = flat.copy()
    peak[100, 100] = 4_000.0
    at = [(float(n // 2), float(n // 2))]
    assert viewshed._sweep(peak, res, at)[1] > 3 * viewshed._sweep(flat, res, at)[1]


def test_nan_ground_neither_blocks_nor_counts():
    n, res = 301, 30.0
    dem = np.zeros((n, n), dtype=np.float32)
    dem[:, 180:190] = np.nan
    mask = seen_mask(dem, res, [(150.0, 150.0)])
    assert not mask[:, 180:190].any()              # it never counts as seen
    assert mask[150, 170:180].all()                # the ground before it
    assert mask[150, 190:220].all()                # the ground past it: no block
    reference = seen_mask(np.zeros((n, n), dtype=np.float32), res, [(150.0, 150.0)])
    away = np.ones((n, n), dtype=bool)
    away[:, 180:190] = False
    assert (mask[away] == reference[away]).all()


def test_a_mark_in_a_hole_uses_the_nearest_finite_ground():
    n, res = 401, 30.0
    yy, xx = np.indices((n, n))
    d = np.hypot(xx - 200, yy - 200)
    mound = np.where(d < 60, 300.0, 0.0).astype(np.float32)
    holed = mound.copy()
    holed[d < 5] = np.nan
    seen_from_hole = seen_mask(holed, res, [(200.0, 200.0)])
    seen_from_mound = seen_mask(mound, res, [(200.0, 200.0)])
    assert seen_from_hole.any()
    assert not seen_from_hole[d < 4.5].any()       # the hole itself is not ground
    outside = d >= 7
    assert (seen_from_hole[outside] == seen_from_mound[outside]).mean() > 0.995


def test_the_edges_never_fail():
    dem = np.zeros((50, 60), dtype=np.float32)
    assert not seen_mask(dem, 30.0, []).any()
    assert seen_mask(dem, 30.0, []).shape == dem.shape
    assert not seen_mask(np.full((50, 60), np.nan), 30.0, [(5.0, 5.0)]).any()
    off = [(-1.0, 5.0), (60.5, 5.0), (5.0, 50.5), (math.nan, 3.0), (3.0, math.inf)]
    assert not seen_mask(dem, 30.0, off).any()
    both = seen_mask(dem, 30.0, off + [(20.0, 20.0)])
    assert (both == seen_mask(dem, 30.0, [(20.0, 20.0)])).all()
    assert seen_mask(np.zeros((1, 40), dtype=np.float32), 30.0, [(5.0, 0.0)]).any()
    assert seen_mask(np.zeros((1, 1), dtype=np.float32), 30.0, [(0.0, 0.0)]).all()
    assert seen_mask(np.zeros((0, 0), dtype=np.float32), 30.0, [(0.0, 0.0)]).shape == (0, 0)


def test_a_mark_on_the_plate_s_last_cell_counts():
    dem = np.zeros((50, 60), dtype=np.float32)
    assert seen_mask(dem, 30.0, [(59.0, 49.0)]).any()


@pytest.mark.parametrize("at", [(59.4, 20.0), (-0.3, 20.0), (59.5, 20.0), (-0.5, 20.0),
                                (20.0, 49.5), (20.0, -0.5)])
def test_a_mark_inside_a_rim_cell_counts(at):
    """A cell reaches half a cell past its centre. A mark there is on the plate."""
    dem = np.zeros((50, 60), dtype=np.float32)
    mask = seen_mask(dem, 30.0, [at])
    clamped = (min(max(at[0], 0.0), 59.0), min(max(at[1], 0.0), 49.0))
    assert mask.any()
    assert (mask == seen_mask(dem, 30.0, [clamped])).all()


@pytest.mark.parametrize("at", [(60.5, 20.0), (61.0, 20.0), (59.6, 20.0), (-0.6, 20.0),
                                (20.0, 49.6), (20.0, -0.6)])
def test_a_mark_past_the_rim_is_ignored(at):
    assert not seen_mask(np.zeros((50, 60), dtype=np.float32), 30.0, [at]).any()


def test_the_input_is_left_alone():
    dem = _rough(100)
    dem[3, 3] = np.nan
    before = dem.copy()
    seen_mask(dem, 30.0, [(50.0, 50.0)])
    assert np.array_equal(dem, before, equal_nan=True)


def test_a_float64_plate_reads_the_same_as_a_float32_one():
    dem = _rough(120)
    at = [(60.0, 60.0)]
    assert (seen_mask(dem.astype(np.float64), 30.0, at) == seen_mask(dem, 30.0, at)).all()


def test_the_result_is_deterministic():
    dem = _rough(300)
    rng = np.random.default_rng(3)
    marks = [(float(x), float(y)) for x, y in rng.uniform(0, 299, (40, 2))]
    first = seen_mask(dem, 60.0, marks)
    assert (first == seen_mask(dem.copy(), 60.0, list(marks))).all()
    assert (first == seen_mask(dem, 60.0, marks[::-1])).all()      # order is no input


def test_a_seen_mask_moves_with_its_mark():
    dem = _rough(300)
    assert (seen_mask(dem, 60.0, [(50.0, 50.0)]) != seen_mask(dem, 60.0, [(250.0, 250.0)])).any()


@pytest.mark.parametrize("count", [10, 500])
def test_more_marks_never_lose_ground(count):
    dem = _rough(400)
    rng = np.random.default_rng(count)
    marks = [(float(x), float(y)) for x, y in rng.uniform(0, 399, (count + 1, 2))]
    fewer = seen_mask(dem, 100.0, marks[:-1])
    more = seen_mask(dem, 100.0, marks)
    assert not (fewer & ~more).any()
    assert more.sum() >= fewer.sum()


def test_the_sample_budget_covers_1000_marks_on_a_full_grid():
    n = int(math.sqrt(GRID_BUDGET_CELLS))
    fan = viewshed._fan(n, n)
    # Every ray from the plate's centre, run out to the corner with nothing stopping it.
    reach = fan.radii.searchsorted(math.hypot(n, n) / 2) + 1
    assert viewshed.RAYS * reach * 1_000 <= SAMPLE_BUDGET


def test_the_shared_fan_cannot_be_written():
    """A fan is cached across calls: one stray write would change every later mask."""
    fan = viewshed._fan(64, 64)
    arrays = [a for a in fan if isinstance(a, np.ndarray)]
    arrays += [a for band in fan.bands for a in band if isinstance(a, np.ndarray)]
    assert arrays and not any(a.flags.writeable for a in arrays)


def test_a_mark_s_rays_do_not_depend_on_how_many_marks_there_are():
    assert viewshed._fan(500, 500) is viewshed._fan(500, 500)      # no count in the key
    dem = _rough(200)
    at = (100.0, 100.0)
    alone = viewshed._sweep(dem, 60.0, [at])[1]
    crowd = viewshed._sweep(dem, 60.0, [at] * 3)[1]
    assert crowd == 3 * alone


@pytest.mark.slow
def test_the_budget_holds_at_1000_marks():
    n = 2000
    dem = _rough(n, relief_m=3000.0)
    rng = np.random.default_rng(11)
    marks = [(float(x), float(y)) for x, y in rng.uniform(0, n - 1, (1000, 2))]
    started = time.perf_counter()
    mask = seen_mask(dem, 250.0, marks)
    elapsed = time.perf_counter() - started
    assert mask.any() and not mask.all()
    assert elapsed < 45.0, f"{elapsed:.1f} s"


def test_no_mark_is_ever_dropped_by_count():
    """The 1,000th mark paints as surely as the first."""
    n = 120
    dem = np.zeros((n, n), dtype=np.float32)
    dem[:, 60:] = 500.0                            # neither mark sees the other's side
    marks = [(5.0, 5.0)] * 999 + [(110.0, 110.0)]
    mask = seen_mask(dem, 30.0, marks)
    assert mask[110, 110] and mask[5, 5]
    assert (mask == (seen_mask(dem, 30.0, [(5.0, 5.0)])
                     | seen_mask(dem, 30.0, [(110.0, 110.0)]))).all()


def test_eye_height_is_part_of_the_answer():
    """A flat plain's radius is sqrt(2 R eye / refraction), near enough."""
    n, res = 801, 30.0
    mask = seen_mask(np.zeros((n, n), dtype=np.float32), res, [(400.0, 400.0)])
    expected = math.sqrt(EYE_M * 2 * EARTH_R_M / REFRACTION)
    assert _radius_along(mask, 400, 400, 1, 0, res) == pytest.approx(expected, rel=0.05)
