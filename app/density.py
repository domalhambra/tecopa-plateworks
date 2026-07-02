# app/density.py
from __future__ import annotations
import numpy as np

def _rasterize_visits(tracks, bounds, cell_m):
    min_x, min_y, max_x, max_y = bounds
    nx = max(1, int((max_x - min_x) / cell_m))
    ny = max(1, int((max_y - min_y) / cell_m))
    # For each cell, collect the set of distinct track keys passing through it.
    sets = [[set() for _ in range(nx)] for _ in range(ny)]
    for i, t in enumerate(tracks):
        # prefer distinct days; day-less tracks each count as their own visit. The
        # list index (not track_id) disambiguates: ids restart at "<name>-0" per
        # FILE, so two day-less files' tracks used to collide and undercount.
        key = t.day or f"__anon-{i}"
        c = t.coords
        # densify so a straight segment still marks every cell it crosses
        seg_len = np.hypot(np.diff(c[:, 0]), np.diff(c[:, 1]))
        for i in range(len(c) - 1):
            # linspace takes a POINT count, not an interval count: +1 turns the
            # interval count into points, and max(2, ...) guarantees both
            # endpoints are always sampled so a segment's destination cell is
            # never dropped (a short leg crossing a cell boundary still marks it).
            n_pts = max(2, int(seg_len[i] / (cell_m * 0.5)) + 1)
            xs = np.linspace(c[i, 0], c[i+1, 0], n_pts)
            ys = np.linspace(c[i, 1], c[i+1, 1], n_pts)
            for x, y in zip(xs, ys):
                gx = int((x - min_x) / cell_m); gy = int((max_y - y) / cell_m)
                if 0 <= gx < nx and 0 <= gy < ny:
                    sets[gy][gx].add(key)
    grid = np.array([[len(sets[j][i]) for i in range(nx)] for j in range(ny)], dtype=float)
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
