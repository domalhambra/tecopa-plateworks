# tests/test_main.py
# Endpoint-level tests over the live app via FastAPI's TestClient. Lock the
# robustness/zoom-cap behaviors: clean 404/422/400 instead of opaque 500s, and
# the zoom cap judged at the FINAL print DPI rather than the proof DPI.
import io, json, os
import pytest
from PIL import Image

REGION_DIR = "regions/lassen_ca"
pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(REGION_DIR, "dem.tif")),
    reason="region assets not built; run region_prep.py")


def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _upload(c):
    with open("tests/fixtures/sample.gpx", "rb") as f:
        r = c.post("/api/upload", files={"gpx": ("sample.gpx", f.read(), "application/gpx+xml")})
    assert r.status_code == 200
    return r.json()


def _crop(j, km_wide, ar=0.75):
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (km_wide * 1000.0 / region_w); ch = cw / ar
    x0 = ovw * 0.5 - cw / 2; y0 = ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch}


def test_unknown_session_is_404_not_500():
    c = _client()
    r = c.post("/api/proof", data={"session_id": "nope", "x0": 0, "y0": 0, "x1": 9, "y1": 12,
                                   "print_w": 9, "print_h": 12})
    assert r.status_code == 404
    assert c.post("/api/final", data={"session_id": "nope"}).status_code == 404


def test_final_before_proof_is_400():
    c = _client(); j = _upload(c)
    assert c.post("/api/final", data={"session_id": j["session"]}).status_code == 400


def test_too_tight_crop_rejected_at_proof_422():
    # A 20 km crop on an 18 in print is fine at 96 dpi (11.6 m/px) but too tight at
    # the 300 dpi final (3.7 m/px). The cap is judged at the final DPI, so proof
    # must reject it -- not silently pass and crash /api/final later.
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=20.0), "print_w": 18, "print_h": 24}
    r = c.post("/api/proof", data=data)
    assert r.status_code == 422


def test_proof_then_final_happy_path():
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    r = c.post("/api/proof", data=data)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).size == (864, 1152)
    r2 = c.post("/api/final", data={"session_id": j["session"]})
    assert r2.status_code == 200
    assert Image.open(io.BytesIO(r2.content)).size == (2700, 3600)
