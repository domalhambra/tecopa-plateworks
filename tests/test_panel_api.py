# tests/test_panel_api.py
import functools
import glob
import io
import json
import os
import time
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from app import main, panels, provenance
from tests.test_panels import set_spec

REGION_DIR = "regions/lassen_ca"
SET = {"panels": 2, "panel_gap": 2, "print_w": 36, "print_h": 22}


def _client():
    return TestClient(main.app)


def _upload(c):
    data = open("tests/fixtures/sample.gpx", "rb").read()
    return c.post("/api/upload", files=[("files", ("a.gpx", data, "application/gpx+xml"))]).json()


def _crop(j, km_wide=56.0, ar=36 / 22):
    """A crop in overview pixels, centred on the plate. 56 km holds a 36 in sheet at
    300 dpi inside the 2x rule of a 10 m plate."""
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (km_wide * 1000.0 / region_w); ch = cw / ar
    x0 = ovw * 0.5 - cw / 2; y0 = ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch}


def _proof(c, **over):
    j = _upload(c)
    r = c.post("/api/proof", data={"session_id": j["session"], **_crop(j), "title": "Set",
                                   **SET, **over})
    return j, r


def test_a_proof_of_a_set_shows_the_gap_in_the_wall_tone():
    c = _client()
    _, r = _proof(c)
    assert r.status_code == 200, r.text
    img = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"))
    assert img.shape == (2112, 3456, 3)                      # 22 x 36 in at 96 dpi
    assert (img[:, 1632:1824] == panels.WALL_TONE).all()     # 17 in, then a 2 in strip
    assert not (img[:, 1600:1632] == panels.WALL_TONE).all()


def test_a_set_with_a_wrong_sheet_is_a_422_that_names_both_sheets():
    c = _client()
    j = _upload(c)
    r = c.post("/api/proof", data={"session_id": j["session"], **_crop(j, ar=34 / 22),
                                   **SET, "print_w": 34})
    assert r.status_code == 422
    assert "46x17 or 36x22 in" in r.json()["detail"]


def test_a_single_sheet_proof_is_not_touched():
    c = _client()
    j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=40.0, ar=0.75),
            "print_w": 6, "print_h": 8}
    a = c.post("/api/proof", data=data)
    b = c.post("/api/proof", data={**data, "panels": 1, "panel_gap": 0})
    assert a.status_code == b.status_code == 200 and a.content == b.content


def test_the_proof_form_carries_both_fields():
    form = main._proof_form_for(set_spec(3, 2.0, "wide"))
    assert form["panels"] == 3 and form["panel_gap"] == 2.0
    assert type(form["panels"]) is int and type(form["panel_gap"]) is float


def _fake_sheet(spec, dpi=10):
    w, h = spec.pixel_size(dpi)
    rng = np.random.default_rng(3)
    return Image.fromarray(rng.integers(0, 255, (h, w, 3), dtype=np.uint8))


def test_the_delivery_of_a_set_is_a_zip_of_one_file_per_panel():
    spec = set_spec(2, 2.0, "tall", region_id="lassen_ca")
    manifest = provenance.build_manifest(spec, [])
    sheet = _fake_sheet(spec)
    data = main._encode_delivery(sheet, spec, "png", manifest, 10)
    again = main._encode_delivery(sheet, spec, "png", manifest, 10)
    assert data == again                                      # invariant 3
    z = zipfile.ZipFile(io.BytesIO(data))
    assert z.namelist() == ["tecopa_lassen_ca_1of2.png", "tecopa_lassen_ca_2of2.png"]
    assert all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in z.infolist())
    # stored, not deflated (a PNG is compressed already), and a plain file mode
    assert all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist())
    assert all(i.external_attr >> 16 == 0o644 for i in z.infolist())
    parts = panels.cut(sheet, spec, 10)
    for k, name in enumerate(z.namelist(), 1):
        png = z.read(name)
        assert np.array_equal(np.asarray(Image.open(io.BytesIO(png))), np.asarray(parts[k - 1]))
        m = provenance.extract(png)
        assert m["panel"] == {"index": k, "of": 2}
        assert m["spec"]["panels"] == 2 and m["spec"]["panel_gap_in"] == 2.0
    assert main._delivery_name(spec, "png") == "tecopa_lassen_ca_panels.zip"
    assert main._delivery_media(spec, "png") == "application/zip"


def test_the_delivery_of_a_single_sheet_is_the_file_itself():
    spec = set_spec(2, 2.0, "tall", region_id="lassen_ca", panels=1, panel_gap_in=0.0)
    manifest = provenance.build_manifest(spec, [])
    sheet = _fake_sheet(spec)
    assert main._encode_delivery(sheet, spec, "png", manifest, 10) == main._encode_final(
        sheet, "png", manifest, dpi=10)
    assert "panel" not in provenance.extract(main._encode_delivery(sheet, spec, "png", manifest, 10))
    assert main._delivery_name(spec, "png") == "tecopa_lassen_ca.png"
    assert main._delivery_media(spec, "pdf") == "application/pdf"


def test_a_share_copy_of_a_set_carries_no_manifest():
    spec = set_spec(2, 0.0, "tall", region_id="lassen_ca")
    z = zipfile.ZipFile(io.BytesIO(main._encode_delivery(_fake_sheet(spec), spec, "png", None, 10)))
    assert all(provenance.extract(z.read(n)) is None for n in z.namelist())


