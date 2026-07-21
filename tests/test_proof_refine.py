# tests/test_proof_refine.py
# Progressive proof: /api/proof stays the instant PROOF_DPI draft; /api/proof/refine
# re-renders the SAME stamped spec sharper on its own queue. Lock the gates (404/400),
# the geometry (refine pixels = sheet inches x _refine_dpi, minus the bleed band),
# and the dpi policy (prints cap at REFINE_DPI_CAP under REFINE_MAX_PIXELS; wallpapers
# refine to native ppi; a draft already near-native skips).
import json
import os
import time

from test_main import _client, _upload, _crop


def _proof(c, j, **overrides):
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0),
            "print_w": 9, "print_h": 12, **overrides}
    r = c.post("/api/proof", data=data)
    assert r.status_code == 200
    return data


def _wait_done(c, jid, timeout=120.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = c.get(f"/api/proof/refine/{jid}").json()
        if s["state"] == "done":
            return s
        assert s["state"] in ("queued", "running"), s["error"]
        time.sleep(0.2)
    raise AssertionError("refine job did not finish in time")


def test_refine_unknown_session_is_404():
    c = _client()
    assert c.post("/api/proof/refine", data={"session_id": "nope"}).status_code == 404


def test_refine_before_proof_is_400():
    c = _client(); j = _upload(c)
    assert c.post("/api/proof/refine",
                  data={"session_id": j["session"]}).status_code == 400


def test_refine_renders_the_stamped_sheet_at_refine_dpi():
    from PIL import Image
    import io
    from app.main import _refine_dpi
    c = _client(); j = _upload(c)
    _proof(c, j)
    r = c.post("/api/proof/refine", data={"session_id": j["session"]})
    assert r.status_code == 200
    body = r.json()
    assert body["skip"] is False
    s = _wait_done(c, body["job"])
    png = c.get(s["result"])
    assert png.status_code == 200
    img = Image.open(io.BytesIO(png.content))
    # a 9x12 print refines at the flat cap (its pixel budget allows far more)
    assert body["dpi"] == 200
    assert img.size == (round(9 * 200), round(12 * 200))


def test_refine_crops_the_bleed_band_like_the_draft():
    from PIL import Image
    import io
    c = _client(); j = _upload(c)
    _proof(c, j, bleed=0.25)
    body = c.post("/api/proof/refine", data={"session_id": j["session"]}).json()
    s = _wait_done(c, body["job"])
    img = Image.open(io.BytesIO(c.get(s["result"]).content))
    # the preview is judged at the trim line: the bleed band never reaches the client
    dpi = body["dpi"]
    b = round(0.25 * dpi)
    assert img.size == (round((9 + 0.5) * dpi) - 2 * b,
                        round((12 + 0.5) * dpi) - 2 * b)


def test_refine_after_reproof_reflects_the_new_spec():
    from PIL import Image
    import io
    c = _client(); j = _upload(c)
    _proof(c, j)
    # re-proof restamps a different sheet (wider crop: the zoom cap is judged at the
    # final dpi, and 30 km over 12 in would be finer than the plate's 10 m/px floor)
    _proof(c, j, print_w=12, print_h=16, **_crop(j, km_wide=45.0))
    body = c.post("/api/proof/refine", data={"session_id": j["session"]}).json()
    s = _wait_done(c, body["job"])
    img = Image.open(io.BytesIO(c.get(s["result"]).content))
    assert img.size == (round(12 * body["dpi"]), round(16 * body["dpi"]))


def test_refine_dpi_policy():
    from types import SimpleNamespace
    from app.main import _refine_dpi, REFINE_MAX_PIXELS

    def spec(w, h, kind="print", final=300.0, bleed=0.0):
        return SimpleNamespace(print_w_in=w, print_h_in=h, bleed_in=bleed,
                               output_kind=kind, final_dpi=lambda: final)

    # prints sit at the flat cap while the pixel budget allows it...
    assert _refine_dpi(spec(18, 24)) == 200
    d = _refine_dpi(spec(24, 36))
    assert d == 200 and 24 * d * 36 * d <= REFINE_MAX_PIXELS
    # ...and a hypothetical wall-sized sheet is pixel-bounded, never budget-busting
    big = _refine_dpi(spec(48, 72))
    assert 48 * big * 72 * big <= REFINE_MAX_PIXELS
    # a wallpaper refines to its native ppi (the print cap must not blur a phone)
    phone = spec(1179 / 460, 2556 / 460, kind="wallpaper", final=460.0)
    assert _refine_dpi(phone) == 460
    # jobs endpoints: an unknown refine id is an honest 404
    c = _client()
    assert c.get("/api/proof/refine/deadbeef").status_code == 404
    assert c.get("/api/proof/refine/deadbeef/result").status_code == 404


def test_wallpaper_refine_reaches_native_device_pixels():
    # the print cap must not blur a screen: a wallpaper's refine IS its final pixels
    from PIL import Image
    import io
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0, ar=1.0),
            "output": "wallpaper", "wallpaper_preset": "custom",
            "custom_px_w": 960, "custom_px_h": 960, "custom_ppi": 96}
    assert c.post("/api/proof", data=data).status_code == 200
    body = c.post("/api/proof/refine", data={"session_id": j["session"]}).json()
    assert body["skip"] is False and body["dpi"] == 96
    s = _wait_done(c, body["job"])
    img = Image.open(io.BytesIO(c.get(s["result"]).content))
    assert img.size == (960, 960)
