#!/usr/bin/env python3
"""
Generate a synthetic-but-realistic GPX standing in for a real OnX/Avenza export,
until a real one is on hand. Several day-trips between Susanville and the south
shore of Eagle Lake (Lassen County, CA), each an out-and-back with per-day route
variation and GPS jitter, so ingest / density / render have something true to
life to chew on. Deterministic (fixed RNG seed), so the committed fixture is stable.

Output: tests/fixtures/sample.gpx
"""
from __future__ import annotations
import math, os, random
from datetime import datetime, timedelta, timezone

# --- anchor points (lon, lat) ---
SUSANVILLE = (-120.6530, 40.4163)          # downtown-ish start / home base
# corridor waypoints heading north-northwest toward Eagle Lake's south shore
CORRIDOR = [
    SUSANVILLE,
    (-120.6600, 40.4350),
    (-120.6720, 40.4600),
    (-120.6900, 40.4850),
    (-120.7080, 40.5100),
    (-120.7200, 40.5350),
    (-120.7300, 40.5550),                  # south-shore arrival
]
# per-day destination spots around the south / west shore (lon, lat)
LAKE_SPOTS = [
    (-120.7300, 40.5700),                  # Merrill / Aspen Grove
    (-120.7450, 40.5850),                  # Gallatin Beach
    (-120.7600, 40.6050),                  # west shore
    (-120.7350, 40.5950),                  # marina-ish
    (-120.7250, 40.5650),                  # south boat launch
]

M_PER_DEG_LAT = 111_132.0
def m_per_deg_lon(lat): return 111_320.0 * math.cos(math.radians(lat))

def interp(polyline, step_m):
    """Densify a lon/lat polyline to ~step_m spacing (equirectangular approx)."""
    out = [polyline[0]]
    for (lon0, lat0), (lon1, lat1) in zip(polyline, polyline[1:]):
        latm = (lat0 + lat1) / 2
        dx = (lon1 - lon0) * m_per_deg_lon(latm)
        dy = (lat1 - lat0) * M_PER_DEG_LAT
        n = max(1, int(math.hypot(dx, dy) / step_m))
        for k in range(1, n + 1):
            f = k / n
            out.append((lon0 + (lon1 - lon0) * f, lat0 + (lat1 - lat0) * f))
    return out

def jitter(points, rng, sigma_m, lateral_m, lat_ref=40.5):
    """Per-point GPS noise plus a constant per-day lateral offset."""
    mlon = m_per_deg_lon(lat_ref)
    out = []
    for lon, lat in points:
        jlon = (rng.gauss(0, sigma_m) + lateral_m) / mlon
        jlat = rng.gauss(0, sigma_m) / M_PER_DEG_LAT
        out.append((lon + jlon, lat + jlat))
    return out

def build():
    rng = random.Random(40)                # determinism
    trips = []
    start = datetime(2024, 6, 1, 7, 30, tzinfo=timezone.utc)
    for i, spot in enumerate(LAKE_SPOTS):
        route = CORRIDOR + [spot]          # drive up the corridor, end at the day's spot
        out = interp(route, step_m=24.0)
        back = list(reversed(interp(route, step_m=27.0)))
        path = jitter(out + back[1:], rng, sigma_m=4.0, lateral_m=(i - 2) * 60.0)
        day = start + timedelta(days=i * 9)
        stamps = [day + timedelta(seconds=4 * k) for k in range(len(path))]
        trips.append((f"Susanville to Eagle Lake {day.date().isoformat()}", path, stamps))
    return trips

def to_gpx(trips):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<!-- SYNTHETIC dummy track from scripts/make_dummy_gpx.py -->',
             '<!-- Stand-in for a real OnX/Avenza export. Susanville <-> Eagle Lake, Lassen Co. CA. -->',
             '<gpx version="1.1" creator="trailprint-dummy" xmlns="http://www.topografix.com/GPX/1/1">']
    for name, path, stamps in trips:
        lines.append(f'  <trk><name>{name}</name><trkseg>')
        for (lon, lat), t in zip(path, stamps):
            lines.append(f'    <trkpt lat="{lat:.6f}" lon="{lon:.6f}">'
                         f'<time>{t.strftime("%Y-%m-%dT%H:%M:%SZ")}</time></trkpt>')
        lines.append('  </trkseg></trk>')
    lines.append('</gpx>')
    return "\n".join(lines) + "\n"

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.normpath(os.path.join(here, "..", "tests", "fixtures", "sample.gpx"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    trips = build()
    with open(out, "w") as f:
        f.write(to_gpx(trips))
    npts = sum(len(p) for _, p, _ in trips)
    print(f"wrote {out}: {len(trips)} tracks, {npts} points")

if __name__ == "__main__":
    main()
