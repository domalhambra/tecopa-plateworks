# tests/test_record_budget.py
"""The record budget reaches every route that writes a manifest with photos in it.

A square-cut photo embeds large, so many of them can push a manifest past PIL's 1 MiB
text chunk, and the file would stop reopening (scripts/track_network.py says why the
record must open with plain PIL). The studio's PNG final was held to the budget first
(Plan B). The time-lapse APNG and the wallpaper bundle now go through the same code
(main._final_with_record): their photos share the 900,000-byte budget, the file reopens
with provenance.extract, and a record that cannot be made is a 422 with no job. A file
with no manifest (WebP, MP4, a share copy) skips the budget, and a file with no photo
is made as it always was."""
import dataclasses
import io
import json
import time
import zipfile

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image

from app import main as _main
from app import provenance, session, timelapse, wallpaper

REGION_DIR = "regions/lassen_ca"
BUDGET = provenance.MAX_RECORD_MANIFEST_BYTES
CROP = {"cx": 0.5, "cy": 0.5}
N_PHOTOS = 40


def _client():
    from fastapi.testclient import TestClient
    return TestClient(_main.app)


def _noisy_jpegs(tmp_path, n, size=(3000, 2000)):
    """Realistic photos: smooth colour blobs under fine grain, which JPEG cannot squeeze."""
    rng = np.random.default_rng(11)
    paths = []
    for k in range(n):
        low = rng.integers(0, 256, (size[1] // 20, size[0] // 20, 3), dtype=np.uint8)
        im = Image.fromarray(low, "RGB").resize(size, Image.BICUBIC)
        arr = np.asarray(im).astype(np.int16) + rng.integers(-40, 40, (size[1], size[0], 3))
        path = tmp_path / f"n{k}.jpg"
        Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB").save(path, "JPEG",
                                                                         quality=88)
        paths.append(str(path))
    return paths


@pytest.fixture(scope="module")
def photos(tmp_path_factory):
    """Forty realistic photos, made once: the plain embedding of them passes the budget."""
    return _noisy_jpegs(tmp_path_factory.mktemp("photos"), N_PHOTOS)


def _crop(j, km_wide=40.0, ar=0.75):
    cfg = json.load(open(f"{REGION_DIR}/region.json"))
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (km_wide * 1000.0 / region_w)
    ch = cw / ar
    x0 = ovw * 0.5 - cw / 2
    y0 = ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch}


def _stamped(c, proof_extra=None, ar=0.75, km_wide=40.0):
    gpx = open("tests/fixtures/sample.gpx", "rb").read()
    j = c.post("/api/upload", files=[("files", ("a.gpx", gpx, "application/gpx+xml"))]).json()
    data = {"session_id": j["session"], **_crop(j, km_wide=km_wide, ar=ar), "print_w": 6, "print_h": 8,
            "title": "Trip"}
    data.update(proof_extra or {})
    r = c.post("/api/proof", data=data)
    assert r.status_code == 200, r.text
    return j["session"]


