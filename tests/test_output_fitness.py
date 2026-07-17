# tests/test_output_fitness.py
"""Output-fitness closures (red-team 2026-07-17): the claims about the three
deliverable surfaces that were engineered but never pinned, plus the new seams.

- custom wallpaper devices (the escape hatch): proof -> final at EXACT typed pixels,
  honest 422s, and a continued custom wallpaper restoring as the same custom device;
- social presets: the 9:16 Reel frame reachable end-to-end as a film;
- the bottom keep-out band (bottom_clear_frac), the clock band's twin;
- the bundle's partial-skip path (SKIPPED.txt + survivors; all-fail = a real error)
  and its pre-enqueue `skipped`/`fitted` reporting;
- the MP4 twin's BT.709 tags and the WebP twin's sRGB profile -- both called
  load-bearing in-code, neither previously read back by any test."""
import io
import json
import os
import zipfile

import numpy as np
import pytest
from PIL import Image

from app import provenance, render, timelapse, wallpaper
from app.spec import CompositionSpec, SpecError

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
    cfg = json.load(open(f"{REGION_DIR}/region.json"))
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (km_wide * 1000.0 / region_w); ch = cw / ar
    x0 = ovw * 0.5 - cw / 2; y0 = ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch}

def _await_job(c, jid):
    import time
    for _ in range(2400):
        s = c.get(f"/api/jobs/{jid}").json()
        if s["state"] in ("done", "error"):
            return s
        time.sleep(0.05)
    raise AssertionError("job never finished")


# ---- custom devices: the escape hatch keeps the exact-native-pixels promise ----

def test_upload_serves_the_final_dpi():
    # the client's zoom-floor math keys on this instead of a hardcoded 300
    c = _client()
    assert _upload(c)["final_dpi"] == 300


def test_custom_device_proof_final_continue_roundtrip():
    c = _client(); j = _upload(c)
    r = c.post("/api/proof", data={
        "session_id": j["session"], **_crop(j, ar=800 / 600),
        "output": "wallpaper", "wallpaper_preset": "custom",
        "custom_px_w": 800, "custom_px_h": 600, "custom_ppi": 120})
    assert r.status_code == 200, r.text
    png = c.post("/api/final", data={"session_id": j["session"]}).content
    img = Image.open(io.BytesIO(png))
    assert img.size == (800, 600)                    # the TYPED device's native pixels
    assert round(img.info["dpi"][0]) == 120          # ...at the typed ppi
    assert img.info.get("icc_profile")               # sRGB rides wallpapers too
    m = provenance.extract(png)
    assert m["spec"]["output_kind"] == "wallpaper" and m["spec"]["screen_ppi"] == 120.0
    # a continued custom wallpaper restores as the SAME custom device, not a print
    r2 = c.post("/api/continue", files={"file": ("wp.png", png, "image/png")})
    assert r2.status_code == 200, r2.text
    pre = r2.json()["prefill"]
    assert pre["output"] == "wallpaper" and pre["wallpaper_preset"] == "custom"
    assert pre["custom_device"] == {"px": [800, 600], "ppi": 120.0}
    assert r2.json()["final_dpi"] == 300


def test_custom_device_422s_name_the_real_problem():
    c = _client(); j = _upload(c)
    base = {"session_id": j["session"], **_crop(j, ar=4 / 3),
            "output": "wallpaper", "wallpaper_preset": "custom"}
    r = c.post("/api/proof", data=base)                       # fields missing entirely
    assert r.status_code == 422 and "custom_px_w" in r.json()["detail"]
    r = c.post("/api/proof", data={**base, "custom_px_w": 100, "custom_px_h": 600,
                                   "custom_ppi": 120})        # pixels out of bounds
    assert r.status_code == 422 and "between" in r.json()["detail"]
    r = c.post("/api/proof", data={**base, "custom_px_w": 800, "custom_px_h": 600,
                                   "custom_ppi": 5000})       # ppi outside the glass range
    assert r.status_code == 422 and "screen_ppi" in r.json()["detail"]
    # the bundle stays table-only: 'custom' in a preset list is an honest 422
    c.post("/api/proof", data={"session_id": j["session"], **_crop(j),
                               "print_w": 9, "print_h": 12})
    r = c.post("/api/wallpapers/submit",
               data={"session_id": j["session"], "presets": "custom"})
    assert r.status_code == 422 and "custom" in r.json()["detail"]


# ---- social presets: the 9:16 frame is a first-class film target ----

