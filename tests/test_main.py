# tests/test_main.py
# Endpoint-level tests over the live app via FastAPI's TestClient. Lock the
# robustness/zoom-cap behaviors: clean 404/422/400 instead of opaque 500s, and
# the zoom cap judged at the FINAL print DPI rather than the proof DPI.
import io, json, os
from PIL import Image

REGION_DIR = "regions/lassen_ca"

# tests/conftest.py hydrates a synthetic DEM on a fresh clone / in CI, so these
# endpoint tests always run (red-team V1-4) instead of skipping without region assets.


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


def test_readyz_ok_with_hydrated_regions():
    # the hydrated (synthetic-DEM) region must report ready with matching bounds. Assert
    # the region entry rather than the aggregate 200, so a machine that also has a real
    # DEM with the documented bounds-drift (-> 503) doesn't fail this test.
    c = _client()
    r = c.get("/readyz")
    body = r.json()
    entry = next(e for e in body["regions"] if e["id"] == "lassen_ca")
    assert entry["dem_present"] and entry["ready"] and entry["bounds_match"]
    # status code tracks the aggregate: 200 iff every region is ready, else 503
    assert r.status_code == (200 if all(e["ready"] for e in body["regions"]) else 503)

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


def test_offdem_crop_proof_is_422():
    # red-team V1-1: a cap-clearing crop shoved off the region's DEM must 422
    # (humanized "extends past the elevation data"), not 500 or an invented poster.
    c = _client(); j = _upload(c)
    ovw, ovh = j["overview_size"]
    # 30 km clears the zoom cap with margin on BOTH axes (27 km sits exactly at the
    # 10 m/px boundary and overview-px rounding can tip the y-axis under it, which
    # would 422 at the cap and never reach the off-DEM guard this test pins).
    base = _crop(j, km_wide=30.0)
    shift = ovw * 0.9                             # slide it east, fully off the DEM
    data = {"session_id": j["session"],
            "x0": base["x0"] + shift, "y0": base["y0"],
            "x1": base["x1"] + shift, "y1": base["y1"],
            "print_w": 9, "print_h": 12}
    r = c.post("/api/proof", data=data)
    assert r.status_code == 422
    # pin the OFF-DEM path specifically (a zoom-cap 422 would not mention elevation data)
    assert "elevation data" in r.json().get("detail", "")

def test_proof_nonfinite_print_size_is_422_not_500():
    # red-team: print_w=nan would make round(nan) raise inside validate() -> uncaught 500;
    # the finiteness guard must turn it into a clean 422.
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": "nan", "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 422

def test_accumulate_preserves_marker_annotations():
    # red-team (high): adding one more day's GPX to a session used to recompute
    # hotspots from scratch, silently destroying every label/icon/photo.
    import io as _io
    import json as _json
    from PIL import Image as _Image
    c = _client(); j = _upload(c)
    assert c.post("/api/markers", data={"session_id": j["session"],
                  "markers": _json.dumps([{"i": 0, "label": "Base Camp",
                                           "icon": "camp"}])}).status_code == 200
    buf = _io.BytesIO(); _Image.new("RGB", (32, 32), (7, 8, 9)).save(buf, "PNG")
    assert c.post("/api/photo", data={"session_id": j["session"], "i": 0},
                  files={"file": ("p.png", buf.getvalue(), "image/png")}).status_code == 200
    r = c.post("/api/upload", files=[_file("b.gpx")], data={"session_id": j["session"]})
    assert r.status_code == 200
    from app import session as sess_mod
    spots = sess_mod.get(j["session"])["hotspots"]
    keep = [s for s in spots if s.get("label") == "Base Camp"]
    assert keep, "annotation lost on accumulate"
    assert keep[0].get("icon") == "camp" and keep[0].get("photo")

def test_accumulate_out_of_region_tracks_422():
    # a session bound to lassen must reject a file whose tracks land elsewhere,
    # not silently accumulate garbage (red-team: the session branch skipped the
    # in-bounds check).
    c = _client(); j = _upload(c)
    utah = (b'<?xml version="1.0"?><gpx version="1.1" creator="t" '
            b'xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
            b'<trkpt lat="39.30" lon="-111.50"></trkpt>'
            b'<trkpt lat="39.34" lon="-111.50"></trkpt>'
            b'</trkseg></trk></gpx>')
    r = c.post("/api/upload", files=[("files", ("utah.gpx", utah, "application/gpx+xml"))],
               data={"session_id": j["session"]})
    assert r.status_code == 422
    from app import session as sess_mod
    assert len(sess_mod.get(j["session"])["tracks"]) == 5     # session unchanged

def test_upload_oversize_rejected(monkeypatch):
    monkeypatch.setattr("app.main.TRACK_FILE_MAX_BYTES", 64)
    c = _client()
    r = c.post("/api/upload", files=[_file()])
    assert r.status_code == 422

