# app/viewshed.py
"""Line of sight over a plate: which ground can a customer's marks see?

Pure: NumPy in, a boolean mask out. No files, no spec. `render` reads the plate and
calls `seen_mask` on a grid from `grid_res_m` (decisions 4, 5 and 13 of
docs/superpowers/specs/2026-11-01-viewshed-wash-design.md).

The sweep. Every mark runs the same fixed fan: RAYS rays, with a ring every cell along
them, read from the plate with bilinear interpolation (decision 6). Along a ray, ground
is seen when its slope from the eye, after the drop of the curve, reaches the running
maximum slope so far. The fan is vectorised across rays, in bands of rings.

A ray ends early (decision 12): once its running maximum beats anything the plate's
highest ground could still show at every further ring. So distance comes from the
terrain: about 5 km from a flat playa, about 250 km from a high summit.

The fan never depends on how many marks there are, and one mark's result never depends
on another's. The mask is a plain union, so adding a mark can never lose ground. Total
work is bounded because the manifest caps a file at 1,000 marks; SAMPLE_BUDGET is the
ceiling the fan is sized to at that count.

Painting. Far out, rays are several cells apart, and painting every cell a seen sample's
fan cell touches, for every sample, would cost a mark millions of writes. So:

* A sample seen together with all four of its neighbours in the fan is inside seen
  ground. It paints four points into a coarse boolean layer, whose tile is sized so no
  tile inside seen ground can miss a point. A neighbour off the plate counts as seen.
* Any other seen sample is on the edge of what the mark sees. It stamps its own fan cell
  at cell resolution, so the seen edge is as sharp as the rays there can place it, about
  half a ray's spacing.

The layers are ORed down to the grid at the end. No holes and no spokes. A tile can still
overhang the seen edge by a few cells on the far side of a stamped sample, so the mask
leans slightly towards seen; tests/test_viewshed.py holds it to brute force."""
from __future__ import annotations
import math
from functools import lru_cache
from typing import NamedTuple, Sequence

import numpy as np
from scipy.ndimage import distance_transform_edt

EYE_M = 1.7                     # the eye above the ground at the mark (decision 3)
EARTH_R_M = 6_371_000.0
REFRACTION = 0.87               # the standard factor on the curve's drop (decision 12)
GRID_BUDGET_CELLS = 4_000_000   # any plate, a county or Oregon to Colorado (decision 13)

RAYS = 1024                     # every mark, always: see the module docstring
SAMPLE_BUDGET = 1_500_000_000   # A sizing ceiling, not a runtime limit: nothing here stops a
                                # sweep at it, and no mark is dropped for it. A test
                                # (test_the_sample_budget_covers_1000_marks_on_a_full_grid)
                                # holds that RAYS keeps the worst case under it.
                                # 1,000 marks x a whole fan from a full grid's centre, the
                                # ceiling RAYS is sized to. No plate reaches it. Measured on
                                # an Apple M5, one thread, 22 M samples/s: Rifle-Aspen's
                                # 1,000 marks took 462 M, 21 s; a bowl where every mark
                                # sees everything took 1,026 M, 47 s.

_NEAR_RINGS = 128               # rings near the mark, where most rays stop
_NEAR_BAND = 16                 # rings per band there: how soon a ray can stop
_FAR_BAND = 64                  # rings per band beyond
_ANGLE_STEP = 2 * math.pi / RAYS
_DROP_PER_M2 = REFRACTION / (2 * EARTH_R_M)


def grid_res_m(width_m: float, height_m: float, native_m: float) -> float:
    """The plate's area over GRID_BUDGET_CELLS as a cell size, never below the plate's own."""
    return max(float(native_m), math.sqrt(width_m * height_m / GRID_BUDGET_CELLS))


class _Band(NamedTuple):
    start: int                  # ring range [start, stop), read with ring `stop` as well
    stop: int
    radii: np.ndarray           # cells, float32, for rings start to stop inclusive
    tile: int                   # the coverage layer this band paints: tiles of 2**tile
    stamp_cos: np.ndarray       # the turns across a ray's wedge that stamp a fan cell
    stamp_sin: np.ndarray


