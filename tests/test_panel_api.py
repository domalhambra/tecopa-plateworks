# tests/test_panel_api.py
import io
import json
import os
import time
import zipfile

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

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
