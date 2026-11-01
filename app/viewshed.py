# app/viewshed.py
"""Line of sight over a plate: which ground can a customer's marks see?

Pure: NumPy in, a boolean mask out. No files, no spec. `render` reads the plate and
calls `seen_mask` on a grid from `grid_res_m` (decisions 4, 5 and 13 of
docs/superpowers/specs/2026-11-01-viewshed-wash-design.md).

The sweep. Every mark runs the same fixed fan: RAYS rays, and rings along them one cell
apart out to where the rays are one cell apart, then spreading with distance so the fan's
cells stay about square. Along a ray, ground is seen when its slope from the eye, after
the drop of the curve, reaches the running maximum slope so far. The fan is vectorised
across rays, in bands of rings.

A ray ends early (decision 12): once its running maximum beats anything the plate's
highest ground could still show at every further ring. So distance comes from the
terrain: about 5 km from a flat playa, about 250 km from a high summit.

The fan never depends on how many marks there are, and one mark's result never depends
on another's. The mask is a plain union, so adding a mark can never lose ground. Total
work is bounded because the manifest caps a file at 1,000 marks; SAMPLE_BUDGET is the
ceiling the fan is sized to at that count.

Far out, three things keep a wide fan honest:

* Ground: a band of rings reads a max-of-cells pyramid of the plate, at the level whose
  window is as wide as its ring spacing. A one-cell ridge between two far rings still blocks,
  instead of being stepped over. Bilinear at every level (decision 6).
* Coverage: each seen sample paints four points inside its fan cell, into a coarse
  boolean layer whose tile is sized so no tile inside seen ground can miss a point. The
  layers are ORed down to the grid at the end. No holes and no spokes, at a cost per
  sample and not per cell.
* The price is resolution: a far seen edge is as coarse as its tile (2 cells past about
  230 cells out, 4 past about 460, 8 past about 920). That is honest to what the rays there measured, and the wash's edge is a
  soft band on a wide sheet (decision 13)."""
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
SAMPLE_BUDGET = 550_000_000     # 1,000 marks x a whole fan from a full grid's centre, the
                                # ceiling RAYS is sized to. Measured on an Apple M5: the
                                # worst plate (every mark sees everything) ran at 22 M
                                # samples/s, so this is about 25 s on one thread.

_BAND_RINGS = 16                # how often a ray may stop, and the vectorised chunk
_EDGE_RINGS = 1                 # rings by which a seen sample paints out past the plate's edge
_ANGLE_STEP = 2 * math.pi / RAYS
_DROP_PER_M2 = REFRACTION / (2 * EARTH_R_M)


def grid_res_m(width_m: float, height_m: float, native_m: float) -> float:
    """The plate's area over GRID_BUDGET_CELLS as a cell size, never below the plate's own."""
    return max(float(native_m), math.sqrt(width_m * height_m / GRID_BUDGET_CELLS))


class _Band(NamedTuple):
    start: int                  # ring range [start, stop)
    stop: int
    radii: np.ndarray           # cells, float32, one per ring
    ground: int                 # the plate pyramid's level this band reads
    tile: int                   # the coverage layer this band paints: tiles of 2**tile


class _Fan(NamedTuple):
    cos: np.ndarray             # (RAYS,) float32
    sin: np.ndarray
    sub_cos: np.ndarray         # (RAYS, 2): the two paint directions of a ray
    sub_sin: np.ndarray
    wedge_cos: np.ndarray       # (RAYS, 2): the two sides of a ray's wedge
    wedge_sin: np.ndarray
    radii: np.ndarray           # cells, float64, ascending, past the plate's far corner
    sub_radii: np.ndarray       # (rings, 2) float32: a ring's inner and outer paint points
    bands: tuple[_Band, ...]


