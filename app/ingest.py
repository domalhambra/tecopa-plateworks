# app/ingest.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import math
import re
import zipfile
import numpy as np
import gpxpy
from lxml import etree
from shapely.geometry import LineString
from app.geo import RegionGeo, lonlat_to_crs

# Waypoints: a hostile KML can carry thousands of <Placemark>s; bound what rides into
# the marker layer (loud boundaries, like the KMZ caps below).
MAX_WAYPOINTS = 200

@dataclass
class Track:
    track_id: str
    coords: np.ndarray   # (N, 2) float64, region CRS meters
    day: str | None      # ISO date if timestamps exist, else None
    # Journey Light (v1.9): the timing the still-poster path discards but the sun and the
    # films need. t0/t1 are the first/last known UTC timestamps (ISO-19); lonlat is the
    # (lon, lat) centroid (geographic, for solar position). coords_t is per-SIMPLIFIED-
    # VERTEX unix-seconds (NaN where unknown), aligned 1:1 to `coords` for the film's
    # time-true reveal -- Douglas-Peucker keeps a subset of the original vertices, so each
    # survivor carries its own real time. summit_t/summit_ele are the timestamp + elevation
    # of the FULL-resolution highest point (found before simplification, so an interior
    # peak dropped by DP still lights the poster) -- the "summit light" default moment. All
    # default None so every existing caller and persisted row keeps working.
    t0: str | None = None
    t1: str | None = None
    lonlat: tuple | None = None
    coords_t: np.ndarray | None = None
    summit_t: str | None = None
    summit_ele: float | None = None

def _to_unix(t) -> float:
    """A gpxpy datetime or an ISO string (KML <when>) -> unix seconds UTC, or NaN."""
    if t is None:
        return float("nan")
    if isinstance(t, datetime):
        dt = t if t.tzinfo is not None else t.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    s = str(t).strip()
    if not s:
        return float("nan")
    try:
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        dt = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return float("nan")

