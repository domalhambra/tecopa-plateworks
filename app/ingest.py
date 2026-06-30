# app/ingest.py
from __future__ import annotations
from dataclasses import dataclass
import io
import numpy as np
import gpxpy
from shapely.geometry import LineString
from app.geo import RegionGeo, lonlat_to_crs

@dataclass
class Track:
    track_id: str
    coords: np.ndarray   # (N, 2) float64, region CRS meters
    day: str | None      # ISO date if timestamps exist, else None

def load_gpx_tracks(data: bytes, region: RegionGeo,
                    simplify_tolerance_m: float = 15.0) -> list[Track]:
    gpx = gpxpy.parse(io.BytesIO(data))
    out: list[Track] = []
    idx = 0
    for trk in gpx.tracks:
        for seg in trk.segments:
            pts = [(p.longitude, p.latitude, p.time) for p in seg.points
                   if p.longitude is not None and p.latitude is not None]
            if len(pts) < 2:
                continue
            xy = np.array([lonlat_to_crs(region, lon, lat) for lon, lat, _ in pts])
            # Points outside the region's projection validity reproject to (inf, inf).
            # Drop them so a single off-region upload can't poison the track (and
            # later crash density's int() cast with OverflowError).
            xy = xy[np.isfinite(xy).all(axis=1)]
            if xy.shape[0] < 2:
                continue
            line = LineString(xy).simplify(simplify_tolerance_m, preserve_topology=False)
            coords = np.asarray(line.coords)
            if coords.shape[0] < 2:
                continue
            day = None
            t0 = next((t for _, _, t in pts if t is not None), None)
            if t0 is not None:
                day = t0.date().isoformat()
            out.append(Track(track_id=f"{trk.name or 'track'}-{idx}", coords=coords, day=day))
            idx += 1
    return out