def test_move_marker_nan_rejected_not_poisoned():
    # pydantic parses px="nan"; the clamp used to propagate NaN into stored x/y and
    # THEN 500 -- a permanently poisoned session (red-team).
    import math
    c = _client(); j = _upload(c)
    r = c.post("/api/markers/move", data={"session_id": j["session"], "i": 0,
                                          "px": "nan", "py": "10"})
    assert r.status_code == 422
    from app import session as sess_mod
    s0 = sess_mod.get(j["session"])["hotspots"][0]
    assert math.isfinite(s0["x"]) and math.isfinite(s0["y"])

def test_markers_non_dict_entries_skipped_not_500():
    import json as _json
    c = _client(); j = _upload(c)
    r = c.post("/api/markers", data={"session_id": j["session"],
               "markers": _json.dumps(["bogus", 7, {"i": 0, "label": "OK"}])})
    assert r.status_code == 200
    from app import session as sess_mod
    assert sess_mod.get(j["session"])["hotspots"][0]["label"] == "OK"
    assert c.post("/api/markers", data={"session_id": j["session"],
                  "markers": _json.dumps({"i": 0})}).status_code == 422

def test_contours_and_compass_flags_stamped_through_endpoint():
    # the furniture toggles are picture decisions: they must ride the stamped spec
    # so the final renders exactly what the proof showed (invariant 1).
    from app import session as sess_mod
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data={**data, "contours": "true",
                                      "compass": "false"}).status_code == 200
    spec = sess_mod.get(j["session"])["spec"]
    assert spec.contours is True and spec.compass is False
    assert c.post("/api/proof", data=data).status_code == 200          # defaults
    spec = sess_mod.get(j["session"])["spec"]
    assert spec.contours is False and spec.compass is True
    assert spec.biome is False
    # the biome toggle stamps through too (both regions ship committed landcover)
    assert c.post("/api/proof", data={**data, "biome": "true"}).status_code == 200
    assert sess_mod.get(j["session"])["spec"].biome is True

def test_style_knobs_stamped_through_endpoint():
    # the Style panel's values must ride the stamped spec (invariant 1), the hex
    # swatch must parse, and bad values must 422 -- not render something else.
    from app import session as sess_mod
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    styled = {**data, "track_width_pt": 3.4, "track_halo": 0.2,
              "track_color": "#b24c2b", "marker_size_in": 0.3,
              "marker_ring": 0.0, "photo_style": "polaroid",
              "furniture_scale": 1.3, "terrain_depth": 0.7, "shadow_strength": 0.3}
    assert c.post("/api/proof", data=styled).status_code == 200
    spec = sess_mod.get(j["session"])["spec"]
    assert spec.track_width_pt == 3.4 and spec.track_halo == 0.2
    assert spec.track_rgb == (178, 76, 43)
    assert spec.marker_diameter_in == 0.3 and spec.marker_ring == 0.0
    assert spec.photo_frame_style == "polaroid"
    assert spec.furniture_scale == 1.3 and spec.terrain_depth == 0.7
    assert spec.shadow_strength == 0.3
    # invalid values -> clean 422s
    assert c.post("/api/proof", data={**data, "track_color": "notahex"}).status_code == 422
    assert c.post("/api/proof", data={**data, "photo_style": "vignette"}).status_code == 422
    assert c.post("/api/proof", data={**data, "track_width_pt": 9}).status_code == 422
    assert c.post("/api/proof", data={**data, "furniture_scale": 0.3}).status_code == 422
    assert c.post("/api/proof", data={**data, "terrain_depth": 2.0}).status_code == 422
    assert c.post("/api/proof", data={**data, "shadow_strength": 1.5}).status_code == 422

def test_track_days_stamped_through_endpoint():
    # journey grouping is a rendering-semantics contract: the spec stamped by the
    # endpoint must carry the per-track days ingest parsed (a mutation dropping
    # track_days used to survive the whole endpoint suite -- red-team).
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 200
    from app import session as sess_mod
    spec = sess_mod.get(j["session"])["spec"]
    assert spec.track_days is not None and len(spec.track_days) == 5
    assert len({d for d in spec.track_days if d}) == 5        # five distinct days

def test_readyz_503_when_a_region_cannot_render(tmp_path, monkeypatch):
    # the 503 path was never exercised: a /readyz that always said 200 would blind
    # the health check (red-team). Break one region and expect 503 + its report.
    import json as _json
    from app import main as main_mod, regions as regions_mod
    d = tmp_path / "broken"; d.mkdir()
    (d / "region.json").write_text(_json.dumps({
        "id": "broken", "name": "Broken", "crs": "EPSG:32610",
        "bounds": [0.0, 0.0, 1000.0, 1000.0], "overview_size": [10, 10],
        "dem_path": "dem.tif", "native_resolution_m": 10,
        "elevation_min": 0.0, "elevation_max": 1.0}))
    broken = regions_mod.Region("broken", root=str(tmp_path))
    patched = dict(main_mod.REGIONS); patched["broken"] = broken
    monkeypatch.setattr(main_mod, "REGIONS", patched)
    r = _client().get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False
    assert any(e["id"] == "broken" and not e["ready"] for e in body["regions"])

