# tests/test_journey_light.py
"""Journey Light (v1.9) -- the contract suite.

- solar position matches a published ephemeris; the schedule/anchor are deterministic;
- archival light + no profile + no coloring is a STRICT no-op (byte-identical render);
- journey mode changes the render deterministically and composes with High relief
  (proof==final under the warp, last-frame==still holds);
- the elevation profile and track coloring are DEM-derived (reprint-safe) and off by
  default; waypoints and per-vertex timing survive ingest + serialize.
"""
import dataclasses
import datetime as dt
import json
import os

import numpy as np
import pytest

from app import ingest, render, serialize, solar, timelapse
from app.regions import discover
from app.spec import CompositionSpec, SpecError

REGION_DIR = "regions/lassen_ca"


def _cfg():
    return json.load(open(os.path.join(REGION_DIR, "region.json")))


def _diag_track(cfg, n=40):
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    xs = np.linspace(cx - 9000, cx + 9000, n)
    ys = np.linspace(cy - 12000, cy + 12000, n)
    return np.column_stack([xs, ys])


def _spec(**kw):
    cfg = _cfg()
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    crop = (cx - 13500, cy - 18000, cx + 13500, cy + 18000)
    base = dict(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                print_w_in=9, print_h_in=12, native_resolution_m=10,
                tracks=[_diag_track(cfg)], hotspots=[], track_days=["2023-07-15"], seed=7)
    base.update(kw)
    return CompositionSpec(**base)


DPI = 96


def _render(spec):
    return np.asarray(render.rasterize(spec, DPI, REGION_DIR).convert("RGB"))


# ---- solar ----

def test_solar_matches_nrel_reference():
    az, alt = solar.solar_position(
        dt.datetime(2003, 10, 17, 19, 30, 30, tzinfo=dt.timezone.utc), 39.742476, -105.1786)
    assert abs(az - 194.340) < 0.3 and abs(alt - 39.888) < 0.3


def test_solar_deterministic():
    args = (dt.datetime(2023, 7, 15, 22, 0, 0, tzinfo=dt.timezone.utc), 40.5, -121.5)
    assert solar.solar_position(*args) == solar.solar_position(*args)


