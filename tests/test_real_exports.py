# tests/test_real_exports.py
"""Real-export corpus + end-to-end validation (red-team V1-5 / P0-d).

These are *representative synthetic* stand-ins for real OnX / Gaia / Strava / Avenza /
Google exports — they encode the structural quirks those apps actually emit (multi-track
and multi-segment GPX, `<wpt>`/`<Point>` waypoints mixed with tracks, Strava trackpoint
extensions, KML LineStrings inside folders, KMZ packaging, `gx:Track` with paused/repeated
fixes, big point counts, mixed dated/undated). Real files remain the gold standard — swap
them in under tests/fixtures/exports/ when on hand — but this exercises ingest -> density
-> framing end-to-end against the shapes that break naive parsers.

Coordinates sit around Susanville / Eagle Lake so they fall inside the bundled lassen_ca
region (UTM 10N); conftest.py hydrates its DEM, so the framing step has a real region.
"""
import io
import zipfile

import numpy as np
import pytest

from app import regions
from app.ingest import load_tracks
from app.density import hotspots
from app.geo import crs_to_overview_px
from app.spec import CompositionSpec, ZoomTooTightError

# A corridor of (lon, lat) anchors NNW from Susanville toward Eagle Lake's south shore.
CORRIDOR = [(-120.6530, 40.4163), (-120.6600, 40.4350), (-120.6720, 40.4600),
            (-120.6900, 40.4850), (-120.7080, 40.5100), (-120.7300, 40.5550)]


def _region():
    return regions.Region("lassen_ca")


def _densify(anchors, n_between=40, jitter=0.0, seed=0):
    """A believable recorded track: densified corridor with optional GPS jitter."""
    rng = np.random.default_rng(seed)
    pts = []
    for (lo0, la0), (lo1, la1) in zip(anchors, anchors[1:]):
        for k in range(n_between):
            f = k / n_between
            lo = lo0 + (lo1 - lo0) * f + rng.normal(0, jitter)
            la = la0 + (la1 - la0) * f + rng.normal(0, jitter)
            pts.append((lo, la))
    pts.append(anchors[-1])
    return pts


# ---- format builders (the "exports") --------------------------------------------

def _gaia_gpx(days):
    """Gaia GPS style: several dated <trk>s (one per outing) + <wpt> waypoints, one
    outing deliberately undated (day=None)."""
    trks = ""
    for i, (day, dated) in enumerate(days):
        pts = _densify(CORRIDOR, jitter=0.0002, seed=i)
        rows = ""
        for j, (lo, la) in enumerate(pts):
            t = f"<time>{day}T08:{j % 60:02d}:00Z</time>" if dated else ""
            rows += f'<trkpt lat="{la:.6f}" lon="{lo:.6f}">{t}</trkpt>'
        trks += f"<trk><name>Outing {i}</name><trkseg>{rows}</trkseg></trk>"
    wpts = ('<wpt lat="40.4163" lon="-120.6530"><name>Trailhead</name></wpt>'
            '<wpt lat="40.5550" lon="-120.7300"><name>Camp</name></wpt>')
    return (f'<?xml version="1.0"?>'
            f'<gpx version="1.1" creator="Gaia GPS" xmlns="http://www.topografix.com/GPX/1/1">'
            f'{wpts}{trks}</gpx>').encode()


def _strava_gpx():
    """Strava style: a single <trk> whose points carry <ele> + namespaced
    TrackPointExtension children (HR/cadence) that ingest must tolerate/ignore."""
    pts = _densify(CORRIDOR, jitter=0.0001, seed=7)
    rows = ""
    for j, (lo, la) in enumerate(pts):
        rows += (f'<trkpt lat="{la:.6f}" lon="{lo:.6f}"><ele>1400</ele>'
                 f'<time>2024-06-02T09:{j % 60:02d}:00Z</time>'
                 f'<extensions><gpxtpx:TrackPointExtension>'
                 f'<gpxtpx:hr>142</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions></trkpt>')
    return (f'<?xml version="1.0"?>'
            f'<gpx version="1.1" creator="StravaGPX" '
            f'xmlns="http://www.topografix.com/GPX/1/1" '
            f'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">'
            f'<trk><name>Morning Run</name><trkseg>{rows}</trkseg></trk></gpx>').encode()


