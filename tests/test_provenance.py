# tests/test_provenance.py
"""Self-describing posters: the manifest round-trips, a reprint is pixel-identical to
the final, untrusted photo paths are sanitized, the privacy toggle omits the manifest,
and a frozen v1 manifest stays loadable forever (the user's printed-file contract)."""
import io
import json
import os
import numpy as np
from PIL import Image

from app import provenance
from app.spec import CompositionSpec

REGION_DIR = "regions/lassen_ca"


def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

def _file(name="a.gpx"):
    return ("files", (name, open("tests/fixtures/sample.gpx", "rb").read(), "application/gpx+xml"))

def _crop(j, km_wide=40.0, ar=0.75):
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (km_wide * 1000.0 / region_w); ch = cw / ar
    x0 = ovw * 0.5 - cw / 2; y0 = ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch}

def _stamped_session(c, print_w=6, print_h=8):   # small sheet keeps the 300-dpi finals fast
    j = c.post("/api/upload", files=[_file()]).json()
    r = c.post("/api/proof", data={"session_id": j["session"], **_crop(j),
                                   "print_w": print_w, "print_h": print_h, "title": "Trip"})
    assert r.status_code == 200, r.text
    return j["session"]

def _spec_from_fixture():
    m = json.load(open("tests/fixtures/manifest_v1.json"))
    return provenance.manifest_to_spec(m), m


# ---- unit: manifest format ----

def test_manifest_roundtrips_through_a_png():
    spec, _ = _spec_from_fixture()
    sources = [provenance.source_entry(b"hello gpx", "trip.gpx")]
    manifest = provenance.build_manifest(spec, sources)
    img = Image.new("RGB", (16, 16), (30, 40, 50))
    buf = io.BytesIO(); img.save(buf, "PNG", pnginfo=provenance.manifest_pnginfo(manifest))
    got = provenance.extract(buf.getvalue())
    # compare against the JSON-normalized manifest: JSON has no tuples, so an in-memory
    # tuple (e.g. track_rgb) becomes a list on the way out -- spec_from_json converts it
    # back on reprint. The bytes are what's frozen; normalize before comparing.
    assert got == json.loads(provenance._manifest_str(manifest))
    assert got["sources"][0]["sha256"] == sources[0]["sha256"]

def test_manifest_is_byte_deterministic():
    spec, _ = _spec_from_fixture()
    s = [provenance.source_entry(b"x", "a.gpx")]
    assert provenance._manifest_str(provenance.build_manifest(spec, s)) == \
           provenance._manifest_str(provenance.build_manifest(spec, s))

def test_extract_returns_none_for_a_plain_png():
    img = Image.new("RGB", (8, 8), (1, 2, 3))
    buf = io.BytesIO(); img.save(buf, "PNG")
    assert provenance.extract(buf.getvalue()) is None
    assert provenance.extract(b"not a png at all") is None


# ---- unit: photo-path sanitization (security-critical) ----

def test_sanitize_drops_photo_paths_outside_uploads(tmp_path):
    uploads = tmp_path / "uploads"; uploads.mkdir()
    good = uploads / "sess"; good.mkdir(); good_file = good / "1_pic.jpg"; good_file.write_bytes(b"x")
    # a symlink INSIDE uploads pointing OUT (realpath must resolve the target, not the link)
    escape_link = good / "link.jpg"; os.symlink("/etc/passwd", escape_link)
    # a sibling dir sharing the uploads prefix -- the classic "/uploads-evil" bypass
    sibling = tmp_path / "uploads-evil"; sibling.mkdir(); sib = sibling / "x.jpg"; sib.write_bytes(b"x")
    spec = CompositionSpec(
        region_id="lassen_ca", crs="EPSG:32610", crop=(0, 0, 1, 1),
        print_w_in=9, print_h_in=12, native_resolution_m=10, tracks=[], seed=7,
        hotspots=[
            {"x": 0, "y": 0, "photo": "/etc/passwd"},               # absolute escape
            {"x": 0, "y": 0, "photo": "../../etc/shadow"},          # relative traversal
            {"x": 0, "y": 0, "photo": str(escape_link)},            # symlink escape
            {"x": 0, "y": 0, "photo": str(sib)},                    # prefix confusion
            {"x": 0, "y": 0, "photo": str(good_file)},              # legit, in-uploads
            {"x": 0, "y": 0},
        ])
    provenance.sanitize_photos(spec, str(uploads))
    for i in range(4):
        assert "photo" not in spec.hotspots[i], f"hotspot {i} escaped uploads"
    assert spec.hotspots[4]["photo"] == str(good_file)     # in-uploads kept
    assert "photo" not in spec.hotspots[5]