def test_a_pdf_set_is_a_zip_of_one_page_per_panel():
    spec = set_spec(3, 0.0, "wide", region_id="lassen_ca")
    z = zipfile.ZipFile(io.BytesIO(main._encode_delivery(_fake_sheet(spec), spec, "pdf", None, 10)))
    assert z.namelist() == [f"tecopa_lassen_ca_{k}of3.pdf" for k in (1, 2, 3)]
    assert all(z.read(n).startswith(b"%PDF") for n in z.namelist())
    # both formats are a zip, so the PDF one says so in its name
    assert main._delivery_name(spec, "pdf") == "tecopa_lassen_ca_panels_pdf.zip"
    assert main._delivery_media(spec, "pdf") == "application/zip"


def _flat_raster(monkeypatch):
    """Replace the painter with a flat sheet of the right size, so a test of the wiring
    around it does not pay for a render."""
    def flat(spec, dpi, region_dir, **kw):
        return Image.new("RGB", spec.pixel_size(dpi), (10, 20, 30))
    monkeypatch.setattr(main.render, "rasterize", flat)


def test_the_refine_of_a_set_shows_the_gap_in_the_wall_tone(monkeypatch):
    # the sharp image replaces the draft in the studio, so it must hang the same way
    _flat_raster(monkeypatch)
    spec = set_spec(2, 2.0, "tall", region_id="lassen_ca")
    key = main._render_refine_to_blob(spec, REGION_DIR, "test_panel_api/refine.png")
    img = np.asarray(Image.open(main.BLOBS.path(key)).convert("RGB"))
    assert main._refine_dpi(spec) == 200
    assert img.shape == (4400, 7200, 3)                      # 22 x 36 in at 200 dpi
    assert (img[:, 3400:3800] == panels.WALL_TONE).all()
    assert (img[:, :3400] == (10, 20, 30)).all() and (img[:, 3800:] == (10, 20, 30)).all()


def test_the_synchronous_final_of_a_set_is_the_same_zip(monkeypatch):
    _flat_raster(monkeypatch)
    c = _client()
    j = _upload(c)
    crop = _crop(j)
    spec, _ = main._build_spec(j["session"], (crop["x0"], crop["y0"], crop["x1"], crop["y1"]),
                               36, 22, style={"panels": 2, "panel_gap_in": 2.0})
    main.session.update(j["session"], spec=spec)             # as a clean proof stamps it
    out = c.post("/api/final", data={"session_id": j["session"]})
    assert out.status_code == 200, out.text
    assert out.headers["content-type"] == "application/zip"
    assert 'filename="tecopa_lassen_ca' in out.headers["content-disposition"]
    assert "_panels.zip" in out.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(out.content))
    assert [n[-9:] for n in z.namelist()] == ["_1of2.png", "_2of2.png"]
    for k, name in enumerate(z.namelist(), 1):
        png = z.read(name)
        assert Image.open(io.BytesIO(png)).size == (5100, 6600)
        m = provenance.extract(png)
        assert m["panel"] == {"index": k, "of": 2} and m["spec"]["panels"] == 2


def _wait(c, jid, seconds=600):
    for _ in range(seconds * 4):
        s = c.get(f"/api/jobs/{jid}").json()
        if s["state"] in ("done", "error"):
            return s
        time.sleep(0.25)
    raise AssertionError("the job did not end")


def test_a_final_of_a_set_is_a_zip_job():
    c = _client()
    j, r = _proof(c)
    assert r.status_code == 200, r.text
    jid = c.post("/api/final/submit", data={"session_id": j["session"]}).json()["job"]
    s = _wait(c, jid)
    assert s["state"] == "done", s
    out = c.get(s["result"])
    assert out.headers["content-type"] == "application/zip"
    assert "_panels.zip" in out.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(out.content))
    assert len(z.namelist()) == 2
    for name in z.namelist():
        assert Image.open(io.BytesIO(z.read(name))).size == (5100, 6600)


def test_a_set_is_refused_by_the_film_and_wallpaper_routes():
    c = _client()
    j, r = _proof(c)
    assert r.status_code == 200, r.text
    film = c.post("/api/timelapse/submit", data={"session_id": j["session"]})
    assert film.status_code == 422 and "set of panels" in film.json()["detail"]
    wall = c.post("/api/wallpapers/submit", data={"session_id": j["session"],
                                                  "presets": "ig_portrait"})
    assert wall.status_code == 422 and "set of panels" in wall.json()["detail"]


def test_inspect_names_the_panel_of_a_set():
    spec = set_spec(3, 2.0, "wide", region_id="lassen_ca")
    manifest = provenance.build_manifest(spec, [])
    z = zipfile.ZipFile(io.BytesIO(main._encode_delivery(_fake_sheet(spec), spec, "png",
                                                         manifest, 10)))
    png = z.read(z.namelist()[1])
    body = _client().post("/api/reprint/inspect",
                          files={"file": ("p.png", png, "image/png")}).json()
    assert body["panels"] == 3 and body["panel_gap_in"] == 2.0
    assert body["panel"] == {"index": 2, "of": 3}
    assert body["print_size_in"] == [70.0, 17.0]


