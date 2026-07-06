# tests/test_wallpaper_api.py
"""The wallpaper API surface: proof/final render a device's exact native pixels and
carry its ppi + manifest; PDF is refused (wallpapers are screen deliverables); the
bundle endpoint re-targets the accepted composition at several devices into one zip;
and a wallpaper PNG is stateless-reprintable, including a frozen fixture that pins
the forever-contract for wallpaper files (like manifest_v1.json does for prints)."""
import io
import json
import time
import zipfile
import numpy as np
from PIL import Image

from app import provenance, wallpaper

REGION_DIR = "regions/lassen_ca"


def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

def _file(name="a.gpx"):
    return ("files", (name, open("tests/fixtures/sample.gpx", "rb").read(),
                      "application/gpx+xml"))

def _upload(c):
    j = c.post("/api/upload", files=[_file()]).json()
    assert "session" in j, j
    return j

def _crop(j, km_wide=40.0, ar=0.75):
    """A centered crop in overview px at width/height aspect `ar` (like the aim UI)."""
    cfg = json.load(open(f"{REGION_DIR}/region.json"))
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (km_wide * 1000.0 / region_w); ch = cw / ar
    x0 = ovw * 0.5 - cw / 2; y0 = ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch}

def _wallpaper_proof(c, j, preset_id="desktop_fhd", km_wide=40.0):
    p = wallpaper.PRESETS[preset_id]
    return c.post("/api/proof", data={
        "session_id": j["session"], **_crop(j, km_wide=km_wide, ar=p.aspect),
        "output": "wallpaper", "wallpaper_preset": preset_id})

def _await_job(c, jid):
    for _ in range(2400):                      # generous budget for a CI runner
        s = c.get(f"/api/jobs/{jid}").json()
        if s["state"] in ("done", "error"):
            return s
        time.sleep(0.05)
    raise AssertionError("job never finished")


def test_presets_endpoint_serves_the_table():
    c = _client()
    got = c.get("/api/wallpapers/presets").json()
    assert {p["id"] for p in got} == set(wallpaper.PRESETS)
    four_k = next(p for p in got if p["id"] == "desktop_4k")
    assert four_k["px"] == [3840, 2160] and four_k["ppi"] == 163.0


def test_wallpaper_proof_then_final_is_exact_native_pixels():
    c = _client(); j = _upload(c)
    r = _wallpaper_proof(c, j, "desktop_fhd")
    assert r.status_code == 200, r.text
    # the proof keeps the print path's 32% preview ratio: 1920 * 96/300 = 614 px wide
    pw, ph = Image.open(io.BytesIO(r.content)).size
    assert abs(pw / ph - 1920 / 1080) < 0.01 and pw < 1920
    png = c.post("/api/final", data={"session_id": j["session"]}).content
    img = Image.open(io.BytesIO(png))
    assert img.size == (1920, 1080)                       # the device's native pixels
    assert round(img.info["dpi"][0]) == 92                # the glass's ppi, not 300
    m = provenance.extract(png)
    assert m and m["spec"]["output_kind"] == "wallpaper"
    assert m["spec"]["screen_ppi"] == 92.0 and m["spec"]["keyline"] is False


def test_wallpaper_final_refuses_pdf():
    c = _client(); j = _upload(c)
    assert _wallpaper_proof(c, j).status_code == 200
    for ep in ("/api/final", "/api/final/submit"):
        r = c.post(ep, data={"session_id": j["session"], "format": "pdf"})
        assert r.status_code == 422 and "PNG" in r.json()["detail"], ep


def test_unknown_preset_is_a_422():
    c = _client(); j = _upload(c)
    r = c.post("/api/proof", data={"session_id": j["session"], **_crop(j),
                                   "output": "wallpaper", "wallpaper_preset": "vision_pro"})
    assert r.status_code == 422 and "preset" in r.json()["detail"]


