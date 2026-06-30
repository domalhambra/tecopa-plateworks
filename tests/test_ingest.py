# tests/test_ingest.py
# Unit coverage for the GPX pipeline using synthetic in-memory GPX, plus an
# end-to-end pass over the committed dummy fixture (tests/fixtures/sample.gpx,
# a stand-in for a real OnX/Avenza export until one is on hand).
import os
import numpy as np
from app.geo import RegionGeo
from app.ingest import load_gpx_tracks

# Sanpete-ish region in UTM 12N; lon -111.5 / lat 39.3 reprojects inside it.
REGION = RegionGeo(crs="EPSG:32612",
                   bounds=(400000.0, 4318000.0, 470000.0, 4385000.0),
                   overview_size=(1400, 1340))

def _gpx(points, name="t", with_time=True):
    """points: list of (lon, lat). Build a minimal valid GPX document."""
    rows = ""
    for i, (lon, lat) in enumerate(points):
        t = f"<time>2024-01-0{(i % 9) + 1}T10:0{i % 6}:00Z</time>" if with_time else ""
        rows += f'<trkpt lat="{lat}" lon="{lon}">{t}</trkpt>'
    return (f'<?xml version="1.0"?>'
            f'<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
            f'<trk><name>{name}</name><trkseg>{rows}</trkseg></trk></gpx>').encode()

def test_reprojects_to_crs_meters():
    data = _gpx([(-111.5, 39.30), (-111.5, 39.32), (-111.5, 39.34)])
    tracks = load_gpx_tracks(data, REGION)
    assert len(tracks) == 1
    c = tracks[0].coords
    assert c.shape[1] == 2 and c.shape[0] >= 2
    assert c.dtype == np.float64
    # eastings are in metres (~hundreds of thousands), not degrees
    assert c[:, 0].min() > 100000.0

def test_day_from_first_timestamp():
    tracks = load_gpx_tracks(_gpx([(-111.5, 39.30), (-111.5, 39.34)]), REGION)
    assert tracks[0].day == "2024-01-01"

def test_day_none_without_timestamps():
    tracks = load_gpx_tracks(_gpx([(-111.5, 39.30), (-111.5, 39.34)], with_time=False), REGION)
    assert tracks[0].day is None

def test_single_point_segment_skipped():
    assert load_gpx_tracks(_gpx([(-111.5, 39.30)]), REGION) == []

def test_out_of_zone_point_dropped_not_inf():
    # A point far outside UTM 12N validity reprojects to (inf, inf). It must be
    # dropped rather than emitted, or it crashes density downstream.
    data = _gpx([(-111.5, 39.30), (200.0, 95.0), (-111.5, 39.34)])
    tracks = load_gpx_tracks(data, REGION)
    for t in tracks:
        assert np.isfinite(t.coords).all()

# End-to-end over the committed Lassen County dummy fixture (UTM zone 10N).
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.gpx")
LASSEN = RegionGeo(crs="EPSG:32610",
                   bounds=(600000.0, 4470000.0, 640000.0, 4520000.0),  # unused by ingest
                   overview_size=(1400, 1750))

def test_loads_dummy_fixture():
    with open(FIXTURE, "rb") as f:
        tracks = load_gpx_tracks(f.read(), LASSEN)
    assert len(tracks) == 5                          # five dated day-trips
    days = {t.day for t in tracks}
    assert len(days) == 5 and None not in days       # each on a distinct date
    for t in tracks:
        assert t.coords.shape[1] == 2
        assert t.coords.shape[0] >= 2                 # simplified, not collapsed
        assert np.isfinite(t.coords).all()
        assert (t.coords[:, 0] > 100000.0).all()      # eastings in metres, not degrees