def test_inspect_of_a_single_sheet_says_one_panel():
    c = _client()
    j = _upload(c)
    c.post("/api/proof", data={"session_id": j["session"], **_crop(j, 40.0, 0.75),
                               "print_w": 6, "print_h": 8})
    png = c.post("/api/final", data={"session_id": j["session"]}).content
    body = c.post("/api/reprint/inspect", files={"file": ("p.png", png, "image/png")}).json()
    assert body["panels"] == 1 and body["panel_gap_in"] == 0.0 and body["panel"] is None


def test_any_panel_reprints_the_whole_set():
    c = _client()
    j, r = _proof(c)
    assert r.status_code == 200, r.text
    first = c.post("/api/final", data={"session_id": j["session"]})
    assert first.headers["content-type"] == "application/zip"
    z1 = zipfile.ZipFile(io.BytesIO(first.content))
    panel_two = z1.read(z1.namelist()[1])
    again = c.post("/api/reprint", files={"file": ("two.png", panel_two, "image/png")})
    assert again.status_code == 200, again.text
    assert again.headers["content-type"] == "application/zip"
    assert "_panels.zip" in again.headers["content-disposition"]
    z2 = zipfile.ZipFile(io.BytesIO(again.content))
    assert z2.namelist() == z1.namelist()
    for name in z1.namelist():
        a = np.asarray(Image.open(io.BytesIO(z1.read(name))).convert("RGB"))
        b = np.asarray(Image.open(io.BytesIO(z2.read(name))).convert("RGB"))
        assert np.array_equal(a, b), name
        assert provenance.extract(z2.read(name))["panel"] == provenance.extract(z1.read(name))["panel"]


def test_a_film_file_that_claims_a_set_is_refused_on_reprint():
    # no route makes a film of a set, so a file with both was crafted: a 422, no job
    c = _client()
    _, spec = _stamp_a_set(c)
    manifest = provenance.build_manifest(spec, [])
    manifest["animation"] = {"max_frames": 8, "step_ms": 90, "hold_ms": 900,
                             "leader_ms": 0, "dpi": 20}
    buf = io.BytesIO()
    Image.new("RGB", (16, 16)).save(buf, "PNG", pnginfo=provenance.manifest_pnginfo(manifest))
    r = c.post("/api/reprint", files={"file": ("f.png", buf.getvalue(), "image/png")})
    assert r.status_code == 422 and "set of panels has no film" in r.json()["detail"]


def _stamp_a_set(c):
    """A stamped set session that costs no render: the spec is built and stored the
    way a clean proof stores it."""
    j = _upload(c)
    crop = _crop(j)
    spec, _ = main._build_spec(j["session"], (crop["x0"], crop["y0"], crop["x1"], crop["y1"]),
                               36, 22, style={"panels": 2, "panel_gap_in": 2.0})
    main.session.update(j["session"], spec=spec)
    return j["session"], spec


def test_a_pdf_final_of_a_set_does_not_replace_the_png_one(monkeypatch):
    # both are zips, so the format is in the name: one session holds both blobs
    _flat_raster(monkeypatch)
    c = _client()
    sid, spec = _stamp_a_set(c)
    assert main._delivery_name(spec, "png") != main._delivery_name(spec, "pdf")
    jobs = {fmt: c.post("/api/final/submit", data={"session_id": sid, "format": fmt}).json()["job"]
            for fmt in ("png", "pdf")}
    done = {fmt: _wait(c, jid) for fmt, jid in jobs.items()}
    assert all(s["state"] == "done" for s in done.values()), done
    keys = {fmt: main.QUEUE.status(jid)["result"] for fmt, jid in jobs.items()}
    assert keys["png"].endswith("_panels.zip") and keys["pdf"].endswith("_panels_pdf.zip")
    for fmt, magic in (("png", b"\x89PNG"), ("pdf", b"%PDF")):
        out = c.get(done[fmt]["result"])
        assert out.status_code == 200
        assert out.headers["content-type"] == "application/zip"
        assert os.path.basename(keys[fmt]) in out.headers["content-disposition"]
        z = zipfile.ZipFile(io.BytesIO(out.content))
        assert [n[-9:] for n in z.namelist()] == [f"_1of2.{fmt}", f"_2of2.{fmt}"]
        assert all(z.read(n).startswith(magic) for n in z.namelist())


def test_a_panel_file_continues_as_the_set():
    """The poster is the save file, and so is any one panel of a set: /api/continue
    restores the set, and its proof_form proofs the same sheet again."""
    from tests.test_editions import _as_form
    c = _client()
    j, r = _proof(c)
    assert r.status_code == 200, r.text
    st = main.session.get(j["session"])
    first = st["spec"]
    manifest = main._final_manifest(first, st.get("sources", []), True, [])
    z = zipfile.ZipFile(io.BytesIO(main._encode_delivery(_fake_sheet(first), first, "png",
                                                         manifest, 10)))
    panel_two = z.read(z.namelist()[1])
    r = c.post("/api/continue", files={"file": ("two.png", panel_two, "image/png")})
    assert r.status_code == 200, r.text
    cont = r.json()
    pre, form = cont["prefill"], cont["proof_form"]
    assert pre["panels"] == 2 and pre["panel_gap_in"] == 2.0
    assert (pre["print_w_in"], pre["print_h_in"]) == (36.0, 22.0)
    assert pre["edition"] == 2
    assert form["panels"] == 2 and form["panel_gap"] == 2.0
    assert (form["print_w"], form["print_h"]) == (36.0, 22.0)
    x0, y0, x1, y1 = cont["starter_crop"]
    r = c.post("/api/proof", data={"session_id": cont["session"], "x0": x0, "y0": y0,
                                   "x1": x1, "y1": y1, **_as_form(form)})
    assert r.status_code == 200, r.text
    assert Image.open(io.BytesIO(r.content)).size == (3456, 2112)     # 36 x 22 in at 96 dpi
    second = main.session.get(cont["session"])["spec"]
    assert (second.panels, second.panel_gap_in) == (2, 2.0)
    assert (second.print_w_in, second.print_h_in) == (36.0, 22.0)
    assert second.edition == first.edition + 1
    assert max(abs(p - q) for p, q in zip(first.crop, second.crop)) < 1e-3