def test_unknown_output_is_a_422_not_a_silent_print():
    # 'Wallpaper' / 'screen' must not quietly fall into the print branch and stamp a
    # 300-dpi poster the client never asked for (same honest-422 pattern as photo_style)
    c = _client(); j = _upload(c)
    r = c.post("/api/proof", data={"session_id": j["session"], **_crop(j),
                                   "output": "Wallpaper", "wallpaper_preset": "iphone"})
    assert r.status_code == 422 and "output" in r.json()["detail"]


def test_bad_format_is_422_even_without_a_session():
    # format membership is checked before the session gate (the pre-wallpaper
    # contract): a bad format never masquerades as a session problem
    c = _client()
    r = c.post("/api/final", data={"session_id": "nope", "format": "tiff"})
    assert r.status_code == 422 and "format" in r.json()["detail"]


def test_bundle_renders_each_device_at_native_pixels():
    c = _client(); j = _upload(c)
    # accept a normal print proof first (the bundle re-targets the ACCEPTED picture)
    r = c.post("/api/proof", data={"session_id": j["session"], **_crop(j),
                                   "print_w": 9, "print_h": 12})
    assert r.status_code == 200, r.text
    # the repeated id is deduped (two identical arcnames in one zip would collide)
    sub = c.post("/api/wallpapers/submit",
                 data={"session_id": j["session"],
                       "presets": "desktop_fhd,iphone,desktop_fhd"})
    assert sub.status_code == 200, sub.text
    body = sub.json()
    assert body["count"] == 2 and body["skipped"] == []
    s = _await_job(c, body["job"])
    assert s["state"] == "done", s
    out = c.get(s["result"])
    assert out.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(out.content))
    names = sorted(z.namelist())
    assert names == ["trailprint_lassen_ca_desktop_fhd_1920x1080.png",
                     "trailprint_lassen_ca_iphone_1179x2556.png"]
    for name, px in zip(names, [(1920, 1080), (1179, 2556)]):
        data = z.read(name)
        assert Image.open(io.BytesIO(data)).size == px
        m = provenance.extract(data)                       # each file self-describing
        assert m and m["spec"]["output_kind"] == "wallpaper"


def test_bundle_requires_a_stamped_proof_and_at_least_one_preset():
    c = _client(); j = _upload(c)
    r = c.post("/api/wallpapers/submit",
               data={"session_id": j["session"], "presets": "iphone"})
    assert r.status_code == 400                            # approve a proof first
    c.post("/api/proof", data={"session_id": j["session"], **_crop(j),
                               "print_w": 9, "print_h": 12})
    r = c.post("/api/wallpapers/submit", data={"session_id": j["session"], "presets": " "})
    assert r.status_code == 422


def test_wallpaper_reprint_is_pixel_identical():
    c = _client(); j = _upload(c)
    assert _wallpaper_proof(c, j, "desktop_fhd").status_code == 200
    final_png = c.post("/api/final", data={"session_id": j["session"]}).content
    r = c.post("/api/reprint", files={"file": ("wp.png", final_png, "image/png")})
    assert r.status_code == 200, r.text
    a = np.asarray(Image.open(io.BytesIO(final_png)).convert("RGB"))
    b = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"))
    assert a.shape == b.shape and np.array_equal(a, b)
    # a wallpaper reprint is PNG-only, like every wallpaper deliverable
    r = c.post("/api/reprint", files={"file": ("wp.png", final_png, "image/png")},
               data={"format": "pdf"})
    assert r.status_code == 422


def test_frozen_wallpaper_manifest_loads_validates_and_reprints():
    # the forever-contract, wallpaper edition: a wallpaper PNG a client saved the day
    # this shipped must still re-render at its device's exact native pixels.
    m = json.load(open("tests/fixtures/manifest_wallpaper_v1.json"))
    spec = provenance.manifest_to_spec(m)
    assert spec.output_kind == "wallpaper" and spec.screen_ppi == 92.0
    spec.validate(spec.final_dpi())
    img = Image.new("RGB", (16, 16), (20, 20, 20))
    buf = io.BytesIO(); img.save(buf, "PNG", pnginfo=provenance.manifest_pnginfo(m))
    c = _client()
    r = c.post("/api/reprint", files={"file": ("wp_v1.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    assert Image.open(io.BytesIO(r.content)).size == (1920, 1080)