class _Fan(NamedTuple):
    cos: np.ndarray             # (RAYS,) float32
    sin: np.ndarray
    sub_cos: np.ndarray         # (RAYS, 2): the two paint directions of a ray
    sub_sin: np.ndarray
    wedge_cos: np.ndarray       # (RAYS, 2): the two sides of a ray's wedge
    wedge_sin: np.ndarray
    radii: np.ndarray           # cells, float32, ascending, past the plate's far corner
    bands: tuple[_Band, ...]


def _frozen(array: np.ndarray) -> np.ndarray:
    array.setflags(write=False)
    return array


@lru_cache(maxsize=4)
def _fan(height: int, width: int) -> _Fan:
    """The one fan for a grid. Its key is the grid's shape and nothing else. Its arrays are
    shared across calls, so none can be written."""
    theta = (np.arange(RAYS) + 0.5) * _ANGLE_STEP       # half a step: no ray on an axis
    sub = np.stack([theta - _ANGLE_STEP / 4, theta + _ANGLE_STEP / 4], axis=1)
    wedge = np.stack([theta - _ANGLE_STEP / 2, theta + _ANGLE_STEP / 2], axis=1)
    radii = np.arange(1.0, math.ceil(math.hypot(height, width)) + 3.0, dtype=np.float32)
    bands = []
    start = 0
    while start < len(radii) - 1:                       # the last ring is only read ahead
        size = _NEAR_BAND if start < _NEAR_RINGS else _FAR_BAND
        stop = min(start + size, len(radii) - 1)
        spacing = max(1.0, float(radii[stop - 1]) * _ANGLE_STEP)
        # Four paint points sit spacing/2 apart; a tile of sqrt(2) times that always holds
        # one, whatever the fan's angle there.
        tile = max(0, math.ceil(math.log2(math.sqrt(2) * spacing / 2)))
        # A stamp's points sit under a cell apart along the arc, on the same rule.
        steps = max(1, math.ceil(math.sqrt(2) * spacing))
        turn = ((np.arange(steps) + 0.5) / steps - 0.5) * _ANGLE_STEP
        bands.append(_Band(start, stop, _frozen(radii[start:stop + 1].copy()), tile,
                           _frozen(np.cos(turn).astype(np.float32)),
                           _frozen(np.sin(turn).astype(np.float32))))
        start = stop
    return _Fan(*(_frozen(a.astype(np.float32)) for a in
                  (np.cos(theta), np.sin(theta), np.cos(sub), np.sin(sub),
                   np.cos(wedge), np.sin(wedge), radii)), tuple(bands))


def _bilinear(flat: np.ndarray, height: int, width: int, x: np.ndarray, y: np.ndarray,
              holes: bool) -> np.ndarray:
    """Bilinear ground at (x, y). A point off the plate reads the plate's edge. Corners that
    are NaN are left out, so ground next to a hole keeps its height; a point with no finite
    corner is NaN."""
    x = np.clip(x, 0.0, width - 1.0)
    y = np.clip(y, 0.0, height - 1.0)
    ix = np.minimum(x.astype(np.int32), max(width - 2, 0))
    iy = np.minimum(y.astype(np.int32), max(height - 2, 0))
    fx = x - ix
    fy = y - iy
    at = iy.astype(np.int64) * width + ix
    right = 1 if width > 1 else 0
    down = width if height > 1 else 0
    z00 = flat.take(at)
    z01 = flat.take(at + right)
    z10 = flat.take(at + down)
    z11 = flat.take(at + down + right)
    top = z00 + (z01 - z00) * fx
    bottom = z10 + (z11 - z10) * fx
    z = top + (bottom - top) * fy
    if holes:
        bad = np.isnan(z)
        if bad.any():
            corners = np.stack([z00[bad], z01[bad], z10[bad], z11[bad]])
            gx, gy = fx[bad], fy[bad]
            weights = np.stack([(1 - gx) * (1 - gy), gx * (1 - gy), (1 - gx) * gy, gx * gy])
            weights = np.where(np.isnan(corners), 0.0, weights)
            total = weights.sum(axis=0)
            with np.errstate(invalid="ignore", divide="ignore"):
                z[bad] = (np.nan_to_num(corners) * weights).sum(axis=0) / total
    return z