@lru_cache(maxsize=4)
def _fan(height: int, width: int) -> _Fan:
    """The one fan for a grid. Its key is the grid's shape and nothing else."""
    theta = (np.arange(RAYS) + 0.5) * _ANGLE_STEP       # half a step: no ray on an axis
    sub = np.stack([theta - _ANGLE_STEP / 4, theta + _ANGLE_STEP / 4], axis=1)
    wedge = np.stack([theta - _ANGLE_STEP / 2, theta + _ANGLE_STEP / 2], axis=1)
    reach = math.hypot(height, width) + 1.0
    near_end = 1.0 / _ANGLE_STEP                        # where rays are a cell apart
    radii = list(np.arange(1.0, near_end + 1.0))
    while radii[-1] < reach:
        radii.append(radii[-1] * (1.0 + _ANGLE_STEP))
    radii = np.array(radii, dtype=np.float64)
    radii = radii[:max(1, int(radii.searchsorted(reach)) + 1)]
    spacing = np.maximum(1.0, radii * _ANGLE_STEP)
    bands = []
    for start in range(0, len(radii), _BAND_RINGS):
        stop = min(start + _BAND_RINGS, len(radii))
        widest = float(spacing[start:stop].max())
        bands.append(_Band(
            start, stop, radii[start:stop].astype(np.float32),
            # A cell at least half the ring spacing, and a level's cell holds the max of
            # twice its width: no ridge fits between two rings, wherever they land.
            ground=max(0, math.ceil(math.log2(widest)) - 1),
            # Four points per fan cell sit widest/2 apart; a tile of sqrt(2) times that
            # always holds one, whatever the fan's angle there.
            tile=max(0, math.ceil(math.log2(math.sqrt(2) * widest / 2))),
        ))
    return _Fan(np.cos(theta).astype(np.float32), np.sin(theta).astype(np.float32),
                np.cos(sub).astype(np.float32), np.sin(sub).astype(np.float32),
                np.cos(wedge).astype(np.float32), np.sin(wedge).astype(np.float32),
                radii, np.stack([radii - spacing / 4, radii + spacing / 4],
                                axis=1).astype(np.float32), tuple(bands))


class _Level(NamedTuple):
    flat: np.ndarray            # float32, C order
    height: int
    width: int
    scale: float                # base cells per cell of this level


def _pyramid(dem: np.ndarray, levels: int) -> list[_Level]:
    """The plate, then coarser levels at every second cell, each cell the max of its 3x3 in
    the level below. Cell centres stay on base cells, and a level always has one on or past
    the plate's last cell, so a level never goes flat short of the edge. A NaN never wins."""
    out = [_Level(dem.ravel(), dem.shape[0], dem.shape[1], 1.0)]
    z = dem
    for level in range(1, levels):
        h, w = z.shape
        if not h % 2 or not w % 2:              # odd, so the last cell lands on the lattice
            z = np.pad(z, ((0, 1 - h % 2), (0, 1 - w % 2)), constant_values=np.nan)
        rows = z[::2].copy()
        between = z[1::2]
        rows[:-1] = np.fmax(rows[:-1], between)
        rows[1:] = np.fmax(rows[1:], between)
        z = rows[:, ::2].copy()
        between = rows[:, 1::2]
        z[:, :-1] = np.fmax(z[:, :-1], between)
        z[:, 1:] = np.fmax(z[:, 1:], between)
        out.append(_Level(z.ravel(), z.shape[0], z.shape[1], float(2 ** level)))
    return out