# ---- endpoint: embedding + privacy ----

def test_final_embeds_a_reprintable_manifest_by_default():
    c = _client()
    sid = _stamped_session(c)
    png = c.post("/api/final", data={"session_id": sid, "format": "png"}).content
    m = provenance.extract(png)
    assert m and m["region_id"] == "lassen_ca"
    assert m["manifest_version"] == provenance.MANIFEST_VERSION
    assert len(m["sources"]) == 1 and len(m["sources"][0]["sha256"]) == 64
    assert m["spec"]["print_w_in"] == 6

def test_embed_spec_false_omits_the_manifest():
    # a share copy must not carry the exact track coordinates (privacy).
    c = _client()
    sid = _stamped_session(c)
    png = c.post("/api/final", data={"session_id": sid, "embed_spec": "false"}).content
    assert provenance.extract(png) is None

def test_pdf_final_carries_no_manifest():
    # Pillow's PDF writer has no text-metadata seam -> self-describing posters are PNG.
    c = _client()
    sid = _stamped_session(c)
    r = c.post("/api/final", data={"session_id": sid, "format": "pdf"})
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


# ---- endpoint: reprint ----

def test_reprint_is_pixel_identical_to_the_final():
    # invariants 1 + 3: the spec rides the file, so a reprint reproduces the poster.
    c = _client()
    sid = _stamped_session(c)
    final_png = c.post("/api/final", data={"session_id": sid}).content
    r = c.post("/api/reprint", files={"file": ("poster.png", final_png, "image/png")})
    assert r.status_code == 200, r.text
    a = np.asarray(Image.open(io.BytesIO(final_png)).convert("RGB"))
    b = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"))
    assert a.shape == b.shape and np.array_equal(a, b)
    assert provenance.extract(r.content) is not None      # reprint is self-describing too

def test_reprint_rejects_a_png_without_a_manifest():
    c = _client()
    img = Image.new("RGB", (32, 32), (9, 9, 9))
    buf = io.BytesIO(); img.save(buf, "PNG")
    r = c.post("/api/reprint", files={"file": ("plain.png", buf.getvalue(), "image/png")})
    assert r.status_code == 422 and "manifest" in r.json()["detail"].lower()

def test_reprint_inspect_returns_provenance_without_rendering():
    c = _client()
    sid = _stamped_session(c)
    final_png = c.post("/api/final", data={"session_id": sid}).content
    r = c.post("/api/reprint/inspect", files={"file": ("poster.png", final_png, "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["region_id"] == "lassen_ca" and body["region_available"] is True
    assert body["print_size_in"] == [6, 8] and len(body["sources"]) == 1

def test_reprint_sanitizes_a_crafted_photo_path():
    # a hostile manifest pointing a hotspot photo at a server file must NOT read it into
    # the poster: the reprint succeeds and matches a render with no photo at all.
    c = _client()
    sid = _stamped_session(c)
    clean_png = c.post("/api/final", data={"session_id": sid}).content
    manifest = provenance.extract(clean_png)
    manifest["spec"]["hotspots"][0]["photo"] = "/etc/passwd"     # inject
    tampered = io.BytesIO()
    Image.open(io.BytesIO(clean_png)).convert("RGB").save(
        tampered, "PNG", dpi=(300, 300), pnginfo=provenance.manifest_pnginfo(manifest))
    r = c.post("/api/reprint", files={"file": ("evil.png", tampered.getvalue(), "image/png")})
    assert r.status_code == 200
    # identical to the clean reprint => the /etc/passwd path was dropped, not opened
    a = np.asarray(Image.open(io.BytesIO(clean_png)).convert("RGB"))
    b = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"))
    assert np.array_equal(a, b)


# ---- the forever-contract: a v1 file must still reprint ----

def test_frozen_v1_manifest_loads_validates_and_reprints():
    spec, manifest = _spec_from_fixture()
    spec.validate(300)                                     # the v1 geometry still passes
    assert spec.region_id == "lassen_ca" and spec.title_text == "Frozen v1"
    # embed the frozen manifest into a PNG and drive it through /api/reprint end to end
    img = Image.new("RGB", (16, 16), (20, 20, 20))
    buf = io.BytesIO(); img.save(buf, "PNG", pnginfo=provenance.manifest_pnginfo(manifest))
    c = _client()
    r = c.post("/api/reprint", files={"file": ("v1.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    assert Image.open(io.BytesIO(r.content)).size == (9 * 300, 12 * 300)