def test_one_panel_of_a_set_makes_a_mockup_of_that_panel():
    # the mockup route reads the pixels of the file it gets and nothing else of the
    # set, so a panel file is staged as the one sheet it is. The zip is not a PNG.
    spec = set_spec(2, 2.0, "tall", region_id="lassen_ca", title_text="Set")
    data = main._encode_delivery(_fake_sheet(spec, 20), spec, "png",
                                 provenance.build_manifest(spec, []), 20)
    z = zipfile.ZipFile(io.BytesIO(data))
    c = _client()
    r = c.post("/api/mockups/submit",
               files={"file": ("two.png", z.read(z.namelist()[1]), "image/png")},
               data={"variants": "frame", "sizes": "540x540"})
    assert r.status_code == 200, r.text
    s = _wait(c, r.json()["job"])
    assert s["state"] == "done", s
    out = zipfile.ZipFile(io.BytesIO(c.get(s["result"]).content))
    assert out.namelist() == ["mockup_frame_540x540.jpg"]
    whole = c.post("/api/mockups/submit", files={"file": ("set.zip", data, "application/zip")})
    assert whole.status_code == 422 and "not a PNG" in whole.json()["detail"]


# ---- /api/reprint/inspect builds no spec, so it types every field it reports ----
# The manifest of an uploaded file is untrusted. /api/reprint and /api/continue send it
# through provenance.spec_from_manifest and answer 422. Inspect is the one route that
# reads the fields raw, so each field has a type and a fallback, and no file that
# provenance.extract returns can make the reply a 500.

NAN, INF = float("nan"), float("inf")
LONE = "a\ud800"                 # what json.loads gives for the JSON text "a\\ud800"
INSPECT_KEYS = ["manifest_version", "engine", "region_id", "region_available", "sources",
                "print_size_in", "panels", "panel_gap_in", "panel", "title", "tracks",
                "hotspots", "edition", "lineage", "animation", "plate", "plate_file",
                "plate_server"]


def _nested(depth):
    """A list in a list, `depth` deep. Built in a loop: no recursion in the test."""
    v = []
    for _ in range(depth - 1):
        v = [v]
    return v


def _short(v):
    """A test id for a hostile value: its start only. A string of 900 kB is not a name."""
    if isinstance(v, tuple):
        return "/".join(v)
    text = v if isinstance(v, str) else repr(v)
    return text if len(text) <= 32 else f"{text[:24]}...{len(text)}"


def _honest():
    """The manifest of panel 2 of a set of 3: a well-formed file."""
    spec = set_spec(3, 2.0, "wide", region_id="lassen_ca", title_text="Set")
    sources = [{"filename": "a.gpx", "sha256": "ab" * 32, "bytes": 3}]
    return {**provenance.build_manifest(spec, sources), "panel": {"index": 2, "of": 3}}


def _put(manifest, path, value):
    """A copy of the manifest with `value` at `path`. A `spec` or `panel` that is not
    a dict is replaced by one, so a path can go through it."""
    m = json.loads(json.dumps(manifest))
    node = m
    for key in path[:-1]:
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    node[path[-1]] = value
    return m


def test_inspect_reads_a_well_formed_set_as_it_is():
    f = main._inspect_fields(_honest())
    assert f == {"manifest_version": 1, "engine": "tecopa-plateworks",
                 "region_id": "lassen_ca",
                 "sources": [{"filename": "a.gpx", "sha256": "ab" * 32, "bytes": 3}],
                 "print_size_in": [70.0, 17.0], "panels": 3, "panel_gap_in": 2.0,
                 "panel": {"index": 2, "of": 3}, "title": "Set", "tracks": 1,
                 "hotspots": 0, "edition": 1, "lineage": [], "animation": None}
    assert type(f["panels"]) is int and type(f["panel_gap_in"]) is float


def _raw_read(m):
    """What inspect reported before it typed its fields: each key read as given."""
    s = m["spec"]
    return {"manifest_version": m.get("manifest_version"), "engine": m.get("engine"),
            "region_id": s.get("region_id") or m.get("region_id"),
            "sources": m.get("sources", []),
            "print_size_in": [s.get("print_w_in"), s.get("print_h_in")],
            "panels": s.get("panels", 1), "panel_gap_in": s.get("panel_gap_in", 0.0),
            "panel": m.get("panel"), "title": s.get("title_text", ""),
            "tracks": len(s.get("tracks", []) or []),
            "hotspots": len(s.get("hotspots", []) or []),
            "edition": m.get("edition", s.get("edition", 1)),
            "lineage": m.get("lineage", []), "animation": m.get("animation")}


