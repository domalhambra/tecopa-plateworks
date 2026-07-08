# tests/test_timelapse.py
"""Time-lapse: the poster as a film.

One spec painted as day-ordered journey prefixes over a static terrain base, encoded as
a self-describing APNG. The master invariant is that the last frame is pixel-equal to
`render.rasterize` at the same dpi -- proving the base/journey/overlay refactor is inert
and that the film ends on the exact still poster. Also covers frame_plan ordering/
binning, APNG manifest + per-frame durations, determinism, the API (submit, pacing/
ceiling 422s, wallpaper-preset films, reprint-of-film reproducibility), and a frozen
animation fixture (the forever-contract for the new `animation` manifest key)."""
import io
import json
import time

import numpy as np
import pytest
from PIL import Image

from app import provenance, render, timelapse
from app.spec import CompositionSpec

REGION_DIR = "regions/lassen_ca"


# ---- helpers ----

def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

def _spec(n_journeys=3, days=None, **kw):
    m = json.load(open("tests/fixtures/manifest_v1.json"))
    spec = provenance.manifest_to_spec(m)
    spec.tracks = [np.array([[680000.0 + i * 400, 4470000.0 + i * 400],
                             [700000.0 - i * 400, 4500000.0 - i * 400]])
                   for i in range(n_journeys)]
    spec.track_days = days if days is not None else [f"2024-06-{i + 1:02d}"
                                                     for i in range(n_journeys)]
    spec.hotspots = [{"x": 690000.0, "y": 4485000.0, "weight": 2, "label": "Camp"}]
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec

def _gpx(name, data):
    return ("files", (name, data, "application/gpx+xml"))

def _multiday_gpx():
    # sample.gpx already spans five days; a second copy with a shifted first day adds a
    # sixth journey and keeps four shared days (cross-file same-day tracks merge).
    s = open("tests/fixtures/sample.gpx", "rb").read()
    return s, s.replace(b"2024-06-01", b"2025-06-01")

def _crop(j, km_wide=40.0, ar=0.75):
    cfg = json.load(open(f"{REGION_DIR}/region.json"))
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (km_wide * 1000.0 / region_w); ch = cw / ar
    x0 = ovw * 0.5 - cw / 2; y0 = ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch}

def _await_job(c, jid, tries=3000):
    for _ in range(tries):
        s = c.get(f"/api/jobs/{jid}").json()
        if s["state"] in ("done", "error"):
            return s
        time.sleep(0.05)
    raise AssertionError("job never finished")


# ---- the master invariant: the refactor is inert + the film ends on the poster ----

def test_last_frame_is_pixel_equal_to_rasterize():
    spec = _spec(n_journeys=4)
    dpi = 120
    still = np.asarray(render.rasterize(spec, dpi=dpi, region_dir=REGION_DIR))
    frames = list(timelapse.render_frames(spec, dpi, REGION_DIR))
    last = np.asarray(frames[-1])
    assert last.shape == still.shape and np.array_equal(last, still)

def test_single_journey_last_frame_equals_rasterize():
    # the worn-width path differs for one journey; the invariant must still hold
    spec = _spec(n_journeys=1)
    still = np.asarray(render.rasterize(spec, dpi=110, region_dir=REGION_DIR))
    last = np.asarray(list(timelapse.render_frames(spec, 110, REGION_DIR))[-1])
    assert np.array_equal(last, still)

def test_leader_frame_has_no_route_ink():
    # frame 0 is bare terrain (+ static markers/furniture): the route ink is absent, so
    # it differs from the final and shows less of the track swatch.
    spec = _spec(n_journeys=3, track_rgb=(214, 60, 60))   # a vivid, easy-to-count ink
    frames = list(timelapse.render_frames(spec, 120, REGION_DIR))
    def redness(im):
        a = np.asarray(im).astype(int)
        return int(((a[..., 0] > 150) & (a[..., 1] < 110) & (a[..., 2] < 110)).sum())
    assert redness(frames[0]) < redness(frames[-1])
    assert not np.array_equal(np.asarray(frames[0]), np.asarray(frames[-1]))