def _onx_kml():
    """OnX / Avenza style KML: Point waypoints AND a LineString track, nested in
    Folders. Only the LineString should become a track; Points are ignored, not fatal."""
    coords = " ".join(f"{lo:.6f},{la:.6f},0" for lo, la in _densify(CORRIDOR, n_between=20))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        '<Folder><name>Waypoints</name>'
        '<Placemark><name>TH</name><Point><coordinates>-120.6530,40.4163,0</coordinates></Point></Placemark>'
        '<Placemark><name>Peak</name><Point><coordinates>-120.7300,40.5550,0</coordinates></Point></Placemark>'
        '</Folder>'
        '<Folder><name>Tracks</name>'
        f'<Placemark><name>Route</name><LineString><coordinates>{coords}</coordinates></LineString></Placemark>'
        '</Folder></Document></kml>').encode()


def _avenza_kmz():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", _onx_kml())
    return buf.getvalue()


def _google_gx_track_with_pauses():
    """Google/Earth gx:Track with PAUSES: fixes where the coord repeats while time
    advances (a stationary rest). Must parse, day from the first <when>."""
    pts = _densify(CORRIDOR, n_between=15)
    whens, coords = [], []
    j = 0
    for (lo, la) in pts:
        reps = 4 if j % 12 == 0 else 1                 # every so often, a pause
        for _ in range(reps):
            whens.append(f"<when>2024-06-03T07:{j % 60:02d}:00Z</when>")
            coords.append(f"<gx:coord>{lo:.6f} {la:.6f} 0</gx:coord>")
            j += 1
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2" '
        'xmlns:gx="http://www.google.com/kml/ext/2.2"><Document><Placemark><gx:Track>'
        + "".join(whens) + "".join(coords) +
        '</gx:Track></Placemark></Document></kml>').encode()


def _big_gpx(n=4000):
    """A high-frequency single track (n fixes) -> ingest must parse it fast and
    simplify it down, not choke or keep every point."""
    lo0, la0 = CORRIDOR[0]
    lo1, la1 = CORRIDOR[-1]
    rows = []
    rng = np.random.default_rng(3)
    for k in range(n):
        f = k / (n - 1)
        lo = lo0 + (lo1 - lo0) * f + rng.normal(0, 0.00005)
        la = la0 + (la1 - la0) * f + rng.normal(0, 0.00005)
        rows.append(f'<trkpt lat="{la:.6f}" lon="{lo:.6f}"><time>2024-06-04T10:00:{k % 60:02d}Z</time></trkpt>')
    return (f'<?xml version="1.0"?>'
            f'<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
            f'<trk><trkseg>{"".join(rows)}</trkseg></trk></gpx>').encode(), n


# ---- ingest correctness per export style ----------------------------------------

def test_gaia_multitrack_with_waypoints():
    reg = _region()
    days = [("2024-06-01", True), ("2024-06-05", True), ("", False)]
    tracks = load_tracks(_gaia_gpx(days), reg.geo, filename="gaia.gpx")
    assert len(tracks) == 3                                 # 3 outings; waypoints ignored
    assert {t.day for t in tracks} == {"2024-06-01", "2024-06-05", None}
    for t in tracks:
        assert t.coords.shape[1] == 2 and t.coords.shape[0] >= 2
        assert np.isfinite(t.coords).all()
        assert (t.coords[:, 0] > 100000).all()             # reprojected to UTM metres


def test_strava_extensions_are_tolerated():
    reg = _region()
    tracks = load_tracks(_strava_gpx(), reg.geo, filename="strava.gpx")
    assert len(tracks) == 1 and tracks[0].day == "2024-06-02"
    assert np.isfinite(tracks[0].coords).all()