@pytest.mark.parametrize("path", sorted(glob.glob("tests/fixtures/manifest_*.json")))
def test_a_frozen_manifest_reads_the_same_typed_as_raw(path):
    # the typed read changes nothing for a well-formed file, old or new
    m = json.load(open(path))
    assert main._inspect_fields(m) == _raw_read(m)
    assert main._inspect_fields(_honest()) == _raw_read(_honest())


@pytest.mark.parametrize("path,value,want", [
    # panels: an int that is 1, 2 or 3. Anything else is a single sheet.
    (("spec", "panels"), 2, {"panels": 2, "panel": None}),      # the panel says "of 3"
    (("spec", "panels"), 1, {"panels": 1, "panel_gap_in": 0.0, "panel": None}),
    (("spec", "panels"), 4, {"panels": 1, "panel_gap_in": 0.0, "panel": None}),
    (("spec", "panels"), 0, {"panels": 1, "panel_gap_in": 0.0, "panel": None}),
    (("spec", "panels"), 3.0, {"panels": 1, "panel_gap_in": 0.0, "panel": None}),
    (("spec", "panels"), True, {"panels": 1, "panel_gap_in": 0.0, "panel": None}),
    (("spec", "panels"), "3", {"panels": 1, "panel_gap_in": 0.0, "panel": None}),
    (("spec", "panels"), NAN, {"panels": 1, "panel_gap_in": 0.0, "panel": None}),
    (("spec", "panels"), INF, {"panels": 1, "panel_gap_in": 0.0, "panel": None}),
    (("spec", "panels"), [3], {"panels": 1, "panel_gap_in": 0.0, "panel": None}),
    (("spec", "panels"), None, {"panels": 1, "panel_gap_in": 0.0, "panel": None}),
    (("spec", "panels"), 10 ** 400, {"panels": 1, "panel_gap_in": 0.0, "panel": None}),
    # panel_gap_in: 0, 2 or 4 as a float. Anything else is 0.
    (("spec", "panel_gap_in"), 4.0, {"panel_gap_in": 4.0}),
    (("spec", "panel_gap_in"), 4, {"panel_gap_in": 4.0}),
    (("spec", "panel_gap_in"), 0, {"panel_gap_in": 0.0}),
    (("spec", "panel_gap_in"), 1.0, {"panel_gap_in": 0.0}),
    (("spec", "panel_gap_in"), -2.0, {"panel_gap_in": 0.0}),
    (("spec", "panel_gap_in"), NAN, {"panel_gap_in": 0.0}),
    (("spec", "panel_gap_in"), INF, {"panel_gap_in": 0.0}),
    (("spec", "panel_gap_in"), "2", {"panel_gap_in": 0.0}),
    (("spec", "panel_gap_in"), False, {"panel_gap_in": 0.0}),
    (("spec", "panel_gap_in"), [2.0], {"panel_gap_in": 0.0}),
    (("spec", "panel_gap_in"), 10 ** 400, {"panel_gap_in": 0.0}),
    # panel: index and of are ints, of is the count of the spec, index is in the set
    (("panel",), {"index": 1, "of": 3, "more": "x" * 999}, {"panel": {"index": 1, "of": 3}}),
    (("panel",), {"index": 3, "of": 3}, {"panel": {"index": 3, "of": 3}}),
    (("panel",), {"index": 4, "of": 3}, {"panel": None}),
    (("panel",), {"index": 0, "of": 3}, {"panel": None}),
    (("panel",), {"index": 1, "of": 2}, {"panel": None}),
    (("panel",), {"index": 9, "of": 9}, {"panel": None}),
    (("panel",), {"index": True, "of": 3}, {"panel": None}),
    (("panel",), {"index": 1.0, "of": 3}, {"panel": None}),
    (("panel",), {"index": 1, "of": 3.0}, {"panel": None}),
    (("panel",), {"index": NAN, "of": 3}, {"panel": None}),
    (("panel",), {"index": 1}, {"panel": None}),
    (("panel",), {}, {"panel": None}),
    (("panel",), None, {"panel": None}),
    (("panel",), NAN, {"panel": None}),
    (("panel",), INF, {"panel": None}),
    (("panel",), 2, {"panel": None}),
    (("panel",), [2, 3], {"panel": None}),
    (("panel",), "<script>alert(1)</script>", {"panel": None}),
    (("panel",), "A" * 900_000, {"panel": None}),
    (("panel",), _nested(3000), {"panel": None}),
    # the sheet: two finite numbers, or neither
    (("spec", "print_w_in"), 36, {"print_size_in": [36, 17.0]}),
    (("spec", "print_w_in"), NAN, {"print_size_in": [None, None]}),
    (("spec", "print_h_in"), INF, {"print_size_in": [None, None]}),
    (("spec", "print_h_in"), -INF, {"print_size_in": [None, None]}),
    (("spec", "print_w_in"), "70", {"print_size_in": [None, None]}),
    (("spec", "print_w_in"), True, {"print_size_in": [None, None]}),
    (("spec", "print_w_in"), [70.0], {"print_size_in": [None, None]}),
    (("spec", "print_w_in"), None, {"print_size_in": [None, None]}),
    (("spec", "print_w_in"), 10 ** 400, {"print_size_in": [None, None]}),
    # the title: a string, cut at the length a spec allows
    (("spec", "title_text"), "x" * 200, {"title": "x" * 200}),
    (("spec", "title_text"), "A" * 900_000, {"title": "A" * 200}),
    (("spec", "title_text"), ["a"], {"title": ""}),
    (("spec", "title_text"), {"a": 1}, {"title": ""}),
    (("spec", "title_text"), 7, {"title": ""}),
    (("spec", "title_text"), None, {"title": ""}),
    # the counts: of a list only
    (("spec", "tracks"), "abc", {"tracks": 0}),
    (("spec", "tracks"), {"a": 1}, {"tracks": 0}),
    (("spec", "tracks"), 5, {"tracks": 0}),
    (("spec", "tracks"), None, {"tracks": 0}),
    (("spec", "tracks"), [1, 2, 3], {"tracks": 3}),
    (("spec", "hotspots"), "abc", {"hotspots": 0}),
    (("spec", "hotspots"), NAN, {"hotspots": 0}),
    (("spec", "hotspots"), [{}, {}], {"hotspots": 2}),
    # the region: a string that can be a folder name. spec.region_id goes first.
    (("spec", "region_id"), ["lassen_ca"], {"region_id": None}),
    (("spec", "region_id"), {"a": 1}, {"region_id": None}),
    (("spec", "region_id"), 7, {"region_id": None}),
    (("spec", "region_id"), NAN, {"region_id": None}),
    (("spec", "region_id"), "A" * 900_000, {"region_id": None}),
    (("spec", "region_id"), "atlantis", {"region_id": "atlantis"}),
    (("spec", "region_id"), None, {"region_id": "lassen_ca"}),      # the top-level one
    # the edition: 1 to 999. The top-level key goes first, as it did.
    (("edition",), 3, {"edition": 3}),
    (("edition",), 0, {"edition": 1}),
    (("edition",), 1000, {"edition": 1}),
    (("edition",), 2.0, {"edition": 1}),
    (("edition",), True, {"edition": 1}),
    (("edition",), "3", {"edition": 1}),
    (("edition",), NAN, {"edition": 1}),
    (("edition",), [3], {"edition": 1}),
    (("spec", "edition"), 5, {"edition": 5}),
    (("spec", "edition"), INF, {"edition": 1}),
    # lineage and sources: a list of plain JSON, nested as a record is. Else empty.
    (("lineage",), [{"sha256": "1" * 64, "edition": 1}],
     {"lineage": [{"sha256": "1" * 64, "edition": 1}]}),
    (("lineage",), {"a": 1}, {"lineage": []}),
    (("lineage",), "abc", {"lineage": []}),
    (("lineage",), NAN, {"lineage": []}),
    (("lineage",), [{"edition": NAN}], {"lineage": []}),
    (("lineage",), [INF], {"lineage": []}),
    (("lineage",), _nested(3000), {"lineage": []}),
    (("lineage",), _nested(9), {"lineage": []}),
    (("lineage",), _nested(8), {"lineage": _nested(8)}),
    (("sources",), None, {"sources": []}),
    (("sources",), "abc", {"sources": []}),
    (("sources",), [{"bytes": -INF}], {"sources": []}),
    (("sources",), _nested(3000), {"sources": []}),
    # animation: a dict of plain JSON, or the file is a still
    (("animation",), {"max_frames": 6, "dpi": 96.0}, {"animation": {"max_frames": 6, "dpi": 96.0}}),
    (("animation",), {"dpi": NAN}, {"animation": None}),
    (("animation",), {"a": _nested(3000)}, {"animation": None}),
    (("animation",), [1], {"animation": None}),
    (("animation",), "film", {"animation": None}),
    (("animation",), INF, {"animation": None}),
    # the two labels of the file itself
    (("manifest_version",), 2, {"manifest_version": 2}),
    (("manifest_version",), NAN, {"manifest_version": None}),
    (("manifest_version",), 1.0, {"manifest_version": None}),
    (("manifest_version",), True, {"manifest_version": None}),
    (("manifest_version",), "1", {"manifest_version": None}),
    (("manifest_version",), 10 ** 400, {"manifest_version": None}),
    (("manifest_version",), [1], {"manifest_version": None}),
    (("engine",), "trailprint", {"engine": "trailprint"}),
    (("engine",), "A" * 900_000, {"engine": None}),
    (("engine",), NAN, {"engine": None}),
    (("engine",), ["tecopa-plateworks"], {"engine": None}),
    # half of a surrogate pair: JSON text can hold it, and UTF-8 cannot send it back
    (("spec", "title_text"), LONE, {"title": ""}),
    (("spec", "region_id"), LONE, {"region_id": None}),
    (("engine",), LONE, {"engine": None}),
    (("sources",), [{"filename": LONE}], {"sources": []}),
    (("lineage",), [{LONE: 1}], {"lineage": []}),
    (("animation",), {"note": [LONE]}, {"animation": None}),
], ids=_short)
def test_inspect_types_each_field_and_leaves_its_neighbours(path, value, want):
    honest = main._inspect_fields(_honest())
    got = main._inspect_fields(_put(_honest(), path, value))
    assert got == {**honest, **want}
    json.dumps(got, allow_nan=False)                 # raises on NaN or Infinity