def test_reel_preset_films_at_reel_pixels():
    # the headline social fix: /api/timelapse/submit can cut the film at the
    # Reels/Stories/Shorts frame (1080x1920) instead of a 0.46-aspect phone panel.
    c = _client(); j = _upload(c)
    c.post("/api/proof", data={"session_id": j["session"], **_crop(j),
                               "print_w": 9, "print_h": 12})
    sub = c.post("/api/timelapse/submit",
                 data={"session_id": j["session"], "max_frames": 3,
                       "wallpaper_preset": "ig_reel", "format": "webp"})
    assert sub.status_code == 200, sub.text
    s = _await_job(c, sub.json()["job"])
    assert s["state"] == "done", s
    data = c.get(s["result"]).content
    im = Image.open(io.BytesIO(data))
    assert im.size == (1080, 1920)                            # exactly 9:16
    assert im.info.get("icc_profile")                         # the WebP twin's sRGB
    assert provenance.extract(data) is None                   # share twin: no manifest


def test_social_presets_are_platform_true():
    reel = wallpaper.PRESETS["ig_reel"]
    assert (reel.px_w, reel.px_h) == (1080, 1920) and reel.device_class == "social"
    assert reel.bottom_clear_frac == wallpaper.REEL_BOTTOM_CLEAR    # the caption zone
    assert wallpaper.PRESETS["ig_portrait"].aspect == 1080 / 1350   # 4:5
    assert wallpaper.PRESETS["ig_square"].aspect == 1.0
    # clean furniture, like every screen deliverable (a caption belongs to the post)
    f = reel.spec_fields()
    assert f["keyline"] is False and f["title_text"] == ""
    assert f["bottom_clear_frac"] == wallpaper.REEL_BOTTOM_CLEAR


# ---- the bottom keep-out band: the clock band's twin ----

def _region_spec(**kw):
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    base = dict(region_id="lassen_ca", crs=cfg["crs"],
                crop=(cx - 13500, cy - 18000, cx + 13500, cy + 18000),  # 27x36 km, 3:4
                print_w_in=9, print_h_in=12, native_resolution_m=10,
                tracks=[], hotspots=[], seed=7, title_text="-", compass=False)
    base.update(kw)
    return CompositionSpec(**base)


def test_bottom_clear_band_keeps_auto_labels_out_of_the_chrome_zone():
    # mirror of the clock-band test: a label anchored ~12% up the sheet draws with no
    # band and vanishes under bottom_clear_frac (home indicator / Reel caption zone).
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    nw = {"lakes": [], "rivers": []}
    spec = _region_spec(labels=True, bottom_clear_frac=0.0)
    banded = _region_spec(labels=True, bottom_clear_frac=0.30)
    ax = (spec.crop[0] + spec.crop[2]) / 2
    ay = spec.crop[1] + 0.12 * (spec.crop[3] - spec.crop[1])
    labels = {"crs": cfg["crs"], "features": [
        {"name": "Gesture Bar Butte", "kind": "summit", "rank": 85, "coords": [[ax, ay]]}]}
    base = np.asarray(render.rasterize(_region_spec(labels=False), dpi=96,
                                       region_dir=REGION_DIR, hydro=nw))
    with_label = np.asarray(render.rasterize(spec, dpi=96, region_dir=REGION_DIR,
                                             hydro=nw, labels=labels))
    with_band = np.asarray(render.rasterize(banded, dpi=96, region_dir=REGION_DIR,
                                            hydro=nw, labels=labels))
    assert not np.array_equal(base, with_label), "label never drew at all"
    assert np.array_equal(base, with_band), \
        "bottom_clear_frac must drop an auto label anchored in the chrome band"


def test_bottom_clear_bounds_rejected():
    with pytest.raises(SpecError):
        _region_spec(bottom_clear_frac=0.5).validate(96)
    with pytest.raises(SpecError):
        _region_spec(bottom_clear_frac=-0.1).validate(96)


# ---- the bundle's skip paths: partial failure is reported, never hidden ----