def _pin_photos(sid, paths, **keys):
    """Pin each photo on the stamped spec, square-cut, spread across its frame."""
    st = session.get(sid)
    spec = st["spec"]
    x0, y0, x1, y1 = spec.crop
    hs = [{"x": x0 + (x1 - x0) * (0.1 + 0.8 * (i % 6) / 5),
           "y": y0 + (y1 - y0) * (0.1 + 0.8 * (i // 6 % 6) / 5),
           "weight": 1, "photo": p, "crop": dict(CROP), **keys}
          for i, p in enumerate(paths)]
    spec = dataclasses.replace(spec, hotspots=hs)
    session.update(sid, spec=spec)
    return spec


def _await_job(c, jid):
    for _ in range(2400):
        s = c.get(f"/api/jobs/{jid}").json()
        if s["state"] in ("done", "error"):
            return s
        time.sleep(0.05)
    raise AssertionError("job never finished")


def _record_size(manifest):
    return len(provenance._manifest_str(manifest))


# ---- the shared helper: one budget for a final, a film, a device file ----

def test_the_plain_embedding_of_many_square_photos_is_over_the_budget(photos):
    # the premise of every test below: without the budget these files would not reopen
    spec = _pin_photos(_stamped(_client()), photos)
    plain = _main._embed_photos(spec, 96)
    assert _record_size(provenance.build_manifest(plain, [], None)) > BUDGET


def test_a_film_record_keeps_its_animation_block_and_the_budget(photos):
    sid = _stamped(_client())
    spec = _pin_photos(sid, photos)
    anim = timelapse.animation_meta(dpi=96, default_image=True, max_frames=15, step_ms=220,
                                    hold_ms=2500, leader_ms=700)
    final, manifest = _main._final_with_record(spec, 96, [], True, [], None,
                                               animation=anim, what="film")
    assert manifest["animation"] == anim
    assert _record_size(manifest) <= BUDGET
    assert provenance.manifest_reads_back(manifest)
    assert all(provenance.is_embedded_photo(h["photo"]) for h in final.hotspots)


def test_a_record_the_tracks_fill_says_film_not_final(photos):
    spec = _pin_photos(_stamped(_client()), photos)
    with pytest.raises(HTTPException) as e:
        _main._final_with_record(spec, 96, [{"filename": "x" * 950_000, "sha256": "",
                                             "bytes": 1}], True, [], None, what="film")
    assert e.value.status_code == 422
    assert "make the film as a share copy" in e.value.detail


# ---- the time-lapse route ----

def test_a_film_of_many_photos_reopens_and_stays_in_the_budget(photos):
    c = _client()
    sid = _stamped(c)
    _pin_photos(sid, photos)
    sub = c.post("/api/timelapse/submit", data={"session_id": sid, "max_frames": 4})
    assert sub.status_code == 200, sub.text
    s = _await_job(c, sub.json()["job"])
    assert s["state"] == "done", s
    data = c.get(s["result"]).content
    m = provenance.extract(data)                           # plain PIL, no raised limit
    assert m is not None
    assert _record_size(m) <= BUDGET
    assert m["animation"]["max_frames"] == 4 and m["animation"]["default_image"] is True
    embedded = [h["photo"] for h in m["spec"]["hotspots"]]
    assert len(embedded) == N_PHOTOS and all(provenance.is_embedded_photo(p) for p in embedded)
    assert Image.open(io.BytesIO(data)).is_animated


def test_a_film_whose_tracks_fill_the_record_is_a_422_and_no_job(photos, monkeypatch):
    c = _client()
    sid = _stamped(c)
    _pin_photos(sid, photos[:3])
    session.update(sid, sources=[{"filename": "x" * 950_000, "sha256": "", "bytes": 1}])
    submitted = []
    monkeypatch.setattr(_main.QUEUE, "submit", lambda *a, **k: submitted.append(a))
    r = c.post("/api/timelapse/submit", data={"session_id": sid, "max_frames": 4})
    assert r.status_code == 422 and "film" in r.json()["detail"]
    assert not submitted


@pytest.mark.parametrize("fmt", ["webp", "mp4"])
def test_a_share_twin_skips_the_budget(photos, monkeypatch, fmt):
    # no manifest in a WebP or an MP4, so no record to budget (and the photos stay as before)
    if fmt == "mp4" and not timelapse.MP4_AVAILABLE:
        pytest.skip("the share extra is not installed")
    c = _client()
    sid = _stamped(c)
    _pin_photos(sid, photos[:3])
    seen = []
    real = _main._final_with_record
    monkeypatch.setattr(_main, "_final_with_record",
                        lambda *a, **k: seen.append(1) or real(*a, **k))
    sub = c.post("/api/timelapse/submit", data={"session_id": sid, "max_frames": 3,
                                                 "format": fmt})
    assert sub.status_code == 200, sub.text
    assert not seen
    assert _await_job(c, sub.json()["job"])["state"] == "done"


def test_a_film_without_photos_is_byte_identical_to_the_worker_alone(monkeypatch):
    # the route's budget step changes nothing for a poster with no photo
    c = _client()
    sid = _stamped(c)
    st = session.get(sid)
    sent = []
    real = _main.QUEUE.submit
    monkeypatch.setattr(_main.QUEUE, "submit",
                        lambda fn, *a, **k: sent.append(a) or real(fn, *a, **k))
    sub = c.post("/api/timelapse/submit", data={"session_id": sid, "max_frames": 4})
    s = _await_job(c, sub.json()["job"])
    assert s["state"] == "done", s
    routed = c.get(s["result"]).content
    tspec, rdir, key, dpi, pacing, sources, embed, lineage, rp = sent[0][:9]
    assert tspec.hotspots == st["spec"].hotspots                  # nothing was changed
    _main._render_timelapse_to_blob(st["spec"], rdir, "test/rb_direct.png", dpi, pacing,
                                    sources, embed, lineage, rp, default_image=True)
    assert routed == open(_main.BLOBS.path("test/rb_direct.png"), "rb").read()


# ---- the wallpaper bundle route ----

def test_a_bundle_of_many_photos_reopens_each_device_file_in_the_budget(photos):
    c = _client()
    p = wallpaper.PRESETS["iphone"]
    sid = _stamped(c, {"output": "wallpaper", "wallpaper_preset": "iphone"}, ar=p.aspect,
                  km_wide=15.0)
    spec = _pin_photos(sid, photos[:12])
    # the budget binds: at the phone's 460 ppi the plain embedding is past it
    assert _record_size(provenance.build_manifest(_main._embed_photos(spec, 460.0),
                                                  [], None)) > BUDGET
    sub = c.post("/api/wallpapers/submit", data={"session_id": sid,
                                                  "presets": "iphone,desktop_fhd"})
    assert sub.status_code == 200, sub.text
    s = _await_job(c, sub.json()["job"])
    assert s["state"] == "done", s
    z = zipfile.ZipFile(io.BytesIO(c.get(s["result"]).content))
    names = [n for n in z.namelist() if n.endswith(".png")]
    assert len(names) == 2
    for n in names:
        m = provenance.extract(z.read(n))
        assert m is not None, n
        assert _record_size(m) <= BUDGET
        embedded = [h["photo"] for h in m["spec"]["hotspots"]]
        assert len(embedded) == 12 and all(provenance.is_embedded_photo(x) for x in embedded)


def test_a_bundle_that_cannot_hold_its_record_is_a_422_and_no_job(photos, monkeypatch):
    c = _client()
    p = wallpaper.PRESETS["iphone"]
    sid = _stamped(c, {"output": "wallpaper", "wallpaper_preset": "iphone"}, ar=p.aspect,
                  km_wide=15.0)
    _pin_photos(sid, photos[:3])
    session.update(sid, sources=[{"filename": "x" * 950_000, "sha256": "", "bytes": 1}])
    submitted = []
    monkeypatch.setattr(_main.QUEUE, "submit", lambda *a, **k: submitted.append(a))
    r = c.post("/api/wallpapers/submit", data={"session_id": sid, "presets": "iphone"})
    assert r.status_code == 422
    assert "wallpaper bundle" in r.json()["detail"] and "iPhone" in r.json()["detail"]
    assert not submitted


def test_a_share_copy_bundle_skips_the_budget(photos, monkeypatch):
    c = _client()
    sid = _stamped(c)
    _pin_photos(sid, photos[:3])
    seen = []
    real = _main._final_with_record
    monkeypatch.setattr(_main, "_final_with_record",
                        lambda *a, **k: seen.append(1) or real(*a, **k))
    sub = c.post("/api/wallpapers/submit", data={"session_id": sid, "presets": "desktop_fhd",
                                                  "embed_spec": "false"})
    assert sub.status_code == 200, sub.text
    assert not seen


def test_a_bundle_without_photos_is_byte_identical_to_the_worker_alone(monkeypatch):
    c = _client()
    sid = _stamped(c)
    st = session.get(sid)
    sent = []
    real = _main.QUEUE.submit
    monkeypatch.setattr(_main.QUEUE, "submit",
                        lambda fn, *a, **k: sent.append(a) or real(fn, *a, **k))
    sub = c.post("/api/wallpapers/submit", data={"session_id": sid, "presets": "desktop_fhd"})
    s = _await_job(c, sub.json()["job"])
    assert s["state"] == "done", s
    routed = c.get(s["result"]).content
    items, rdir, key, cfg, sources, embed, lineage, rp = sent[0][:8]
    assert [i[0].hotspots for i in items] == [st["spec"].hotspots]
    # the same items, as the route built them before this change: the photo-less spec as is
    plain = [(dataclasses.replace(spec, hotspots=list(st["spec"].hotspots)), name)
             for spec, name in items]
    _main._render_bundle_to_blob(plain, rdir, "test/rb_bundle_direct.zip", cfg, sources,
                                 embed, lineage, rp)
    # the zip stamps each member with the clock, so compare the members, not the container
    direct = zipfile.ZipFile(_main.BLOBS.path("test/rb_bundle_direct.zip"))
    got = zipfile.ZipFile(io.BytesIO(routed))
    assert got.namelist() == direct.namelist()
    assert all(got.read(n) == direct.read(n) for n in got.namelist())
