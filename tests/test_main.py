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


def _file(name="a.gpx"):
    return ("files", (name, open("tests/fixtures/sample.gpx", "rb").read(), "application/gpx+xml"))

def _upload(c):
    r = c.post("/api/upload", files=[_file()])
    assert r.status_code == 200
    return r.json()


def _crop(j, km_wide, ar=0.75):
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (km_wide * 1000.0 / region_w); ch = cw / ar
    x0 = ovw * 0.5 - cw / 2; y0 = ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch}


def test_list_regions_includes_lassen():
    c = _client()
    r = c.get("/api/regions")
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()}
    assert "lassen_ca" in ids

def test_upload_with_explicit_region_binds_session():
    c = _client()
    r = c.post("/api/upload", files=[_file()], data={"region_id": "lassen_ca"})
    assert r.status_code == 200
    assert r.json()["region"] == "lassen_ca"

def test_upload_unknown_region_is_404():
    c = _client()
    r = c.post("/api/upload", files=[_file()], data={"region_id": "atlantis"})
    assert r.status_code == 404

def test_upload_multiple_files_accumulate():
    c = _client()
    r = c.post("/api/upload", files=[_file("a.gpx"), _file("b.gpx")])
    assert r.status_code == 200
    assert len(r.json()["tracks"]) == 10            # 5 + 5 combined

def test_upload_appends_to_session():
    c = _client()
    j = _upload(c)                                   # 5 tracks
    r = c.post("/api/upload", files=[_file("b.gpx")], data={"session_id": j["session"]})
    assert r.status_code == 200
    assert r.json()["session"] == j["session"]
    assert len(r.json()["tracks"]) == 10

def test_reupload_after_proof_requires_reproof():
    # accumulating tracks after a proof must invalidate the stamped spec, so the
    # final can't silently render the old subset -> /api/final 400 until re-proofed.
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 200
    c.post("/api/upload", files=[_file("b.gpx")], data={"session_id": j["session"]})
    assert c.post("/api/final", data={"session_id": j["session"]}).status_code == 400

def test_one_bad_file_does_not_fail_batch():
    c = _client()
    bad = ("files", ("broken.gpx", b"<gpx>not valid xml", "application/gpx+xml"))
    r = c.post("/api/upload", files=[_file("good.gpx"), bad])
    assert r.status_code == 200          # the good file survives; no opaque 500
    assert len(r.json()["tracks"]) == 5

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


def test_set_markers_updates_and_invalidates_spec():
    import json as _json
    c = _client(); j = _upload(c)
    # proof first so a spec is stamped, then edit markers -> final must 400 (re-proof)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 200
    r = c.post("/api/markers", data={"session_id": j["session"],
               "markers": _json.dumps([{"i": 0, "label": "Base Camp", "icon": "camp"}])})
    assert r.status_code == 200
    assert c.post("/api/final", data={"session_id": j["session"]}).status_code == 400
    # an invalid icon is dropped rather than rejected (label-only edits still apply)
    assert c.post("/api/markers", data={"session_id": j["session"],
           "markers": _json.dumps([{"i": 0, "icon": "bogus"}])}).status_code == 200

def test_photo_endpoint_validates_and_attaches():
    import io as _io
    from PIL import Image
    c = _client(); j = _upload(c)
    buf = _io.BytesIO(); Image.new("RGB", (40, 40), (10, 20, 30)).save(buf, "PNG"); buf.seek(0)
    r = c.post("/api/photo", data={"session_id": j["session"], "i": 0},
               files={"file": ("p.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200
    # a non-image is rejected 422, not silently saved
    bad = c.post("/api/photo", data={"session_id": j["session"], "i": 0},
                 files={"file": ("x.png", b"not an image", "image/png")})
    assert bad.status_code == 422

def test_markers_unknown_session_404():
    c = _client()
    assert c.post("/api/markers", data={"session_id": "nope", "markers": "[]"}).status_code == 404

def test_move_marker_invalidates_spec():
    # a hand-dragged marker must invalidate the stamped spec so the final re-proofs
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 200          # stamp a spec
    w, h = j["overview_size"]
    r = c.post("/api/markers/move", data={"session_id": j["session"], "i": 0,
               "px": w * 0.5, "py": h * 0.5})
    assert r.status_code == 200
    assert c.post("/api/final", data={"session_id": j["session"]}).status_code == 400

def test_async_final_via_job_queue():
    import time
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 200
    r = c.post("/api/final/submit", data={"session_id": j["session"]})
    assert r.status_code == 200
    jid = r.json()["job"]
    state, res = None, None
    for _ in range(600):                       # render runs on a worker thread
        s = c.get(f"/api/jobs/{jid}").json()
        state = s["state"]
        if state in ("done", "error"):
            res = s
            break
        time.sleep(0.05)
    assert state == "done", res
    out = c.get(res["result"])
    assert out.status_code == 200 and out.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(out.content)).size == (2700, 3600)

def test_async_final_before_proof_is_400():
    c = _client(); j = _upload(c)
    assert c.post("/api/final/submit", data={"session_id": j["session"]}).status_code == 400

def test_job_status_unknown_404():
    c = _client()
    assert c.get("/api/jobs/nope").status_code == 404

def test_proof_then_final_happy_path():
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    r = c.post("/api/proof", data=data)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).size == (864, 1152)
    r2 = c.post("/api/final", data={"session_id": j["session"]})
    assert r2.status_code == 200
    assert Image.open(io.BytesIO(r2.content)).size == (2700, 3600)