def _bilinear(level: _Level, x: np.ndarray, y: np.ndarray, holes: bool) -> np.ndarray:
    """Bilinear ground at base-grid (x, y). Corners that are NaN are left out, so ground
    next to a hole keeps its height; a point with no finite corner is NaN. Past the plate's
    edge, a ring off the plate reads the edge."""
    if level.scale > 1.0:
        x = x / level.scale
        y = y / level.scale
    x = np.clip(x, 0.0, level.width - 1.0)
    y = np.clip(y, 0.0, level.height - 1.0)
    ix = np.minimum(x.astype(np.int32), max(level.width - 2, 0))
    iy = np.minimum(y.astype(np.int32), max(level.height - 2, 0))
    fx = x - ix
    fy = y - iy
    at = iy.astype(np.int64) * level.width + ix
    right = 1 if level.width > 1 else 0
    down = level.width if level.height > 1 else 0
    z00 = level.flat.take(at)
    z01 = level.flat.take(at + right)
    z10 = level.flat.take(at + down)
    z11 = level.flat.take(at + down + right)
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
    marks = [(float(x), float(y)) for x, y in cells
             if math.isfinite(x) and math.isfinite(y)
             and 0.0 <= x <= width - 1 and 0.0 <= y <= height - 1]
    if not marks:
        return mask, 0

    if not all_finite:                      # a NaN must never win `max` or `<`
        dem = np.where(finite, dem, np.nan)  # +-inf reads as a hole, too
    plate_max = float(np.nanmax(dem))
    fan = _fan(height, width)
    ground = _pyramid(dem, max(b.ground for b in fan.bands) + 1)
    layers = [np.zeros(((height >> t) + 1, (width >> t) + 1), dtype=bool)
              for t in range(max(b.tile for b in fan.bands) + 1)]
    flat_layers = [layer.ravel() for layer in layers]      # views: writes reach the layer

    metres = fan.radii.astype(np.float32) * float(res_m)
    drop = _DROP_PER_M2 * metres * metres
    inverse = 1.0 / metres
    nearest = None                          # the hole-filling index, only if one is needed
    rays = np.arange(RAYS)
    samples = 0

    for x0, y0 in marks:
        start = np.array([x0], dtype=np.float32), np.array([y0], dtype=np.float32)
        z0 = float(_bilinear(ground[0], start[0], start[1], False)[0])
        if math.isnan(z0):                  # decision: the nearest finite ground
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
        # and the plate's edge is never painted. A ring just off the plate reads the edge.
        with np.errstate(divide="ignore", invalid="ignore"):
            tx = np.where(fan.wedge_cos >= 0, width - 0.5 - x0, -0.5 - x0) / fan.wedge_cos
            ty = np.where(fan.wedge_sin >= 0, height - 0.5 - y0, -0.5 - y0) / fan.wedge_sin
        on_plate = fan.radii.searchsorted(np.minimum(tx, ty).max(axis=1), side="right")

        active = rays
        carried = np.full(RAYS, -np.inf, dtype=np.float32)
        for band in fan.bands:
            keep = on_plate[active] > band.start
            if not keep.all():
                active, carried = active[keep], carried[keep]
            if active.size == 0:
                break
            x = x0 + fan.cos[active, None] * band.radii
            y = y0 + fan.sin[active, None] * band.radii
            z = _bilinear(ground[band.ground], x, y, not all_finite)
            slope = (z - eye - drop[band.start:band.stop]) * inverse[band.start:band.stop]
            if not all_finite:
                slope[np.isnan(slope)] = -np.inf
            running = np.maximum.accumulate(slope, axis=1)
            np.maximum(running, carried[:, None], out=running)
            seen = slope >= running
            if not all_finite:
                seen &= slope > -np.inf
            ends = on_plate[active]
            samples += int(np.minimum(ends - band.start, band.stop - band.start).sum())
            if (ends < band.stop).any():
                seen &= np.arange(band.start, band.stop) < ends[:, None]
            ray_i, ring_i = np.nonzero(seen)
            if ray_i.size:
                seen_rays, seen_rings = active[ray_i], band.start + ring_i
                # Near the plate's edge a pyramid level has no cell centre further out, so
                # its reading goes flat and rising ground falls out of sight falsely. A
                # seen sample in a ray's last rings therefore also paints out past the edge.
                near_edge = seen_rings >= ends[ray_i] - 1 - _EDGE_RINGS
                if near_edge.any():
                    edge_rays, edge_rings = seen_rays[near_edge], seen_rings[near_edge]
                    edge_ends = ends[ray_i][near_edge]
                    extra = [(edge_rays[edge_rings + o <= edge_ends],
                              edge_rings[edge_rings + o <= edge_ends] + o)
                             for o in range(1, _EDGE_RINGS + 2)]
                    seen_rays = np.concatenate([seen_rays, *(e[0] for e in extra)])
                    seen_rings = np.concatenate([seen_rings, *(e[1] for e in extra)])
                _paint(flat_layers[band.tile], layers[band.tile].shape[1], band.tile,
                       fan, seen_rays, seen_rings, x0, y0, width, height)
            carried = running[:, -1]
            if band.stop >= len(fan.radii):
                break
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


def _paint(layer: np.ndarray, layer_width: int, tile: int, fan: _Fan, rays: np.ndarray,
           rings: np.ndarray, x0: float, y0: float, width: int, height: int) -> None:
    """Four points inside each seen sample's fan cell, into a layer of 2**tile tiles. A
    point just off the plate paints the edge cell it left through: a tile the plate's edge
    cuts in half may hold no other point."""
    for a in (0, 1):
        cos, sin = fan.sub_cos[rays, a], fan.sub_sin[rays, a]
        for b in (0, 1):
            r = fan.sub_radii[rings, b]
            ix = np.floor(x0 + cos * r + 0.5).astype(np.int32).clip(0, width - 1)
            iy = np.floor(y0 + sin * r + 0.5).astype(np.int32).clip(0, height - 1)
            layer[(iy >> tile) * layer_width + (ix >> tile)] = True


def seen_mask(dem: np.ndarray, res_m: float, cells: list[tuple[float, float]]) -> np.ndarray:
    """Bool, the shape of `dem`: the union of what observers at float (col, row) can see.
    NaN ground neither blocks nor counts as seen. A mark off the grid is ignored here; a
    mark in a hole stands on the nearest finite ground. A pure function of its arguments."""
    return _sweep(dem, res_m, cells)[0]