def test_onx_kml_linestring_over_point_waypoints():
    reg = _region()
    tracks = load_tracks(_onx_kml(), reg.geo, filename="onx.kml")
    assert len(tracks) == 1                                 # only the LineString, not the Points
    assert tracks[0].coords.shape[0] >= 2


def test_avenza_kmz_roundtrip():
    reg = _region()
    tracks = load_tracks(_avenza_kmz(), reg.geo, filename="avenza.kmz")
    assert len(tracks) == 1 and np.isfinite(tracks[0].coords).all()


def test_google_gx_track_with_pauses():
    reg = _region()
    tracks = load_tracks(_google_gx_track_with_pauses(), reg.geo, filename="hist.kml")
    assert len(tracks) == 1 and tracks[0].day == "2024-06-03"


def test_big_point_count_parses_and_simplifies():
    reg = _region()
    data, n = _big_gpx(4000)
    tracks = load_tracks(data, reg.geo, filename="big.gpx")
    assert len(tracks) == 1
    assert tracks[0].coords.shape[0] < n                   # simplified, not 1:1
    assert np.isfinite(tracks[0].coords).all()


# ---- end-to-end: ingest -> hotspots -> framing ----------------------------------

def test_end_to_end_gaia_export_frames_cleanly():
    reg = _region()
    # a realistic multi-day export: repeated outings on the same corridor
    days = [(f"2024-06-0{d}", True) for d in range(1, 6)]
    tracks = load_tracks(_gaia_gpx(days), reg.geo, filename="gaia.gpx")
    assert len(tracks) == 5

    spots = hotspots(tracks, region_bounds=reg.cfg["bounds"])
    assert spots, "distinct-day corridor should yield at least one hotspot"
    b = reg.cfg["bounds"]
    for s in spots:
        assert b[0] <= s["x"] <= b[2] and b[1] <= s["y"] <= b[3]   # in region bounds
    # the busiest hotspot reflects multiple distinct days visiting the corridor
    assert max(s["weight"] for s in spots) >= 2

    # framing: the starter crop must be a valid ordered box inside the overview...
    from app.geo import starter_crop
    tpx = [[crs_to_overview_px(reg.geo, x, y) for x, y in t.coords] for t in tracks]
    ovw, ovh = reg.cfg["overview_size"]
    x0, y0, x1, y1 = starter_crop(reg.geo, tpx, 18, 24,
                                  native_resolution_m=reg.cfg["native_resolution_m"])
    assert x0 < x1 and y0 < y1
    assert -1 <= x0 and x1 <= ovw + 1 and -1 <= y0 and y1 <= ovh + 1

    # ...and it must clear the zoom cap at the final print DPI (floor-safe framing)
    from app.geo import crop_px_to_crs_window
    crop = crop_px_to_crs_window(reg.geo, x0, y0, x1, y1)
    spec = CompositionSpec(region_id=reg.id, crs=reg.cfg["crs"], crop=crop,
                           print_w_in=18, print_h_in=24,
                           native_resolution_m=reg.cfg["native_resolution_m"],
                           tracks=[t.coords for t in tracks], hotspots=spots, seed=7)
    spec.validate(300)                                     # raises ZoomTooTightError if too tight


def test_mixed_batch_upload_accumulates_all_styles():
    # dropping several exports of different formats at once must all parse (the batch
    # tolerance in main._load_all), matching a real "here's everything I have" upload.
    reg = _region()
    blobs = [
        (_gaia_gpx([("2024-06-01", True)]), "gaia.gpx"),
        (_strava_gpx(), "strava.gpx"),
        (_onx_kml(), "onx.kml"),
        (_avenza_kmz(), "avenza.kmz"),
    ]
    total = 0
    for data, fn in blobs:
        total += len(load_tracks(data, reg.geo, filename=fn))
    assert total == 4                                      # 1 + 1 + 1 + 1