# ---- frame_plan (pure) ----

def test_frame_plan_leader_and_canonical_last():
    spec = _spec(n_journeys=4)
    plan = timelapse.frame_plan(spec, max_frames=40)
    assert plan[0] == []                                   # leader: bare terrain
    assert plan[-1] == render._journey_groups(spec)        # last == canonical full (byte-eq)
    # cumulative and monotonic
    counts = [len(p) for p in plan]
    assert counts == sorted(counts) and counts[-1] == 4

def test_frame_plan_reveals_in_day_order_dayless_last():
    # journeys out of chronological order + one day-less: reveal is chronological, the
    # day-less journey comes last.
    spec = _spec(n_journeys=4, days=["2024-08-01", "2024-05-01", None, "2024-06-01"])
    plan = timelapse.frame_plan(spec, max_frames=40)
    groups = render._journey_groups(spec)
    # the first revealed journey (plan[1]) is the earliest-dated one (2024-05-01 -> idx 1)
    first_revealed = plan[1][0]
    assert first_revealed == groups[1]
    # the day-less journey (idx 2) is only present in the final full frame
    assert groups[2] not in plan[-2] if len(plan) >= 2 else True
    assert groups[2] in plan[-1]

def test_frame_plan_bins_to_max_frames():
    spec = _spec(n_journeys=30)
    plan = timelapse.frame_plan(spec, max_frames=10)
    assert len(plan) <= 10
    assert plan[-1] == render._journey_groups(spec)        # full poster still last
    assert plan[0] == []

def test_frame_plan_degenerate_cases():
    assert timelapse.frame_plan(_spec(n_journeys=1), 40) == [[], render._journey_groups(_spec(1))]
    # max_frames=2 -> leader + full only
    p = timelapse.frame_plan(_spec(n_journeys=8), max_frames=2)
    assert len(p) == 2 and p[0] == [] and len(p[1]) == 8

def test_frame_plan_is_pure():
    spec = _spec(n_journeys=5)
    assert timelapse.frame_plan(spec, 40) == timelapse.frame_plan(spec, 40)


# ---- APNG encoding ----

def test_apng_carries_manifest_and_durations():
    spec = _spec(n_journeys=3)
    frames = list(timelapse.render_frames(spec, 96, REGION_DIR))
    manifest = provenance.build_manifest(
        spec, [], None, animation=timelapse.animation_meta(20, 220, 2500, 700, 96))
    data = timelapse.encode_apng(frames, manifest=manifest, step_ms=220,
                                 hold_ms=2500, leader_ms=700)
    im = Image.open(io.BytesIO(data))
    assert im.is_animated and im.n_frames == len(frames)
    durs = []
    for i in range(im.n_frames):
        im.seek(i); durs.append(im.info.get("duration"))
    assert durs[0] == 700 and durs[-1] == 2500 and durs[1] == 220
    got = provenance.extract(data)
    assert got["animation"]["max_frames"] == 20
    provenance.manifest_to_spec(got)                       # the film round-trips to a spec

def test_film_is_deterministic():
    spec = _spec(n_journeys=3)
    mk = lambda: timelapse.encode_apng(list(timelapse.render_frames(spec, 96, REGION_DIR)),
                                       step_ms=220, hold_ms=2500, leader_ms=700)
    assert mk() == mk()

def test_edition_one_still_manifest_omits_animation():
    # additive key: a still manifest never carries `animation` (frozen fixtures untouched)
    m = provenance.build_manifest(_spec(n_journeys=2), [], None)
    assert "animation" not in m


# ---- API: submit ----

def _stamped(c, print_w=6, print_h=8, proof_extra=None):
    a, b = _multiday_gpx()
    j = c.post("/api/upload", files=[_gpx("a.gpx", a), _gpx("b.gpx", b)]).json()
    data = {"session_id": j["session"], **_crop(j), "print_w": print_w,
            "print_h": print_h, "title": "Trip"}
    data.update(proof_extra or {})
    r = c.post("/api/proof", data=data)
    assert r.status_code == 200, r.text
    return j["session"], j

