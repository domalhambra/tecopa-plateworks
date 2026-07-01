# tests/test_region_recovery.py
# Cross-region auto-recovery: when the operator pre-picks the wrong region but the
# dropped tracks clearly belong to another built region, the upload switches to the
# region that actually holds them and flags `recovered` so the client can say so.
# Pure region-resolution + hotspots (no DEM), so this runs on a fresh clone.
from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app)


def _gpx(points):   # points: list of (lon, lat)
    trkpts = "".join(f'<trkpt lat="{lat}" lon="{lon}"></trkpt>' for lon, lat in points)
    return (f'<?xml version="1.0"?>'
            f'<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">'
            f'<trk><trkseg>{trkpts}</trkseg></trk></gpx>').encode()


# a track squarely inside lassen_ca and OUTSIDE susanville_reno
_LASSEN_ONLY = _gpx([(-120.95, 40.78), (-120.93, 40.80), (-120.91, 40.82)])


def test_upload_recovers_when_region_is_wrong():
    c = _client()
    r = c.post("/api/upload",
               files=[("files", ("t.gpx", _LASSEN_ONLY, "application/gpx+xml"))],
               data={"region_id": "susanville_reno"})   # wrong region on purpose
    assert r.status_code == 200
    j = r.json()
    assert j["region"] == "lassen_ca"      # switched to the region that holds the tracks
    assert j["recovered"] is True
    assert len(j["tracks"]) >= 1


def test_upload_honors_correct_region_without_recovery():
    c = _client()
    r = c.post("/api/upload",
               files=[("files", ("t.gpx", _LASSEN_ONLY, "application/gpx+xml"))],
               data={"region_id": "lassen_ca"})          # correct region
    assert r.status_code == 200
    j = r.json()
    assert j["region"] == "lassen_ca"
    assert j["recovered"] is False


def test_upload_autodetect_is_not_flagged_as_recovery():
    # no region_id at all -> plain auto-detect, which is not a "recovery"
    c = _client()
    r = c.post("/api/upload",
               files=[("files", ("t.gpx", _LASSEN_ONLY, "application/gpx+xml"))])
    assert r.status_code == 200
    j = r.json()
    assert j["region"] == "lassen_ca"
    assert j["recovered"] is False