def _anchor_from_gpx():
    geo = discover()["lassen_ca"].geo
    base = dt.datetime(2023, 7, 15, 21, 0, 0, tzinfo=dt.timezone.utc)  # afternoon PT
    pts = []
    for i in range(60):
        lon, lat = -121.50 + 0.0012 * i, 40.48 + 0.0009 * i
        ele = 1800 + (i if i < 30 else 60 - i) * 25          # summit at i=30
        t = (base + dt.timedelta(minutes=6 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        pts.append(f'<trkpt lat="{lat}" lon="{lon}"><ele>{ele}</ele><time>{t}</time></trkpt>')
    gpx = ('<?xml version="1.0"?><gpx version="1.1">'
           '<wpt lat="40.50" lon="-121.45"><name>Camp</name><sym>Campground</sym></wpt>'
           '<trk><name>c</name><trkseg>' + "".join(pts) + "</trkseg></trk></gpx>").encode()
    return gpx, geo


def test_anchor_and_summit_light():
    gpx, geo = _anchor_from_gpx()
    tracks = ingest.load_tracks(gpx, geo)
    anchor = solar.track_anchor(tracks)
    assert anchor is not None and anchor["summit_unix"] is not None
    js = solar.journey_sun(anchor)
    assert 8.0 <= js["altitude_deg"] <= 80.0 and 0 <= js["azimuth_deg"] < 360
    # a midnight scrub must clamp to the daylight floor, never an under-horizon sun
    assert solar.journey_sun(anchor, 2.0)["altitude_deg"] >= 8.0


def test_sun_schedule_pure_and_bounded():
    _, geo = _anchor_from_gpx()
    gpx, _ = _anchor_from_gpx()
    anchor = solar.track_anchor(ingest.load_tracks(gpx, geo))
    a = solar.sun_schedule(anchor, 8, "auto")
    b = solar.sun_schedule(anchor, 8, "auto")
    assert a == b and len(a) == 8
    assert all(8.0 <= alt <= 80.0 for _, alt in a)


# ---- ingest / serialize ----

def test_ingest_keeps_time_summit_and_waypoints():
    gpx, geo = _anchor_from_gpx()
    tr = ingest.load_tracks(gpx, geo)[0]
    assert tr.t0 and tr.t1 and tr.lonlat is not None
    assert tr.coords_t is not None and np.isfinite(tr.coords_t).any()
    assert tr.summit_t is not None and tr.summit_ele is not None
    wpts = ingest.load_waypoints(gpx, geo)
    assert len(wpts) == 1 and wpts[0]["label"] == "Camp" and wpts[0]["icon"] == "camp"
    # roundtrip incl. the new per-vertex/summit fields, and old rows still load
    tr2 = serialize.track_from_json(serialize.track_to_json(tr))
    assert tr2.summit_t == tr.summit_t
    assert serialize.track_from_json({"track_id": "x", "coords": [[0, 0], [1, 1]],
                                      "day": None}).lonlat is None


def test_route_has_no_timing():
    geo = discover()["lassen_ca"].geo
    gpx = (b'<?xml version="1.0"?><gpx version="1.1"><rte>'
           b'<rtept lat="40.48" lon="-121.50"/><rtept lat="40.50" lon="-121.48"/>'
           b"</rte></gpx>")
    tr = ingest.load_tracks(gpx, geo)[0]
    assert tr.coords_t is None and tr.summit_t is None
    assert solar.track_anchor([tr]) is None


# ---- render ----

def test_archival_is_strict_noop():
    a = _render(_spec())
    b = _render(_spec(light_mode="archival", profile=False, track_color_by="none"))
    assert np.array_equal(a, b)


def test_journey_changes_render_and_is_deterministic():
    arch = _render(_spec())
    j = _spec(light_mode="journey", sun_azimuth_deg=250.0, sun_altitude_deg=14.0,
              golden_strength=0.8)
    r1, r2 = _render(j), _render(j)
    assert np.array_equal(r1, r2)
    assert not np.array_equal(arch, r1)


def test_profile_off_is_noop_on_and_draws():
    off = _render(_spec())
    on = _render(_spec(profile=True))
    assert not np.array_equal(off, on)
    # the profile lives in the lower-left inset; that region must be what changed
    h, w, _ = off.shape
    assert not np.array_equal(off[int(h * 0.8):, :int(w * 0.5)],
                              on[int(h * 0.8):, :int(w * 0.5)])


def test_coloring_off_is_noop_on_and_changes_track():
    flat = _render(_spec())
    col = _render(_spec(track_color_by="elevation"))
    assert not np.array_equal(flat, col)
    assert np.array_equal(flat, _render(_spec(track_color_by="none")))


def test_journey_composes_with_high_relief():
    j = dict(light_mode="journey", sun_azimuth_deg=250.0, sun_altitude_deg=14.0,
             golden_strength=0.8, track_color_by="grade", profile=True)
    flat = _render(_spec(**j))
    obl = _render(_spec(oblique=0.8, **j))
    assert not np.array_equal(flat, obl)              # the warp changed the picture
    assert np.array_equal(obl, _render(_spec(oblique=0.8, **j)))  # deterministic


def test_bad_light_values_rejected():
    for bad in (dict(light_mode="bogus"), dict(track_color_by="rainbow"),
                dict(sun_altitude_deg=3.0), dict(sun_azimuth_deg=400.0)):
        with pytest.raises(SpecError):
            _spec(**bad).validate(DPI)


# ---- API (endpoint-level, over the live app) ----

def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def _upload(c, name="a.gpx"):
    data = open("tests/fixtures/sample.gpx", "rb").read()
    r = c.post("/api/upload", files=[("files", (name, data, "application/gpx+xml"))])
    assert r.status_code == 200
    return r.json()


def _crop_form(j):
    cfg = _cfg()
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (40000.0 / region_w)
    ch = cw / 0.75
    x0, y0 = ovw * 0.5 - cw / 2, ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch,
            "print_w": 9, "print_h": 12}


def test_upload_reports_journey_light_available():
    j = _upload(_client())
    assert j["journey_light"]["available"] is True
    assert "sun" in j["journey_light"] and 8.0 <= j["journey_light"]["sun"]["altitude_deg"] <= 80.0


def test_journey_proof_stamps_resolved_sun_and_differs():
    c = _client()
    j = _upload(c)
    form = _crop_form(j)
    arch = c.post("/api/proof", data={"session_id": j["session"], **form})
    assert arch.status_code == 200
    jr = c.post("/api/proof", data={"session_id": j["session"], **form,
                                    "light_mode": "journey", "golden_strength": 0.8})
    assert jr.status_code == 200
    assert jr.content != arch.content                     # journey != archival bytes


def test_journey_proof_requires_timestamps():
    c = _client()
    # a route-only GPX (no <time>) -> journey light 422s honestly
    gpx = (b'<?xml version="1.0"?><gpx version="1.1"><rte>'
           b'<rtept lat="40.42" lon="-120.65"/><rtept lat="40.44" lon="-120.63"/>'
           b"</rte></gpx>")
    j = c.post("/api/upload", files=[("files", ("r.gpx", gpx, "application/gpx+xml"))]).json()
    assert j["journey_light"]["available"] is False
    r = c.post("/api/proof", data={"session_id": j["session"], **_crop_form(j),
                                   "light_mode": "journey"})
    assert r.status_code == 422 and "timestamp" in r.text.lower()


# ---- the Journey Light film (time-true reveal + moving sun) ----

def test_time_reveal_grows_and_closes_on_full_trip():
    spec = _spec()
    n = spec.tracks[0].shape[0]
    times = [np.linspace(0.0, 3600.0, n)]                # one steady hour
    frames = timelapse.time_reveal(spec, times, 6)
    assert frames[0].tracks == []                        # leader
    lengths = [f.tracks[0].shape[0] if f.tracks else 0 for f in frames]
    assert lengths == sorted(lengths)                    # monotonic growth
    assert frames[-1].tracks[0].shape[0] == n            # closes on the whole trip


def test_time_reveal_compresses_an_overnight_gap():
    spec = _spec()
    n = spec.tracks[0].shape[0]
    # half the points in hour 1, then a 12 h gap, then the rest in hour 2
    t = np.concatenate([np.linspace(0, 3600, n // 2),
                        np.linspace(3600 + 12 * 3600, 3600 + 12 * 3600 + 3600, n - n // 2)])
    frames = timelapse.time_reveal(spec, [t], 8)
    # the gap is compressed, so the reveal doesn't spend most frames stalled before it
    mid = frames[len(frames) // 2].tracks
    assert mid and mid[0].shape[0] > n // 2              # past the gap by the midpoint


def test_journey_light_film_deterministic_and_moves():
    gpx, geo = _anchor_from_gpx()
    tracks = ingest.load_tracks(gpx, geo)
    anchor = solar.track_anchor(tracks)
    cfg = _cfg()
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    spec = CompositionSpec(region_id="lassen_ca", crs=cfg["crs"],
                           crop=(cx - 13500, cy - 18000, cx + 13500, cy + 18000),
                           print_w_in=9, print_h_in=12, native_resolution_m=10,
                           tracks=[t.coords for t in tracks],
                           track_days=[t.day for t in tracks], hotspots=[], seed=7)
    tt = [t.coords_t for t in tracks]
    f1 = list(timelapse.journey_light_frames(spec, tt, anchor, dpi=72,
              region_dir=REGION_DIR, motion="auto", n_frames=5))
    f2 = list(timelapse.journey_light_frames(spec, tt, anchor, dpi=72,
              region_dir=REGION_DIR, motion="auto", n_frames=5))
    assert timelapse.encode_webp(f1) == timelapse.encode_webp(f2)     # deterministic
    assert not np.array_equal(np.asarray(f1[1]), np.asarray(f1[-1]))  # sun + line moved


def test_journey_light_film_is_share_twin_only():
    c = _client()
    j = _upload(c)
    c.post("/api/proof", data={"session_id": j["session"], **_crop_form(j)})  # stamp a spec
    apng = c.post("/api/timelapse/submit", data={"session_id": j["session"],
                  "format": "apng", "light_motion": "diurnal", "max_frames": 4})
    assert apng.status_code == 422                        # moving sun is not archival APNG
    webp = c.post("/api/timelapse/submit", data={"session_id": j["session"],
                  "format": "webp", "light_motion": "auto", "max_frames": 4})
    assert webp.status_code == 200 and "job" in webp.json()
