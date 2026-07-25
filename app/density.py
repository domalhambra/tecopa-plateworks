# app/density.py
from __future__ import annotations
import numpy as np

def _densify(a, b, n_pts):
    """The concatenation of `np.linspace(a[i], b[i], n_pts[i])` for every i, in one
    array -- the vectorized twin of the per-segment linspace this used to call in a
    Python loop (~96k calls on a region-wide upload). numpy's own formula is
    reproduced exactly (`start + step * arange(n)`, with the last point PINNED to
    `stop`), so every sample lands on the identical float and the visit grid is
    bit-identical to the scalar version."""
    starts = np.concatenate([[0], np.cumsum(n_pts)[:-1]])
    within = np.arange(int(n_pts.sum())) - np.repeat(starts, n_pts)   # 0..n-1 per segment
    step = (b - a) / (n_pts - 1)                                      # n_pts >= 2 always
    out = within * np.repeat(step, n_pts)
    out += np.repeat(a, n_pts)
    out[starts + n_pts - 1] = b                                       # linspace pins the end
    return out


def _rasterize_visits(tracks, bounds, cell_m):
    min_x, min_y, max_x, max_y = bounds
    nx = max(1, int((max_x - min_x) / cell_m))
    ny = max(1, int((max_y - min_y) / cell_m))
    # Each cell counts the DISTINCT keys passing through it. Expressed as a set of
    # (cell, key) pairs rather than a grid of Python sets: one np.unique over the
    # pairs is the same de-duplication, without materializing nx*ny set objects for
    # a corridor-scale plate (a 1000 km region at 1 km cells is ~1e6 of them).
    pairs, key_ids = [], {}
    for i, t in enumerate(tracks):
        # prefer distinct days; day-less tracks each count as their own visit. The
        # list index (not track_id) disambiguates: ids restart at "<name>-0" per
        # FILE, so two day-less files' tracks used to collide and undercount.
        key = t.day or f"__anon-{i}"
        kid = key_ids.setdefault(key, len(key_ids))
        c = np.asarray(t.coords, dtype=float)
        if len(c) < 2:
            continue
        # densify so a straight segment still marks every cell it crosses.
        # linspace takes a POINT count, not an interval count: +1 turns the interval
        # count into points, and max(2, ...) guarantees both endpoints are always
        # sampled so a segment's destination cell is never dropped (a short leg
        # crossing a cell boundary still marks it).
        seg_len = np.hypot(np.diff(c[:, 0]), np.diff(c[:, 1]))
        n_pts = np.maximum(2, (seg_len / (cell_m * 0.5)).astype(np.int64) + 1)
        xs = _densify(c[:-1, 0], c[1:, 0], n_pts)
        ys = _densify(c[:-1, 1], c[1:, 1], n_pts)
        # int() truncates toward zero, and so does .astype -- an out-of-region point
        # just west of min_x lands on 0 in BOTH, and is kept or dropped identically.
        gx = ((xs - min_x) / cell_m).astype(np.int64)
        gy = ((max_y - ys) / cell_m).astype(np.int64)
        keep = (gx >= 0) & (gx < nx) & (gy >= 0) & (gy < ny)
        if not keep.any():
            continue
        # dedupe within the track first: the pair list then holds at most one entry
        # per (cell, track), not one per sampled point.
        pairs.append((np.unique(gy[keep] * nx + gx[keep]), kid))
    grid = np.zeros((ny, nx), dtype=float)
    if pairs:
        n_keys = max(1, len(key_ids))
        flat = np.concatenate([cells * n_keys + kid for cells, kid in pairs])
        cells = np.unique(flat) // n_keys          # distinct (cell, key) -> its cell
        counts = np.bincount(cells, minlength=nx * ny)
        grid = counts.reshape(ny, nx).astype(float)
    return grid, nx, ny

def hotspots(tracks, region_bounds, cell_m=1000, max_spots=7, min_spacing_m=6000):
    if not tracks:
        return []
    min_x, min_y, max_x, max_y = region_bounds
    grid, nx, ny = _rasterize_visits(tracks, region_bounds, cell_m)
    # candidate cells, strongest first
    order = np.dstack(np.unravel_index(np.argsort(grid, axis=None)[::-1], grid.shape))[0]
    spots = []
    for gy, gx in order:
        w = grid[gy, gx]
        if w < 1:
            break
        x = min_x + (gx + 0.5) * cell_m
        y = max_y - (gy + 0.5) * cell_m
        if all(np.hypot(x - s["x"], y - s["y"]) >= min_spacing_m for s in spots):
            spots.append({"x": float(x), "y": float(y), "weight": int(w)})
        if len(spots) >= max_spots:
            break
    return spots