def _iso19(unix: float) -> str:
    return datetime.fromtimestamp(unix, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

def _make_track(pts, region: RegionGeo, name, idx, simplify_tolerance_m,
                stats: dict | None = None):
    """Build one Track from points. pts: list of (lon, lat, time, ele) where time is a
    datetime / ISO string / None and ele is a float / None. Reproject -> drop non-finite
    -> simplify, then carry each surviving vertex's real time + elevation.
    `stats` (when given) accumulates counters across calls -- today just
    `dropped_points`, the non-finite drops -- so upload can NAME the loss instead
    of swallowing it (loud boundaries)."""
    pts = [p for p in pts if p[0] is not None and p[1] is not None]
    if len(pts) < 2:
        return None
    xy = np.array([lonlat_to_crs(region, p[0], p[1]) for p in pts])
    lonlat_in = np.array([(p[0], p[1]) for p in pts], dtype=float)
    tsec = np.array([_to_unix(p[2] if len(p) > 2 else None) for p in pts])
    ele = np.array([float(p[3]) if len(p) > 3 and p[3] is not None else float("nan")
                    for p in pts])
    # Points outside the region's projection validity reproject to (inf, inf).
    # Drop them so a single off-region upload can't poison the track (and later
    # crash density's int() cast with OverflowError). Counted, never silent.
    before = xy.shape[0]
    mask = np.isfinite(xy).all(axis=1)
    xy = xy[mask]
    tsec, ele, lonlat_in = tsec[mask], ele[mask], lonlat_in[mask]
    dropped = int(before - xy.shape[0])
    if stats is not None:
        stats["dropped_points"] = stats.get("dropped_points", 0) + dropped
    if xy.shape[0] < 2:
        # the non-finite drops orphaned this journey: a lone finite survivor can't
        # draw a line, so it is lost too -- count it, or dropped_points under-reports
        # the loss and a whole journey vanishes half-counted (the exact silent
        # swallow the counter exists to eliminate).
        if stats is not None and dropped:
            stats["dropped_points"] += int(xy.shape[0])
        return None
    line = LineString(xy).simplify(simplify_tolerance_m, preserve_topology=False)
    coords = np.asarray(line.coords)
    if coords.shape[0] < 2:
        return None
    # Recover per-vertex time for the SURVIVING (simplified) vertices: DP keeps exact
    # input coordinates, so match each output vertex back to its input row.
    idx_of = {}
    for i in range(xy.shape[0]):
        idx_of.setdefault((xy[i, 0], xy[i, 1]), i)
    ct = np.full(coords.shape[0], np.nan)
    for j in range(coords.shape[0]):
        i = idx_of.get((coords[j, 0], coords[j, 1]))
        if i is not None:
            ct[j] = tsec[i]
    have_t = np.isfinite(tsec).any()
    t0 = _iso19(float(np.nanmin(tsec))) if have_t else None
    t1 = _iso19(float(np.nanmax(tsec))) if have_t else None
    day = t0[:10] if t0 is not None else None
    lonlat = (float(lonlat_in[:, 0].mean()), float(lonlat_in[:, 1].mean()))
    # Summit light: the highest FULL-resolution point that also carries a time (found
    # pre-simplification, so a sharp interior peak DP would drop still resolves the sun).
    summit_t = summit_ele = None
    both = np.isfinite(ele) & np.isfinite(tsec)
    if both.any():
        si = int(np.argmax(np.where(both, ele, -np.inf)))
        summit_t, summit_ele = _iso19(float(tsec[si])), float(ele[si])
    return Track(track_id=f"{name or 'track'}-{idx}", coords=coords, day=day,
                 t0=t0, t1=t1, lonlat=lonlat,
                 coords_t=ct if have_t else None,
                 summit_t=summit_t, summit_ele=summit_ele)

def load_gpx_tracks(data: bytes, region: RegionGeo,
                    simplify_tolerance_m: float = 15.0,
                    stats: dict | None = None) -> list[Track]:
    gpx = gpxpy.parse(io.BytesIO(data))
    out: list[Track] = []
    idx = 0
    for trk in gpx.tracks:
        for seg in trk.segments:
            pts = [(p.longitude, p.latitude, p.time, p.elevation) for p in seg.points]
            t = _make_track(pts, region, trk.name, idx, simplify_tolerance_m, stats)
            if t is not None:
                out.append(t)
                idx += 1
    # <rte>/<rtept> route-only files are a common exporter output (Garmin route
    # exports, planning apps); they used to parse to zero tracks and fail the whole
    # upload with a generic 400 (red-team). A planned route has no timestamps.
    for rte in gpx.routes:
        pts = [(p.longitude, p.latitude, p.time, p.elevation) for p in rte.points]
        t = _make_track(pts, region, rte.name or "route", idx, simplify_tolerance_m,
                        stats)
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
                        ele = float(p[2]) if len(p) >= 3 else None
                        pts.append((float(p[0]), float(p[1]), None, ele))
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
                            ele = float(xy[2]) if len(xy) >= 3 else None
                            coords.append((float(xy[0]), float(xy[1]), when, ele))
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
                    simplify_tolerance_m: float = 15.0,
                    stats: dict | None = None) -> list[Track]:
    root = _parse_kml_bytes(data)
    out: list[Track] = []
    idx = 0
    for pts in _kml_segments(root):
        t = _make_track(pts, region, "track", idx, simplify_tolerance_m, stats)
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
                simplify_tolerance_m: float = 15.0,
                stats: dict | None = None) -> list[Track]:
    """Auto-detect GPX / KML / KMZ and return a list[Track]. `stats` (optional)
    accumulates ingest counters (see _make_track); the default None keeps every
    existing caller byte-identical."""
    if data[:4] == b"PK\x03\x04":                      # zip -> KMZ
        return load_kml_tracks(_kmz_to_kml(data), region, simplify_tolerance_m, stats)
    # scan the WHOLE document for the first root marker (a long comment/license block
    # can push <kml past any fixed window), and pick whichever appears first
    low = data.lower()
    gpx_at = low.find(b"<gpx"); kml_at = low.find(b"<kml")
    if gpx_at != -1 and (kml_at == -1 or gpx_at < kml_at):
        return load_gpx_tracks(data, region, simplify_tolerance_m, stats)
    if kml_at != -1:
        return load_kml_tracks(data, region, simplify_tolerance_m, stats)
    fn = (filename or "").lower()                       # no marker -> extension
    if fn.endswith((".kml", ".kmz")):
        return load_kml_tracks(data, region, simplify_tolerance_m, stats)
    return load_gpx_tracks(data, region, simplify_tolerance_m, stats)


# Map a GPX/KML symbol string to one of the app's vector icons (VALID_ICONS in main.py);
# default "flag" -- a waypoint is a marked point. Keyword match, case-insensitive.
_SYM_ICON = (("summit", "peak"), ("peak", "peak"), ("mountain", "peak"),
             ("camp", "camp"), ("tent", "camp"), ("shelter", "camp"),
             ("water", "water"), ("spring", "water"), ("river", "water"),
             ("photo", "camera"), ("camera", "camera"), ("scenic", "camera"),
             ("view", "camera"), ("star", "star"))