def _on_the_plate(cells: Sequence[tuple[float, float]], height: int, width: int
                  ) -> list[tuple[float, float]]:
    """Marks inside a cell of the grid, which reaches half a cell past its centre, moved onto
    the nearest cell centre if they sit past the last one. The caller reports the rest."""
    return [(min(max(float(x), 0.0), width - 1.0), min(max(float(y), 0.0), height - 1.0))
            for x, y in cells
            if math.isfinite(x) and math.isfinite(y)
            and -0.5 <= x <= width - 0.5 and -0.5 <= y <= height - 0.5]


def _sweep(dem: np.ndarray, res_m: float, cells: Sequence[tuple[float, float]]
           ) -> tuple[np.ndarray, int]:
    """The mask and the number of ground samples it took. `seen_mask` is the public door."""
    if res_m <= 0:
        raise ValueError(f"res_m must be positive, got {res_m}")
    dem = np.asarray(dem, dtype=np.float32)
    height, width = dem.shape
    mask = np.zeros(dem.shape, dtype=bool)
    if dem.size == 0:
        return mask, 0
    finite = np.isfinite(dem)
    all_finite = bool(finite.all())
    if not finite.any():
        return mask, 0
    marks = _on_the_plate(cells, height, width)
    if not marks:
        return mask, 0

    if not all_finite:                      # a NaN must never win `max` or `<`
        dem = np.where(finite, dem, np.nan)  # +-inf reads as a hole, too
    plate_max = float(np.nanmax(dem))
    flat = dem.ravel()
    fan = _fan(height, width)
    layers = [np.zeros(((height >> t) + 1, (width >> t) + 1), dtype=bool)
              for t in range(max(b.tile for b in fan.bands) + 1)]
    flat_layers = [layer.ravel() for layer in layers]      # views: writes reach the layer

    metres = fan.radii * float(res_m)
    drop = _DROP_PER_M2 * metres * metres
    inverse = 1.0 / metres
    nearest = None                          # the hole-filling index, only if one is needed
    all_rays = np.arange(RAYS)
    samples = 0

    for x0, y0 in marks:
        start = np.array([x0], dtype=np.float32), np.array([y0], dtype=np.float32)
        z0 = float(_bilinear(flat, height, width, start[0], start[1], False)[0])
        if math.isnan(z0):                  # the nearest finite ground
            if nearest is None:
                nearest = distance_transform_edt(~finite, return_distances=False,
                                                 return_indices=True)
            row, col = int(round(y0)), int(round(x0))
            z0 = float(dem[nearest[0][row, col], nearest[1][row, col]])
        eye = z0 + EYE_M
        mask[int(round(y0)), int(round(x0))] = True

        # The best slope the plate's highest ground could show at this ring or beyond.
        potential = (plate_max - eye - drop) * inverse
        best_ahead = np.maximum.accumulate(potential[::-1])[::-1]

        # How many of each ray's rings count as on the plate: a ray runs until its whole
        # wedge has left the last cell's outer edge, or the sliver between a grazing ray
        # and the plate's edge is never painted.
        with np.errstate(divide="ignore", invalid="ignore"):
            tx = np.where(fan.wedge_cos >= 0, width - 0.5 - x0, -0.5 - x0) / fan.wedge_cos
            ty = np.where(fan.wedge_sin >= 0, height - 0.5 - y0, -0.5 - y0) / fan.wedge_sin
        on_plate = fan.radii.searchsorted(np.minimum(tx, ty).max(axis=1), side="right")

        active = all_rays
        carried = np.full(RAYS, -np.inf, dtype=np.float32)
        before = np.ones(RAYS, dtype=bool)              # the ring inside the first: the mark
        for band in fan.bands:
            keep = on_plate[active] > band.start
            if not keep.all():
                active, carried = active[keep], carried[keep]
            if active.size == 0:
                break
            rings = band.stop - band.start
            samples += active.size * (rings + 1)
            x = x0 + fan.cos[active, None] * band.radii
            y = y0 + fan.sin[active, None] * band.radii
            z = _bilinear(flat, height, width, x, y, not all_finite)
            at = slice(band.start, band.stop + 1)
            slope = (z - eye - drop[at]) * inverse[at]
            if not all_finite:
                slope[np.isnan(slope)] = -np.inf
            running = np.maximum.accumulate(slope, axis=1)
            np.maximum(running, carried[:, None], out=running)
            seen = slope >= running
            if not all_finite:
                seen &= slope > -np.inf

            # (RAYS, rings + 2): the ring before the band, the band, the ring after it.
            grid = np.zeros((RAYS, rings + 2), dtype=bool)
            grid[active, 1:] = seen
            on = np.arange(band.start, band.stop + 1) < on_plate[:, None]
            grid[:, 1:-1] &= on[:, :-1]
            painted = grid[:, 1:-1].copy()
            grid[:, 1:] |= ~on
            grid[:, 0] = before
            before = grid[:, -2].copy()
            _paint(painted, grid, band, fan, flat_layers, layers, x0, y0, height, width)

            carried = running[:, rings - 1]
            alive = carried <= best_ahead[band.stop]
            if not alive.all():
                active, carried = active[alive], carried[alive]

    for t in range(len(layers) - 1, 0, -1):             # OR the coarse tiles down
        layer = layers[t]
        if layer.any():
            finer = layers[t - 1]
            grown = np.repeat(np.repeat(layer, 2, axis=0), 2, axis=1)
            finer |= grown[:finer.shape[0], :finer.shape[1]]
    mask |= layers[0][:height, :width]
    if not all_finite:
        mask &= finite                      # NaN ground never counts as seen
    return mask, samples


