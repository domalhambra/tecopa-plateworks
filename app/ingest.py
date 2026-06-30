# app/ingest.py
from __future__ import annotations
from dataclasses import dataclass
import io
import re
import zipfile
import numpy as np
import gpxpy
from lxml import etree
from shapely.geometry import LineString
from app.geo import RegionGeo, lonlat_to_crs

@dataclass
class Track:
    track_id: str
    coords: np.ndarray   # (N, 2) float64, region CRS meters
    day: str | None      # ISO date if timestamps exist, else None

def _make_track(pts, region: RegionGeo, name, idx, simplify_tolerance_m):
    """Build one Track from points. pts: list of (lon, lat, time) where time is
    a datetime, an ISO string, or None. Reproject -> drop non-finite -> simplify."""
    pts = [(lo, la, t) for lo, la, t in pts if lo is not None and la is not None]
    if len(pts) < 2:
        return None
    xy = np.array([lonlat_to_crs(region, lo, la) for lo, la, _ in pts])
    # Points outside the region's projection validity reproject to (inf, inf).
    # Drop them so a single off-region upload can't poison the track (and later
    # crash density's int() cast with OverflowError).
    xy = xy[np.isfinite(xy).all(axis=1)]
    if xy.shape[0] < 2:
        return None
    line = LineString(xy).simplify(simplify_tolerance_m, preserve_topology=False)
    coords = np.asarray(line.coords)
    if coords.shape[0] < 2:
        return None
    t0 = next((t for _, _, t in pts if t is not None), None)
    day = None
    if t0 is not None:
        day = t0.date().isoformat() if hasattr(t0, "date") else str(t0)[:10]
    return Track(track_id=f"{name or 'track'}-{idx}", coords=coords, day=day)

def load_gpx_tracks(data: bytes, region: RegionGeo,
                    simplify_tolerance_m: float = 15.0) -> list[Track]:
    gpx = gpxpy.parse(io.BytesIO(data))
    out: list[Track] = []
    idx = 0
    for trk in gpx.tracks:
        for seg in trk.segments:
            pts = [(p.longitude, p.latitude, p.time) for p in seg.points]
            t = _make_track(pts, region, trk.name, idx, simplify_tolerance_m)
            if t is not None:
                out.append(t)
                idx += 1
    return out

def _localname(el):
    return etree.QName(el).localname

def _kml_segments(root):
    """Yield pts lists for every LineString and gx:Track, namespace-agnostic."""
    segs = []
    for el in root.iter():
        ln = _localname(el)
        if ln == "LineString":
            coord_el = next((c for c in el if _localname(c) == "coordinates"), None)
            if coord_el is None or not coord_el.text:
                continue
            # normalize "lon, lat, alt" (exporter quirk) -> "lon,lat,alt"; skip bad tuples
            pts = []
            for tok in re.sub(r"\s*,\s*", ",", coord_el.text).split():
                p = tok.split(",")
                if len(p) >= 2:
                    try:
                        pts.append((float(p[0]), float(p[1]), None))
                    except ValueError:
                        continue
            if len(pts) >= 2:
                segs.append(pts)
        elif ln == "Track":   # gx:Track: parallel <when> and <gx:coord> children
            whens, coords = [], []
            for c in el:
                cl = _localname(c)
                if cl == "when":
                    whens.append(c.text)
                elif cl == "coord" and c.text:
                    xy = c.text.split()
                    if len(xy) >= 2:
                        try:
                            coords.append((float(xy[0]), float(xy[1])))
                        except ValueError:
                            continue
            if len(coords) >= 2:
                times = whens + [None] * (len(coords) - len(whens))
                segs.append([(lon, lat, times[i]) for i, (lon, lat) in enumerate(coords)])
    return segs

def load_kml_tracks(data: bytes, region: RegionGeo,
                    simplify_tolerance_m: float = 15.0) -> list[Track]:
    root = etree.fromstring(data)
    out: list[Track] = []
    idx = 0
    for pts in _kml_segments(root):
        t = _make_track(pts, region, "track", idx, simplify_tolerance_m)
        if t is not None:
            out.append(t)
            idx += 1
    return out

def _kmz_to_kml(data: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        target = "doc.kml" if "doc.kml" in names else next(
            (n for n in names if n.lower().endswith(".kml")), None)
        if target is None:
            raise ValueError("no .kml inside KMZ")
        return z.read(target)

def load_tracks(data: bytes, region: RegionGeo, filename: str | None = None,
                simplify_tolerance_m: float = 15.0) -> list[Track]:
    """Auto-detect GPX / KML / KMZ and return a list[Track]."""
    if data[:4] == b"PK\x03\x04":                      # zip -> KMZ
        return load_kml_tracks(_kmz_to_kml(data), region, simplify_tolerance_m)
    # scan the WHOLE document for the first root marker (a long comment/license block
    # can push <kml past any fixed window), and pick whichever appears first
    low = data.lower()
    gpx_at = low.find(b"<gpx"); kml_at = low.find(b"<kml")
    if gpx_at != -1 and (kml_at == -1 or gpx_at < kml_at):
        return load_gpx_tracks(data, region, simplify_tolerance_m)
    if kml_at != -1:
        return load_kml_tracks(data, region, simplify_tolerance_m)
    fn = (filename or "").lower()                       # no marker -> extension
    if fn.endswith((".kml", ".kmz")):
        return load_kml_tracks(data, region, simplify_tolerance_m)
    return load_gpx_tracks(data, region, simplify_tolerance_m)
