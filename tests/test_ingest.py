# tests/test_ingest.py
# Unit coverage for the GPX pipeline using synthetic in-memory GPX, plus an
# end-to-end pass over the committed dummy fixture (tests/fixtures/sample.gpx,
# a stand-in for a real OnX/Avenza export until one is on hand).
import io, os, zipfile
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

def _kml_linestring(points, name="t"):
    coords = " ".join(f"{lon},{lat},0" for lon, lat in points)
    return (f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>'
            f'<name>{name}</name><LineString><coordinates>{coords}</coordinates>'
            f'</LineString></Placemark></Document></kml>').encode()

def _kml_gx_track(points, day="2024-03-02"):
    whens = "".join(f"<when>{day}T10:0{i}:00Z</when>" for i in range(len(points)))
    coords = "".join(f"<gx:coord>{lon} {lat} 0</gx:coord>" for lon, lat in points)
    return (f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<kml xmlns="http://www.opengis.net/kml/2.2" '
            f'xmlns:gx="http://www.google.com/kml/ext/2.2"><Document><Placemark>'
            f'<gx:Track>{whens}{coords}</gx:Track></Placemark></Document></kml>').encode()

def test_kml_linestring_tracks():
    from app.ingest import load_kml_tracks
    data = _kml_linestring([(-111.5, 39.30), (-111.5, 39.33), (-111.5, 39.36)])
    tracks = load_kml_tracks(data, REGION)
    assert len(tracks) == 1
    assert tracks[0].coords.shape[1] == 2
    assert (tracks[0].coords[:, 0] > 100000).all()        # reprojected to metres

def test_kml_gx_track_with_time():
    from app.ingest import load_kml_tracks
    tracks = load_kml_tracks(_kml_gx_track([(-111.5, 39.30), (-111.5, 39.34)]), REGION)
    assert len(tracks) == 1
    assert tracks[0].day == "2024-03-02"

def test_gx_track_drops_bad_coord_as_unit_keeps_time_alignment():
    # red-team V1-7: a malformed leading <gx:coord> must drop together with its own
    # <when>, so the surviving first point keeps ITS date. The old code collected the
    # two lists independently, shifting every later time up by one -> wrong day.
    from app.ingest import load_kml_tracks
    whens = ("<when>2024-03-01T10:00:00Z</when>"
             "<when>2024-03-02T10:00:00Z</when>"
             "<when>2024-03-02T10:01:00Z</when>")
    coords = ("<gx:coord>garbage</gx:coord>"           # dropped
              "<gx:coord>-111.5 39.32 0</gx:coord>"
              "<gx:coord>-111.5 39.34 0</gx:coord>")
    kml = (f'<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2" '
           f'xmlns:gx="http://www.google.com/kml/ext/2.2"><Document><Placemark>'
           f'<gx:Track>{whens}{coords}</gx:Track></Placemark></Document></kml>').encode()
    tracks = load_kml_tracks(kml, REGION)
    assert len(tracks) == 1
    assert tracks[0].day == "2024-03-02"    # second when (first coord dropped), not 03-01

def test_kml_doctype_is_rejected():
    # red-team V1-6: a DOCTYPE could define entities (billion-laughs DoS / XXE); the
    # hardened parser rejects it outright rather than expanding anything.
    import pytest
    from app.ingest import load_kml_tracks
    evil = (b'<?xml version="1.0"?>'
            b'<!DOCTYPE kml [<!ENTITY a "aaaaaaaaaa">]>'
            b'<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            b'<Placemark><LineString><coordinates>&a;</coordinates>'
            b'</LineString></Placemark></Document></kml>')
    with pytest.raises(ValueError):
        load_kml_tracks(evil, REGION)

def test_kmz_too_many_entries_rejected():
    # red-team V1-6: an entry-flood KMZ must be refused before reading anything out.
    import pytest
    from app.ingest import load_tracks, KMZ_MAX_ENTRIES
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k in range(KMZ_MAX_ENTRIES + 10):
            z.writestr(f"f{k}.txt", b"x")
    with pytest.raises(ValueError):
        load_tracks(buf.getvalue(), REGION, filename="a.kmz")

def test_kmz_unzips_and_parses():
    from app.ingest import load_tracks
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("doc.kml", _kml_linestring([(-111.5, 39.30), (-111.5, 39.34)]))
    tracks = load_tracks(buf.getvalue(), REGION, filename="a.kmz")
    assert len(tracks) == 1

def test_load_tracks_dispatches_by_content():
    from app.ingest import load_tracks
    gpx = _gpx([(-111.5, 39.30), (-111.5, 39.34)])
    kml = _kml_linestring([(-111.5, 39.30), (-111.5, 39.34)])
    assert len(load_tracks(gpx, REGION)) == 1
    assert len(load_tracks(kml, REGION)) == 1

def test_kml_with_long_preamble_routes_by_content():
    from app.ingest import load_tracks
    body = ('<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><LineString>'
            '<coordinates>-111.5,39.30,0 -111.5,39.34,0</coordinates></LineString></Placemark></Document></kml>')
    kml = b'<?xml version="1.0" encoding="UTF-8"?><!-- ' + b'x' * 600 + b' -->' + body.encode()
    assert b"<kml" not in kml[:400].lower()       # root tag is past any fixed window
    assert len(load_tracks(kml, REGION)) == 1     # whole-doc scan still routes to KML

def test_kml_malformed_coords_skipped_not_crash():
    from app.ingest import load_kml_tracks
    # spaces after commas (a real exporter quirk) must parse, not crash the file
    kml = ('<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           '<Placemark><LineString><coordinates>-111.5, 39.30, 0 -111.5, 39.34, 0</coordinates>'
           '</LineString></Placemark></Document></kml>').encode()
    tracks = load_kml_tracks(kml, REGION)
    assert len(tracks) == 1 and tracks[0].coords.shape[0] >= 2

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
