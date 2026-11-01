#!/usr/bin/env python3
"""Score a plate elevation file for resampling stripes.

Low-order resampling onto a rotated or differently spaced grid leaves a periodic
diagonal pattern in a DEM (docs/superpowers/plans/2026-11-01-dem-lanczos-resampling.md).
Such a pattern is a narrow spike in the 2-D spectrum, and natural terrain has none, so
the score is each cell's spectral magnitude over the median around it. A score of
STRIPE_RED_SCORE or more is striped.

Usage:
    scripts/stripe_check.py <dem.tif> [xmin ymin xmax ymax]     # exit 1 when striped
"""
import sys

import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds
from scipy.ndimage import gaussian_filter, median_filter

STRIPE_RED_SCORE = 12.0
MAX_PERIOD_M = 300.0      # longer waves are terrain, however regular they look
MAX_NAN_SHARE = 0.01      # a window with more holes than this is not scored


def peaks(a, dx, dy, n=3):
    """The n strongest spectral spikes of the grid `a` with cells dx x dy metres, each
    {score, period_m, angle_deg}, strongest first."""
    a = np.where(np.isnan(a), np.nanmean(a), a).astype("float64")
    g = a - gaussian_filter(a, 12)
    h, w = g.shape
    f = np.abs(np.fft.fftshift(np.fft.fft2(g * np.outer(np.hanning(h), np.hanning(w)))))
    fx, fy = np.meshgrid(np.fft.fftshift(np.fft.fftfreq(w, dx)),
                         np.fft.fftshift(np.fft.fftfreq(h, dy)))
    r = np.hypot(fx, fy)
    s = f / (median_filter(f, size=25, mode="nearest") + 1e-9)
    s[(r < 1 / MAX_PERIOD_M) | (fy < 0) | ((fy == 0) & (fx < 0))] = 0   # one half-plane
    out = []
    for _ in range(n):
        j = np.unravel_index(np.argmax(s), s.shape)
        out.append({"score": round(float(s[j]), 1),
                    "period_m": round(float(1 / r[j]), 1),
                    "angle_deg": round(float(np.degrees(np.arctan2(fy[j], fx[j]))), 1)})
        s[max(0, j[0] - 6):j[0] + 7, max(0, j[1] - 6):j[1] + 7] = 0
    return out


def scan(path, grid=6, size=400):
    """Score a grid x grid spread of size x size windows of the file at `path`:
    {red, valid, median, worst}. Median and worst are 0.0 when no window is valid."""
    scores = []
    with rasterio.open(path) as d:
        dx, dy = d.res
        for fx in np.linspace(0.1, 0.9, grid) if grid > 1 else [0.5]:
            for fy in np.linspace(0.1, 0.9, grid) if grid > 1 else [0.5]:
                col = min(max(0, int(d.width * fx) - size // 2), max(0, d.width - size))
                row = min(max(0, int(d.height * fy) - size // 2), max(0, d.height - size))
                a = d.read(1, window=Window(col, row, size, size))
                if np.isnan(a).mean() > MAX_NAN_SHARE:
                    continue
                scores.append(peaks(a, dx, dy, 1)[0]["score"])
    return {"red": sum(s >= STRIPE_RED_SCORE for s in scores), "valid": len(scores),
            "median": float(np.median(scores)) if scores else 0.0,
            "worst": float(max(scores)) if scores else 0.0}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in (1, 5):
        print(__doc__)
        return 2
    with rasterio.open(argv[0]) as d:
        win = (from_bounds(*map(float, argv[1:]), d.transform) if len(argv) == 5
               else Window(max(0, d.width // 2 - 300), max(0, d.height // 2 - 300), 600, 600))
        a = d.read(1, window=win)
        dx, dy = d.res
    p = peaks(a, dx, dy)
    red = p[0]["score"] >= STRIPE_RED_SCORE
    print("RED" if red else "GREEN", a.shape, p)
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