def test_submit_renders_an_apng_with_the_animation_block():
    c = _client()
    sid, _ = _stamped(c)
    sub = c.post("/api/timelapse/submit", data={"session_id": sid, "max_frames": 15})
    assert sub.status_code == 200, sub.text
    body = sub.json()
    assert body["frames"] >= 2
    s = _await_job(c, body["job"])
    assert s["state"] == "done", s
    data = c.get(s["result"]).content
    im = Image.open(io.BytesIO(data))
    assert im.is_animated and im.n_frames == body["frames"]
    m = provenance.extract(data)
    assert m["animation"]["max_frames"] == 15              # pacing recorded on the file
    assert m["animation"]["dpi"] == 96                     # screen-fidelity default (PROOF_DPI)

def test_submit_requires_a_stamped_proof():
    c = _client()
    a, _ = _multiday_gpx()
    j = c.post("/api/upload", files=[_gpx("a.gpx", a)]).json()
    r = c.post("/api/timelapse/submit", data={"session_id": j["session"]})
    assert r.status_code == 400                            # approve a proof first

@pytest.mark.parametrize("bad", [
    {"max_frames": 1}, {"max_frames": 200},
    {"step_ms": 5}, {"step_ms": 99999}, {"hold_ms": 1}, {"leader_ms": 50000},
])
def test_submit_pacing_bounds_are_422(bad):
    c = _client()
    sid, _ = _stamped(c)
    r = c.post("/api/timelapse/submit", data={"session_id": sid, **bad})
    assert r.status_code == 422, r.text

def test_animation_ceiling_rejects_an_oversize_film():
    # the total-pixel ceiling (frames x w x h) guards the worker: unit-test the helper
    # directly -- a real film big enough to breach 600 MP is too slow for the suite.
    from fastapi import HTTPException
    from app.main import _animation_ceiling_or_422, MAX_ANIMATION_PIXELS
    spec = _spec(n_journeys=10)                            # 11 frames (leader + 10)
    w, h = spec.pixel_size(800)                            # 9x12 in @ 800 dpi -> ~69 MP
    assert 11 * w * h > MAX_ANIMATION_PIXELS
    with pytest.raises(HTTPException):
        _animation_ceiling_or_422(spec, 800, 40)
    # a sane target passes and returns the frame count
    assert _animation_ceiling_or_422(spec, 96, 40) == 11

def test_submit_dpi_out_of_range_is_422():
    c = _client()
    sid, _ = _stamped(c)
    r = c.post("/api/timelapse/submit", data={"session_id": sid, "dpi": 5000})
    assert r.status_code == 422


# ---- API: wallpaper-preset film is exact device pixels ----

def test_wallpaper_preset_film_is_native_pixels():
    from app import wallpaper
    c = _client()
    sid, _ = _stamped(c)
    p = wallpaper.PRESETS["desktop_fhd"]
    sub = c.post("/api/timelapse/submit",
                 data={"session_id": sid, "max_frames": 8, "wallpaper_preset": "desktop_fhd"})
    assert sub.status_code == 200, sub.text
    s = _await_job(c, sub.json()["job"])
    assert s["state"] == "done", s
    im = Image.open(io.BytesIO(c.get(s["result"]).content))
    assert im.size == (p.px_w, p.px_h)                     # the device's native pixels


# ---- API: reprint of a film + inspect ----

def test_reprint_of_a_film_reproduces_it_byte_identically():
    c = _client()
    sid, _ = _stamped(c)
    sub = c.post("/api/timelapse/submit", data={"session_id": sid, "max_frames": 10})
    film1 = c.get(_await_job(c, sub.json()["job"])["result"]).content
    # reprint the film -> a job (async, since a film render is slow), then the APNG
    rp = c.post("/api/reprint", files={"file": ("film.png", film1, "image/png")})
    assert rp.status_code == 200, rp.text
    assert "job" in rp.json()
    film2 = c.get(_await_job(c, rp.json()["job"])["result"]).content
    assert film1 == film2                                  # the file re-renders itself