def _sym_to_icon(sym: str | None) -> str:
    s = (sym or "").lower()
    for key, icon in _SYM_ICON:
        if key in s:
            return icon
    return "flag"

def _waypoint_hotspot(region, lon, lat, name, sym):
    x, y = lonlat_to_crs(region, lon, lat)
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    label = (name or "").strip()[:60]
    # weight seeds the marker's presence; waypoints are explicit, so give them a solid
    # (but not dominating) default so they read as pins in the marker layer.
    return {"x": float(x), "y": float(y), "weight": 3,
            "label": label, "icon": _sym_to_icon(sym)}

def load_waypoints(data: bytes, region: RegionGeo,
                   filename: str | None = None) -> list[dict]:
    """Named user waypoints (GPX <wpt>, KML <Placemark> points) -> hotspot-shaped dicts
    (the existing marker layer's shape: {x,y,weight,label,icon}). Auto-detects format
    like load_tracks; bounded by MAX_WAYPOINTS. Off-region points are dropped. Returns []
    when the file carries none (the common case), so the upload path is unchanged."""
    out: list[dict] = []
    is_kmz = data[:4] == b"PK\x03\x04"
    low = data.lower()
    fn = (filename or "").lower()
    is_kml = (is_kmz or fn.endswith((".kml", ".kmz"))
              or (low.find(b"<kml") != -1
                  and (low.find(b"<gpx") == -1 or low.find(b"<kml") < low.find(b"<gpx"))))
    if is_kml:
        root = _parse_kml_bytes(_kmz_to_kml(data) if is_kmz else data)
        for el in root.iter():
            if _localname(el) != "Placemark":
                continue
            pt = next((d for d in el.iter() if _localname(d) == "Point"), None)
            if pt is None:
                continue
            coord_el = next((c for c in pt if _localname(c) == "coordinates"), None)
            name_el = next((n for n in el if _localname(n) == "name"), None)
            if coord_el is None or not coord_el.text:
                continue
            tok = re.sub(r"\s*,\s*", ",", coord_el.text).strip().split()[0].split(",")
            if len(tok) < 2:
                continue
            try:
                lon, lat = float(tok[0]), float(tok[1])
            except ValueError:
                continue
            hs = _waypoint_hotspot(region, lon, lat,
                                   name_el.text if name_el is not None else "", None)
            if hs is not None:
                out.append(hs)
            if len(out) >= MAX_WAYPOINTS:
                break
        return out
    gpx = gpxpy.parse(io.BytesIO(data))
    for w in gpx.waypoints:
        hs = _waypoint_hotspot(region, w.longitude, w.latitude, w.name, w.symbol)
        if hs is not None:
            out.append(hs)
        if len(out) >= MAX_WAYPOINTS:
            break
    return out


def lonlat_extent(payloads) -> dict:
    """Raw lon/lat bounding box + a name prefill across (data, filename) payloads --
    the no-region parse behind /api/regions/plan. Malformed files are skipped, not
    fatal: the caller reports 'no points' only when NOTHING parsed. The name prefill
    is the first GPX <name> found (file-level, else first track's)."""
    import gpxpy
    w = s = float("inf")
    e = n = float("-inf")
    name = ""
    for data, filename in payloads:
        fn = (filename or "").lower()
        try:
            if fn.endswith(".kmz"):
                segs = _kml_segments(_parse_kml_bytes(_kmz_to_kml(data)))
                pts = [(p[0], p[1]) for seg in segs for p in seg]
            elif fn.endswith(".kml"):
                segs = _kml_segments(_parse_kml_bytes(data))
                pts = [(p[0], p[1]) for seg in segs for p in seg]
            else:
                g = gpxpy.parse(data.decode("utf-8", errors="replace"))
                if not name:
                    name = (g.name or next((t.name for t in g.tracks if t.name), "") or "").strip()
                pts = [(pt.longitude, pt.latitude)
                       for t in g.tracks for sg in t.segments for pt in sg.points]
        except Exception:
            continue                      # one bad file must not sink the batch
        for lon, lat in pts:
            if lon < w: w = lon
            if lon > e: e = lon
            if lat < s: s = lat
            if lat > n: n = lat
    if not (w <= e and s <= n):
        return {"bbox": None, "name": name}
    return {"bbox": (w, s, e, n), "name": name}