@pytest.mark.parametrize("spec", [None, [], [1, 2], "spec", 7, NAN, True, _nested(3000)],
                         ids=_short)
def test_inspect_reads_a_spec_that_is_not_a_dict_as_an_empty_one(spec):
    got = main._inspect_fields({**_honest(), "spec": spec})
    assert got == {"manifest_version": 1, "engine": "tecopa-plateworks",
                   "region_id": "lassen_ca",              # the top-level one
                   "sources": [{"filename": "a.gpx", "sha256": "ab" * 32, "bytes": 3}],
                   "print_size_in": [None, None], "panels": 1, "panel_gap_in": 0.0,
                   "panel": None, "title": "", "tracks": 0, "hotspots": 0, "edition": 1,
                   "lineage": [], "animation": None}


def test_a_stray_panel_key_on_a_single_sheet_is_not_reported():
    # the review's file: one sheet, and a panel key that says 2 of 3
    m = _put(_put(_honest(), ("spec", "panels"), 1), ("spec", "panel_gap_in"), 0.0)
    got = main._inspect_fields(m)
    assert (got["panels"], got["panel_gap_in"], got["panel"]) == (1, 0.0, None)


def test_an_inspect_reply_that_cannot_be_json_drops_its_free_form_parts():
    # the last guard: the route encodes its reply once, here, and never as a 500
    for bad in (NAN, INF, LONE):
        reply = {"panels": 1, "sources": [bad], "lineage": [bad], "animation": {"dpi": bad}}
        r = main._inspect_response(reply)
        assert r.status_code == 200 and r.media_type == "application/json"
        assert json.loads(r.body) == {"panels": 1, "sources": [], "lineage": [],
                                      "animation": None}
    assert json.loads(main._inspect_response({"panels": 3, "sources": [1]}).body) == {
        "panels": 3, "sources": [1]}