def test_reprint_of_a_film_refuses_pdf():
    c = _client()
    sid, _ = _stamped(c)
    sub = c.post("/api/timelapse/submit", data={"session_id": sid, "max_frames": 6})
    film = c.get(_await_job(c, sub.json()["job"])["result"]).content
    r = c.post("/api/reprint", files={"file": ("film.png", film, "image/png")},
               data={"format": "pdf"})
    assert r.status_code == 422

def test_inspect_reports_the_animation_block():
    c = _client()
    sid, _ = _stamped(c)
    sub = c.post("/api/timelapse/submit", data={"session_id": sid, "max_frames": 6})
    film = c.get(_await_job(c, sub.json()["job"])["result"]).content
    body = c.post("/api/reprint/inspect", files={"file": ("f.png", film, "image/png")}).json()
    assert body["animation"] and body["animation"]["max_frames"] == 6

def test_still_inspect_has_null_animation():
    c = _client()
    sid, _ = _stamped(c)
    still = c.post("/api/final", data={"session_id": sid}).content
    body = c.post("/api/reprint/inspect", files={"file": ("s.png", still, "image/png")}).json()
    assert body["animation"] is None


# ---- the forever-contract: a frozen film fixture still re-renders ----

def test_worker_honors_max_frames_not_the_default():
    # regression (adversarial review, high): the worker used to call render_frames with
    # NO plan, so it always rendered DEFAULT_MAX_FRAMES (40) and bypassed the ceiling the
    # submit path checked against the requested max_frames. With many journeys and a small
    # max_frames, the encoded APNG must have the ceiling-checked frame count, not 40.
    from app import main as _main
    spec = _spec(n_journeys=30)                            # 30 day-distinct journeys
    pacing = {"max_frames": 5, "step_ms": 220, "hold_ms": 2500, "leader_ms": 700}
    _main._render_timelapse_to_blob(spec, REGION_DIR, "test/tl.png", 90, pacing, [], True)
    im = Image.open(_main.BLOBS.path("test/tl.png"))
    expected = len(timelapse.frame_plan(spec, 5))
    assert expected <= 5 and im.n_frames == expected      # NOT 31 (the default-40 plan)

def test_reprint_dpi_clamp_rejects_a_crafted_huge_dpi():
    # a crafted animation.dpi beyond the legit film range falls back to the spec's dpi
    from app.main import _animation_from_manifest_or_422
    spec = _spec(n_journeys=2)
    _, dpi = _animation_from_manifest_or_422({"dpi": 5000}, spec)
    assert dpi == spec.final_dpi()
    _, dpi2 = _animation_from_manifest_or_422({"dpi": 120}, spec)
    assert dpi2 == 120                                    # an in-range dpi is kept verbatim

def test_single_frame_film_degrades_to_a_static_poster():
    # a 0-journey spec yields one bare frame: encode_apng must degrade to a plain static
    # PNG (no leader/hold ambiguity), not a one-frame "animation".
    spec = _spec(n_journeys=0, days=[])
    frames = list(timelapse.render_frames(spec, 96, REGION_DIR))
    assert len(frames) == 1
    data = timelapse.encode_apng(frames, step_ms=220, hold_ms=2500, leader_ms=700)
    im = Image.open(io.BytesIO(data))
    assert not getattr(im, "is_animated", False)

def test_frozen_animation_fixture_reprints_as_a_film():
    c = _client()
    m = json.load(open("tests/fixtures/manifest_animation_v1.json"))
    spec = provenance.manifest_to_spec(m)
    spec.validate(spec.final_dpi())
    img = Image.new("RGB", (16, 16), (20, 20, 20))
    buf = io.BytesIO(); img.save(buf, "PNG", pnginfo=provenance.manifest_pnginfo(m))
    r = c.post("/api/reprint", files={"file": ("film_v1.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    assert "job" in r.json()                               # a film reprints via the queue
    s = _await_job(c, r.json()["job"])
    assert s["state"] == "done", s
    im = Image.open(io.BytesIO(c.get(s["result"]).content))
    assert im.is_animated and im.n_frames >= 2
    got = provenance.extract(c.get(s["result"]).content)
    assert got["animation"]["max_frames"] == 20