def _paint(painted: np.ndarray, grid: np.ndarray, band: _Band, fan: _Fan,
           flat_layers: list[np.ndarray], layers: list[np.ndarray],
           x0: float, y0: float, height: int, width: int) -> None:
    """Paint a band's seen samples. `grid` holds, ring by ring, what counts as seen for a
    neighbour, one ring wider than the band on each side. A point just off the plate paints
    the edge cell it left through: a tile the plate's edge cuts may hold no other point."""
    along = grid[:, :-2] & grid[:, 2:]
    across = np.roll(grid[:, 1:-1], 1, axis=0) & np.roll(grid[:, 1:-1], -1, axis=0)
    inside = along & across

    ray, ring = np.nonzero(painted & inside)
    if ray.size:
        layer, row_width = flat_layers[band.tile], layers[band.tile].shape[1]
        radius = band.radii[ring]
        for a in (0, 1):
            cos, sin = fan.sub_cos[ray, a], fan.sub_sin[ray, a]
            for r in (radius - 0.25, radius + 0.25):
                ix = np.floor(x0 + cos * r + 0.5).astype(np.int32).clip(0, width - 1)
                iy = np.floor(y0 + sin * r + 0.5).astype(np.int32).clip(0, height - 1)
                layer[(iy >> band.tile) * row_width + (ix >> band.tile)] = True

    ray, ring = np.nonzero(painted & ~inside)
    if ray.size:
        layer, row_width = flat_layers[0], layers[0].shape[1]
        radius = band.radii[ring, None]
        # cos(a + b), sin(a + b), across the ray's wedge
        cos = fan.cos[ray, None] * band.stamp_cos - fan.sin[ray, None] * band.stamp_sin
        sin = fan.sin[ray, None] * band.stamp_cos + fan.cos[ray, None] * band.stamp_sin
        for r in (radius - 0.25, radius + 0.25):
            ix = np.floor(x0 + cos * r + 0.5).astype(np.int32).clip(0, width - 1)
            iy = np.floor(y0 + sin * r + 0.5).astype(np.int32).clip(0, height - 1)
            layer[iy * row_width + ix] = True


def seen_mask(dem: np.ndarray, res_m: float, cells: list[tuple[float, float]]) -> np.ndarray:
    """Bool, the shape of `dem`: the union of what observers at float (col, row) can see.
    NaN ground neither blocks nor counts as seen. A mark outside the grid's cells is ignored
    here; a mark in a hole stands on the nearest finite ground. A pure function of its
    arguments."""
    return _sweep(dem, res_m, cells)[0]