def test_job_result_409_while_running_and_404_when_expired():
    import time
    c = _client()
    from app.main import QUEUE
    slow = QUEUE.submit(time.sleep, 1.0)
    assert c.get(f"/api/jobs/{slow}/result").status_code == 409   # not done yet
    gone = QUEUE.submit(lambda: "nonexistent/blob.png")           # done, blob missing
    for _ in range(200):
        if QUEUE.status(gone)["state"] == "done":
            break
        time.sleep(0.02)
    assert c.get(f"/api/jobs/{gone}/result").status_code == 404   # result expired

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

def test_photo_oversized_dimensions_rejected(monkeypatch):
    # red-team V1-6: a decompression-bomb photo (small file, huge declared dimensions)
    # must 422 on the pixel-count guard, not decode into an OOM.
    import io as _io
    from PIL import Image
    monkeypatch.setattr("app.main.PHOTO_MAX_PIXELS", 100)   # a 40x40 upload now exceeds it
    c = _client(); j = _upload(c)
    buf = _io.BytesIO(); Image.new("RGB", (40, 40), (1, 2, 3)).save(buf, "PNG"); buf.seek(0)
    r = c.post("/api/photo", data={"session_id": j["session"], "i": 0},
               files={"file": ("big.png", buf.getvalue(), "image/png")})
    assert r.status_code == 422

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
    for _ in range(1200):                      # generous budget for a CI runner
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

def test_final_blob_seam_srgb_and_dpi():
    # one 300-dpi render covers three contracts (the suite used to re-render an
    # identical final five times -- red-team): (a) the sync final routes through
    # the blob seam, not final_*.png in region.dir (V1-8); (b) the PNG embeds an
    # sRGB ICC profile; (c) it embeds the 300-dpi physical size.
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 200
    r = c.post("/api/final", data={"session_id": j["session"]})
    assert r.status_code == 200
    assert not os.path.exists(os.path.join(REGION_DIR, f"final_{j['session']}.png"))
    from app.main import BLOBS
    assert BLOBS.exists(f"{j['session']}/final.png")
    im = Image.open(io.BytesIO(r.content))
    assert im.info.get("icc_profile"), "no sRGB profile embedded"
    assert round(im.info["dpi"][0]) == 300

def test_sweep_uploads_evicts_stale_session_dirs(tmp_path):
    # red-team V1-8: a stale session's photo dir is evicted; an active one survives.
    import time
    from app.main import _sweep_uploads
    root = str(tmp_path / "uploads")
    os.makedirs(os.path.join(root, "old_sess"))
    os.makedirs(os.path.join(root, "fresh_sess"))
    stale = time.time() - 100_000
    os.utime(os.path.join(root, "old_sess"), (stale, stale))
    _sweep_uploads(ttl_seconds=3600, root=root)
    assert not os.path.exists(os.path.join(root, "old_sess"))
    assert os.path.exists(os.path.join(root, "fresh_sess"))

def test_final_unknown_format_is_422():
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 200
    assert c.post("/api/final", data={"session_id": j["session"],
                                      "format": "tiff"}).status_code == 422
    assert c.post("/api/final/submit", data={"session_id": j["session"],
                                             "format": "tiff"}).status_code == 422

def test_async_final_pdf_via_job_queue():
    # V1-10: the deliverable may be a PDF someone saves for themselves (or hands a
    # print shop). One render covers the whole pdf pipeline: _render_to_blob fmt,
    # the blob-key extension -> media type inference, and the embedded page size.
    import re, time
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 200
    jid = c.post("/api/final/submit", data={"session_id": j["session"],
                                            "format": "pdf"}).json()["job"]
    res = None
    for _ in range(1200):                     # generous budget for a CI runner
        s = c.get(f"/api/jobs/{jid}").json()
        if s["state"] in ("done", "error"):
            res = s
            break
        time.sleep(0.05)
    assert res and res["state"] == "done", res
    out = c.get(res["result"])
    assert out.status_code == 200
    assert out.headers["content-type"] == "application/pdf"
    assert out.content[:5] == b"%PDF-"
    # the PDF's reason to exist: a true 9x12 in page (648x864 pt) via resolution=300
    box = re.search(rb"/MediaBox \[ ([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) \]", out.content)
    assert box, "no MediaBox in PDF"
    assert [round(float(v)) for v in box.groups()] == [0, 0, 648, 864]

def test_title_defaults_to_region_name_and_dash_suppresses():
    # the finished poster never ships bare: no title -> region name; "-" -> clean map
    from app import session as sess_mod
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 200
    assert sess_mod.get(j["session"])["spec"].title_text == "Lassen County, California"
    assert c.post("/api/proof", data={**data, "title": "-"}).status_code == 200
    assert sess_mod.get(j["session"])["spec"].title_text == ""
    assert c.post("/api/proof", data={**data, "title": "Eagle Lake Loop"}).status_code == 200
    assert sess_mod.get(j["session"])["spec"].title_text == "Eagle Lake Loop"

def test_proof_then_final_happy_path():
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0), "print_w": 9, "print_h": 12}
    r = c.post("/api/proof", data=data)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).size == (864, 1152)
    r2 = c.post("/api/final", data={"session_id": j["session"]})
    assert r2.status_code == 200
    assert Image.open(io.BytesIO(r2.content)).size == (2700, 3600)