# The same, through the route. A hostile value is given as JSON text, because
# json.dumps cannot write 1e999 and cannot write 3,000 lists in each other.
HOSTILE = {
    "nan": "NaN", "inf": "Infinity", "neg_inf": "-Infinity", "1e999": "1e999",
    "int_of_4000_digits": "1" + "0" * 3999,
    "lists_3000_deep": "[" * 3000 + "]" * 3000,
    "lists_600_deep": "[" * 600 + "]" * 600,
    "string_of_900_kb": '"' + "A" * 900_000 + '"',
    "script": '"<script>alert(1)</script>"',
    "list": "[1, 2]", "dict": '{"index": 2, "of": 3}', "true": "true", "null": "null",
    "number": "2.5", "empty_string": '""',
    "lone_surrogate": '"a\\ud800"', "lone_surrogate_in_a_list": '[{"a\\ud800": "\\udfff"}]',
}
# Each place a hostile value goes, and the keys of the reply it is allowed to change.
PLATE = {"plate", "plate_file", "plate_server"}
HOLES = {
    ("panel",): {"panel"},
    ("panel", "index"): {"panel"},
    ("panel", "of"): {"panel"},
    ("spec",): {"print_size_in", "panels", "panel_gap_in", "panel", "title", "tracks",
                "hotspots", "edition"} | PLATE,
    ("spec", "panels"): {"panels", "panel_gap_in", "panel"},
    ("spec", "panel_gap_in"): {"panel_gap_in"},
    ("spec", "print_w_in"): {"print_size_in"},
    ("spec", "print_h_in"): {"print_size_in"},
    ("spec", "title_text"): {"title"},
    ("spec", "tracks"): {"tracks"},
    ("spec", "hotspots"): {"hotspots"},
    ("spec", "edition"): {"edition"},
    ("spec", "labels"): PLATE,
    ("spec", "region_id"): {"region_id", "region_available"} | PLATE,
    ("region_id",): set(),                                   # spec.region_id goes first
    ("edition",): {"edition"},
    ("lineage",): {"lineage"},
    ("sources",): {"sources"},
    ("animation",): {"animation"},
    ("manifest_version",): {"manifest_version"},
    ("engine",): {"engine"},
    ("region_pack",): PLATE,
    ("region_pack", "pack_version"): PLATE,
}
HOLE = "@@hostile@@"


def _png_with_text(text):
    info = PngInfo()
    info.add_text(provenance.MANIFEST_KEY, text, zip=True)
    buf = io.BytesIO()
    Image.new("RGB", (16, 16)).save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


def _inspect(c, text):
    return c.post("/api/reprint/inspect", files={"file": ("p.png", _png_with_text(text),
                                                          "image/png")})


@functools.cache
def _honest_reply():
    """What inspect says of the well-formed file. Asked for once: each inspect hashes
    the plate, and the cases below are many."""
    r = _inspect(_client(), json.dumps(_honest()))
    assert r.status_code == 200, r.text
    return r.json()