def test_bundle_worker_writes_skipped_txt_and_keeps_survivors(monkeypatch):
    # the worker's per-item backstop: one device failing at RENDER time lands in
    # SKIPPED.txt while the others ship. Rasterize is faked (this is a logic test of
    # the skip/zip path, not a render test): the iphone's ppi raises, the rest paint.
    from app import main as _main
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    base = _region_spec()
    bounds = tuple(cfg["bounds"])
    items = [(wallpaper.spec_for_preset(base, wallpaper.PRESETS["desktop_fhd"], bounds),
              "a_desktop.png"),
             (wallpaper.spec_for_preset(base, wallpaper.PRESETS["iphone"], bounds),
              "b_iphone.png")]
    def fake_rasterize(spec, dpi, region_dir, **kw):
        if spec.screen_ppi == 460.0:
            raise SpecError("no DEM under this refit")
        return Image.new("RGB", (8, 8), (10, 20, 30))
    monkeypatch.setattr(_main.render, "rasterize", fake_rasterize)
    _main._render_bundle_to_blob(items, REGION_DIR, "test/of_bundle.zip", cfg, [], True)
    z = zipfile.ZipFile(io.BytesIO(open(_main.BLOBS.path("test/of_bundle.zip"), "rb").read()))
    assert sorted(z.namelist()) == ["SKIPPED.txt", "a_desktop.png"]
    note = z.read("SKIPPED.txt").decode()
    assert "b_iphone.png" in note and "no DEM" in note
    # every device failing is a real error (the zip must not ship empty-but-"done")
    def all_fail(spec, dpi, region_dir, **kw):
        raise SpecError("nope")
    monkeypatch.setattr(_main.render, "rasterize", all_fail)
    with pytest.raises(RuntimeError):
        _main._render_bundle_to_blob(items, REGION_DIR, "test/of_bundle2.zip", cfg, [], True)


def test_bundle_response_reports_skips_and_fit_growth(monkeypatch):
    # the pre-enqueue truth the UI shows: a preset that can't re-fit lands in
    # `skipped` with its reason; every rendered device reports how far its re-fit
    # crop grew from the proofed frame (crop_growth, area ratio >= ~1.0).
    from app import main as _main
    c = _client(); j = _upload(c)
    r = c.post("/api/proof", data={"session_id": j["session"], **_crop(j),
                                   "print_w": 9, "print_h": 12})
    assert r.status_code == 200, r.text
    real = wallpaper.spec_for_preset
    def picky(spec, preset, bounds):
        if preset.id == "iphone":
            raise SpecError("region too small for this device")
        return real(spec, preset, bounds)
    monkeypatch.setattr(_main.wallpaper, "spec_for_preset", picky)
    sub = c.post("/api/wallpapers/submit",
                 data={"session_id": j["session"], "presets": "desktop_fhd,iphone"})
    assert sub.status_code == 200, sub.text
    body = sub.json()
    assert body["count"] == 1
    assert body["skipped"] == [{"preset": "iphone",
                               "reason": "region too small for this device"}]
    assert [f["preset"] for f in body["fitted"]] == ["desktop_fhd"]
    assert body["fitted"][0]["crop_growth"] >= 0.9          # a real, reported ratio
    # ...and when NO device fits, the submit itself is an honest 422
    monkeypatch.setattr(_main.wallpaper, "spec_for_preset",
                        lambda s, p, b: (_ for _ in ()).throw(SpecError("too small")))
    r = c.post("/api/wallpapers/submit",
               data={"session_id": j["session"], "presets": "desktop_fhd,iphone"})
    assert r.status_code == 422
    _await_job(c, body["job"])          # let the enqueued render finish before teardown


# ---- share-twin color contracts: read the tags back, don't trust the flags ----

def test_webp_twin_carries_the_srgb_profile():
    from app.main import SRGB_PROFILE
    frames = [Image.new("RGB", (32, 48), c) for c in ((240, 20, 20), (20, 240, 20))]
    data = timelapse.encode_webp(frames, icc_profile=SRGB_PROFILE)
    assert Image.open(io.BytesIO(data)).info.get("icc_profile") == SRGB_PROFILE


@pytest.mark.skipif(not timelapse.MP4_AVAILABLE,
                    reason="mp4 needs the share extra (imageio-ffmpeg)")
def test_mp4_twin_is_tagged_bt709():
    # the encoder converts AND tags BT.709 (untagged HD decodes as 709 on real players
    # while swscale defaults to 601 -- the hues would drift from the poster). The tag
    # lands in the stream's `colr` box: 'nclx', primaries=1, transfer=1, matrix=1.
    frames = [Image.new("RGB", (32, 48), c) for c in ((240, 20, 20), (20, 240, 20))]
    data = timelapse.encode_mp4(frames)
    assert b"colr" in data, "no colour-description box in the stream"
    assert b"nclx\x00\x01\x00\x01\x00\x01" in data, \
        "colr box is not the BT.709 nclx triplet"
