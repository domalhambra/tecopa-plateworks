# tests/test_mockups_api.py
"""The in-app wall-art mockup endpoint (POST /api/mockups/submit): stage a finished
final as photographed objects (Plate / Frame) for social, stateless like /api/reprint.
Covers the happy-path zip, the honest 422s (not a PNG, too many combos, the MP4 share
extra), and determinism (the pack_region posture — same input, byte-identical output)."""
import io
import json
import time
import zipfile

from app import timelapse

REGION_DIR = "regions/lassen_ca"


def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _final_png(c):
    """Drive upload -> print proof -> sync final and return the poster PNG bytes."""
    j = c.post("/api/upload", files=[("files", ("a.gpx",
              open("tests/fixtures/sample.gpx", "rb").read(), "application/gpx+xml"))]).json()
    cfg = json.load(open(f"{REGION_DIR}/region.json"))
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (40_000.0 / region_w); ch = cw / 0.75          # 6x8 portrait aspect (0.75)
    x0, y0 = ovw * 0.5 - cw / 2, ovh * 0.5 - ch / 2
    # a small print (6x8) keeps the 40 km crop above the 300-dpi zoom floor
    # (10 m native x 6 in x 300 = 18 km) and renders a fast 1800x2400 final to stage.
    pr = c.post("/api/proof", data={"session_id": j["session"],
               "x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch,
               "print_w": 6, "print_h": 8})
    assert pr.status_code == 200, pr.text
    fr = c.post("/api/final", data={"session_id": j["session"], "format": "png"})
    assert fr.status_code == 200, fr.text
    return fr.content


def _await(c, jid):
    for _ in range(2400):
        s = c.get(f"/api/jobs/{jid}").json()
        if s["state"] in ("done", "error"):
            return s
        time.sleep(0.05)
    raise AssertionError("mockup job never finished")


def test_mockups_happy_path_zip():
    c = _client()
    png = _final_png(c)
    r = c.post("/api/mockups/submit",
               files={"file": ("poster.png", png, "image/png")},
               data={"variants": "plate,frame", "sizes": "1080x1080"})
    assert r.status_code == 200, r.text
    s = _await(c, r.json()["job"])
    assert s["state"] == "done", s
    z = zipfile.ZipFile(io.BytesIO(c.get(s["result"]).content))
    assert set(z.namelist()) == {"mockup_plate_1080x1080.jpg", "mockup_frame_1080x1080.jpg"}
    # each member is a real JPEG (SOI marker)
    assert z.read("mockup_plate_1080x1080.jpg")[:2] == b"\xff\xd8"


def test_mockups_not_a_png_422():
    c = _client()
    r = c.post("/api/mockups/submit",
               files={"file": ("notes.txt", b"just some text", "text/plain")},
               data={"variants": "plate", "sizes": "1080x1080"})
    assert r.status_code == 422
    assert "PNG" in r.json()["detail"]


def test_mockups_too_many_combos_422():
    c = _client()
    png = _final_png(c)
    r = c.post("/api/mockups/submit",
               files={"file": ("poster.png", png, "image/png")},
               data={"variants": "plate,frame", "sizes": "1080x1080,1080x1350,1080x566"})
    assert r.status_code == 422
    assert "too many" in r.json()["detail"].lower()


def test_mockups_bad_variant_422():
    c = _client()
    png = _final_png(c)
    r = c.post("/api/mockups/submit",
               files={"file": ("poster.png", png, "image/png")},
               data={"variants": "bogus", "sizes": "1080x1080"})
    assert r.status_code == 422
    assert "variant" in r.json()["detail"].lower()


def test_mockups_video_needs_share_extra():
    c = _client()
    png = _final_png(c)
    r = c.post("/api/mockups/submit",
               files={"file": ("poster.png", png, "image/png")},
               data={"variants": "plate", "sizes": "1080x1080", "video": "true"})
    if timelapse.MP4_AVAILABLE:
        assert r.status_code == 200, r.text
        s = _await(c, r.json()["job"])
        assert s["state"] == "done", s
        z = zipfile.ZipFile(io.BytesIO(c.get(s["result"]).content))
        assert any(n.endswith(".mp4") for n in z.namelist())
    else:
        assert r.status_code == 422
        assert "share extra" in r.json()["detail"]


def test_mockups_deterministic():
    c = _client()
    png = _final_png(c)

    def _one():
        r = c.post("/api/mockups/submit",
                   files={"file": ("poster.png", png, "image/png")},
                   data={"variants": "plate", "sizes": "1080x1080"})
        s = _await(c, r.json()["job"])
        z = zipfile.ZipFile(io.BytesIO(c.get(s["result"]).content))
        return z.read("mockup_plate_1080x1080.jpg")

    assert _one() == _one()