def _assert_typed(b):
    """The type of every key of an inspect reply, whatever the file said."""
    assert list(b) == INSPECT_KEYS
    assert b["manifest_version"] is None or type(b["manifest_version"]) is int
    assert b["engine"] is None or (type(b["engine"]) is str and len(b["engine"]) <= 64)
    assert b["region_id"] is None or (type(b["region_id"]) is str and len(b["region_id"]) <= 255)
    assert type(b["region_available"]) is bool
    assert type(b["sources"]) is list and type(b["lineage"]) is list
    assert b["animation"] is None or type(b["animation"]) is dict
    w, h = b["print_size_in"]
    assert (w is None and h is None) or all(
        type(v) in (int, float) and abs(v) <= 1e6 for v in (w, h))
    assert type(b["panels"]) is int and b["panels"] in (1, 2, 3)
    assert type(b["panel_gap_in"]) is float and b["panel_gap_in"] in (0.0, 2.0, 4.0)
    assert b["panels"] > 1 or b["panel_gap_in"] == 0.0
    if b["panel"] is not None:
        assert sorted(b["panel"]) == ["index", "of"]
        index, of = b["panel"]["index"], b["panel"]["of"]
        assert type(index) is int and type(of) is int
        assert of == b["panels"] > 1 and 1 <= index <= of
    assert type(b["title"]) is str and len(b["title"]) <= 200
    assert type(b["tracks"]) is int and type(b["hotspots"]) is int
    assert type(b["edition"]) is int and 1 <= b["edition"] <= 999
    assert b["plate"] in ("verified", "mismatch", "unverifiable", "region_missing")
    assert b["plate_file"] is None or (type(b["plate_file"]) is str and len(b["plate_file"]) == 12)
    assert b["plate_server"] is None or type(b["plate_server"]) is str


@pytest.mark.parametrize("value", sorted(HOSTILE))
@pytest.mark.parametrize("path", sorted(HOLES), ids="/".join)
def test_inspect_never_answers_500_and_always_answers_typed(path, value):
    honest = _honest_reply()
    text = json.dumps(_put(_honest(), path, HOLE)).replace(json.dumps(HOLE), HOSTILE[value])
    r = _inspect(_client(), text)
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"] == "application/json"
    body = r.json()
    _assert_typed(body)
    # a reply is small: a long string or a deep list in the file is not sent back
    assert len(r.content) < 2_000
    assert "[[[[[[[[[" not in r.text and "Infinity" not in r.text and "NaN" not in r.text
    # one bad value does not change what the other keys say
    same = [k for k in INSPECT_KEYS if k not in HOLES[path]]
    assert {k: body[k] for k in same} == {k: honest[k] for k in same}


def test_inspect_of_a_crafted_panel_key_is_a_reply_and_not_a_500():
    # the review's reproduction, value for value
    c = _client()
    for raw in ("NaN", "Infinity", "1e999", "[" * 3000 + "]" * 3000,
                '"' + "A" * 900_000 + '"', '"<script>alert(1)</script>"'):
        text = json.dumps(_put(_honest(), ("panel",), HOLE)).replace(json.dumps(HOLE), raw)
        r = _inspect(c, text)
        assert r.status_code == 200, raw[:20]
        body = r.json()
        assert (body["panels"], body["panel_gap_in"], body["panel"]) == (3, 2.0, None)
        assert "script" not in r.text and len(r.content) < 2_000
    stray = _put(_put(_honest(), ("spec", "panels"), 1), ("spec", "panel_gap_in"), 0.0)
    body = _inspect(c, json.dumps(stray)).json()
    assert (body["panels"], body["panel_gap_in"], body["panel"]) == (1, 0.0, None)


# ---- a reprint takes the panel from the spec, never from the uploaded key ----

def _file_of(manifest):
    buf = io.BytesIO()
    Image.new("RGB", (16, 16)).save(buf, "PNG", pnginfo=provenance.manifest_pnginfo(manifest))
    return buf.getvalue()


def _reprint(c, manifest):
    return c.post("/api/reprint", files={"file": ("p.png", _file_of(manifest), "image/png")})


def test_a_reprint_of_a_set_numbers_its_panels_itself(monkeypatch):
    # the uploaded file says it is panel 9 of 2. The reprint is the honest zip.
    _flat_raster(monkeypatch)
    c = _client()
    _, spec = _stamp_a_set(c)
    manifest = provenance.build_manifest(spec, [])
    honest = _reprint(c, {**manifest, "panel": {"index": 2, "of": 2}})
    lying = _reprint(c, {**manifest, "panel": {"index": 9, "of": 2}})
    for r in (honest, lying):
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip"
        assert "_panels.zip" in r.headers["content-disposition"]
    assert lying.content == honest.content
    z = zipfile.ZipFile(io.BytesIO(lying.content))
    assert [n[-9:] for n in z.namelist()] == ["_1of2.png", "_2of2.png"]
    for k, name in enumerate(z.namelist(), 1):
        m = provenance.extract(z.read(name))
        assert m["panel"] == {"index": k, "of": 2} and m["spec"]["panels"] == 2


def test_a_reprint_of_a_single_sheet_drops_a_stray_panel_key(monkeypatch):
    _flat_raster(monkeypatch)
    c = _client()
    j = _upload(c)
    crop = _crop(j, 40.0, 0.75)
    spec, _ = main._build_spec(j["session"], (crop["x0"], crop["y0"], crop["x1"], crop["y1"]),
                               6, 8)
    manifest = provenance.build_manifest(spec, [])
    plain = _reprint(c, manifest)
    stray = _reprint(c, {**manifest, "panel": {"index": 2, "of": 3}})
    for r in (plain, stray):
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "image/png"
        assert r.content.startswith(b"\x89PNG")
        assert "_panels" not in r.headers["content-disposition"]
    assert "panel" not in provenance.extract(stray.content)
    assert stray.content == plain.content
