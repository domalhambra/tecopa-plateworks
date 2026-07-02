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
    # <rte>/<rtept> route-only files are a common exporter output (Garmin route
    # exports, planning apps); they used to parse to zero tracks and fail the whole
    # upload with a generic 400 (red-team). A planned route has no timestamps.
    for rte in gpx.routes:
        pts = [(p.longitude, p.latitude, p.time) for p in rte.points]
        t = _make_track(pts, region, rte.name or "route", idx, simplify_tolerance_m)
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
        elif ln == "Track":   # gx:Track: N <when>s then N position-matched <gx:coord>s
            whens, coords = [], []
            j = 0                       # index over ALL <gx:coord>s (valid or not)
            for c in el:
                cl = _localname(c)
                if cl == "when":
                    whens.append(c.text)
                elif cl == "coord":
                    # pair this coord with its own <when> and drop them as a unit: a
                    # malformed coord must advance the index too, or every later point
                    # inherits the previous point's time -> wrong day -> wrong hotspots
                    # (red-team V1-7). The n-th when matches the n-th coord (KML spec).
                    when = whens[j] if j < len(whens) else None
                    j += 1
                    if not c.text:
                        continue
                    xy = c.text.split()
                    if len(xy) >= 2:
                        try:
                            coords.append((float(xy[0]), float(xy[1]), when))
                        except ValueError:
                            continue
            if len(coords) >= 2:
                segs.append(coords)     # each point already carries its aligned (lon,lat,when)
    return segs

def _parse_kml_bytes(data: bytes):
    """Parse KML/XML with entity expansion + external/DTD loading disabled. On modern
    lxml the real threat is a billion-laughs entity-expansion DoS (not XXE file-read),
    so resolve_entities=False neutralizes it; huge_tree=False bounds the tree; and a
    DOCTYPE is rejected outright so no custom entities can be defined (red-team V1-6).
    A fresh parser per call keeps this thread-safe under concurrent requests."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True,
                             huge_tree=False, load_dtd=False, dtd_validation=False)
    root = etree.fromstring(data, parser=parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("XML DOCTYPE is not allowed")
    return root

def load_kml_tracks(data: bytes, region: RegionGeo,
                    simplify_tolerance_m: float = 15.0) -> list[Track]:
    root = _parse_kml_bytes(data)
    out: list[Track] = []
    idx = 0
    for pts in _kml_segments(root):
        t = _make_track(pts, region, "track", idx, simplify_tolerance_m)
        if t is not None:
            out.append(t)
            idx += 1
    return out

# KMZ is a zip; a malicious archive can be a zip-bomb or an entry flood. Bound both
# before reading anything out (red-team V1-6).
KMZ_MAX_ENTRIES = 512
KMZ_MAX_TOTAL_BYTES = 200 * 1024 * 1024     # declared decompressed size, whole archive
KMZ_MAX_MEMBER_BYTES = 64 * 1024 * 1024     # the single .kml we actually read

def _kmz_to_kml(data: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if len(infos) > KMZ_MAX_ENTRIES:
            raise ValueError("KMZ has too many entries")
        if sum(i.file_size for i in infos) > KMZ_MAX_TOTAL_BYTES:
            raise ValueError("KMZ decompressed size exceeds cap")
        names = z.namelist()
        target = "doc.kml" if "doc.kml" in names else next(
            (n for n in names if n.lower().endswith(".kml")), None)
        if target is None:
            raise ValueError("no .kml inside KMZ")
        if z.getinfo(target).file_size > KMZ_MAX_MEMBER_BYTES:
            raise ValueError("KMZ .kml member too large")
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
