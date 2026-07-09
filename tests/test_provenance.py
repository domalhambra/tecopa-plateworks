# tests/test_provenance.py
"""Self-describing posters: the manifest round-trips, a reprint is pixel-identical to
the final (photos included -- they ride the file as embedded bytes), untrusted photos
are kept only as size-bounded embedded JPEGs, the privacy toggle omits the manifest,
and a frozen v1 manifest stays loadable forever (the user's printed-file contract)."""
import base64
import io
import json
import os
import shutil
import numpy as np
from PIL import Image

from app import provenance
from app.spec import CompositionSpec

REGION_DIR = "regions/lassen_ca"


def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

from app.main import UPLOADS_DIR

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

def _spec_from_fixture(name="manifest_v1.json"):
    m = json.load(open(f"tests/fixtures/{name}"))
    return provenance.manifest_to_spec(m), m

def _photo_bytes(color=(200, 30, 120), size=(240, 180)):
    im = Image.new("RGB", size, color)
    b = io.BytesIO(); im.save(b, "JPEG", quality=90); return b.getvalue()

def _stamped_session_with_photo(c, print_w=6, print_h=8):
    """A stamped session with a real photo pinned to hotspot 0 (upload auto-creates the
    density hotspots, then /api/photo attaches, then a clean proof stamps the spec)."""
    j = c.post("/api/upload", files=[_file()]).json()
    sid = j["session"]
    r = c.post("/api/photo", data={"session_id": sid, "i": 0},
               files={"file": ("pic.jpg", _photo_bytes(), "image/jpeg")})
    assert r.status_code == 200, r.text
    r = c.post("/api/proof", data={"session_id": sid, **_crop(j),
                                   "print_w": print_w, "print_h": print_h, "title": "Trip"})
    assert r.status_code == 200, r.text
    return sid


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


# ---- unit: embedded-photo hardening (security-critical) ----

def test_drop_unembedded_photos_keeps_only_bounded_embedded_jpegs():
    # a manifest can no longer carry a server path (only inert embedded bytes): every
    # non-embedded / oversized photo is dropped, so there is nothing to path-traverse.
    good = provenance.PHOTO_DATA_PREFIX + base64.b64encode(_photo_bytes()).decode("ascii")
    oversized = provenance.PHOTO_DATA_PREFIX + base64.b64encode(
        b"\xff" * (provenance.MAX_PHOTO_EMBED_BYTES + 1)).decode("ascii")
    spec = CompositionSpec(
        region_id="lassen_ca", crs="EPSG:32610", crop=(0, 0, 1, 1),
        print_w_in=9, print_h_in=12, native_resolution_m=10, tracks=[], seed=7,
        hotspots=[
            {"x": 0, "y": 0, "photo": "/etc/passwd"},               # absolute path
            {"x": 0, "y": 0, "photo": "../../etc/shadow"},          # relative traversal
            {"x": 0, "y": 0, "photo": "uploads/sess/1_pic.jpg"},    # even an in-uploads path
            {"x": 0, "y": 0, "photo": 12345},                       # non-string
            {"x": 0, "y": 0, "photo": oversized},                   # embedded but over cap
            {"x": 0, "y": 0, "photo": good},                        # valid embedded JPEG
            {"x": 0, "y": 0},                                       # no photo
        ])
    provenance.drop_unembedded_photos(spec)
    for i in range(5):
        assert "photo" not in spec.hotspots[i], f"hotspot {i} survived"
    assert spec.hotspots[5]["photo"] == good                       # embedded kept verbatim
    assert "photo" not in spec.hotspots[6]

def test_load_photo_guards_a_decompression_bomb():
    # a small embedded JPEG that DECLARES enormous dimensions must be refused before a
    # full decode -- load_photo checks the header size against the pixel guard.
    im = Image.new("RGB", (3000, 3000), (10, 20, 30))     # 9 MP > MAX_PHOTO_EMBED_PIXELS (8 MP)
    b = io.BytesIO(); im.save(b, "JPEG", quality=10)
    uri = provenance.PHOTO_DATA_PREFIX + base64.b64encode(b.getvalue()).decode("ascii")
    try:
        provenance.load_photo(uri)
        assert False, "decompression bomb was not refused"
    except Exception:
        pass


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

def test_reprint_drops_a_crafted_photo_path():
    # a hostile manifest pointing a hotspot photo at a server file must NOT read it into
    # the poster: a bare path is not an embedded JPEG, so it is dropped, not opened, and
    # the reprint matches a render with no photo at all.
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


# ---- embedded photos: the file carries its own pictures ----

def test_final_embeds_the_photo_as_bytes_not_a_path():
    c = _client()
    sid = _stamped_session_with_photo(c)
    png = c.post("/api/final", data={"session_id": sid}).content
    m = provenance.extract(png)
    photos = [hs["photo"] for hs in m["spec"]["hotspots"] if hs.get("photo")]
    assert photos, "the pinned photo did not reach the manifest"
    for p in photos:
        assert p.startswith(provenance.PHOTO_DATA_PREFIX)          # embedded, never a path
        assert UPLOADS_DIR not in p                                # no server path leaked
        base64.b64decode(p[len(provenance.PHOTO_DATA_PREFIX):], validate=True)  # real bytes

def test_embedded_photo_reprints_after_the_uploads_dir_is_wiped():
    # the strengthened invariant: a reprint is pixel-identical to the final *including*
    # the photo, with NO dependency on the uploads dir -- the picture lives in the file.
    c = _client()
    sid = _stamped_session_with_photo(c)
    final_png = c.post("/api/final", data={"session_id": sid}).content
    shutil.rmtree(UPLOADS_DIR, ignore_errors=True)                 # evict every upload
    r = c.post("/api/reprint", files={"file": ("poster.png", final_png, "image/png")})
    assert r.status_code == 200, r.text
    a = np.asarray(Image.open(io.BytesIO(final_png)).convert("RGB"))
    b = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"))
    assert a.shape == b.shape and np.array_equal(a, b)             # photo included, byte-exact

def test_photo_embedding_is_deterministic():
    # invariant 3: encoding the same source photo yields the same bytes, so the manifest
    # (and thus the file) stays byte-stable across builds.
    spec, _ = _spec_from_fixture()
    spots = [{"x": 690000.0, "y": 4485000.0, "weight": 1, "photo": "tests/fixtures/_probe.jpg"}]
    import dataclasses
    Image.new("RGB", (200, 150), (12, 200, 80)).save("tests/fixtures/_probe.jpg", "JPEG", quality=90)
    try:
        s = dataclasses.replace(spec, hotspots=spots)
        a = provenance.build_final_spec(s, 128).hotspots[0]["photo"]
        b = provenance.build_final_spec(s, 128).hotspots[0]["photo"]
        assert a == b and a.startswith(provenance.PHOTO_DATA_PREFIX)
    finally:
        os.remove("tests/fixtures/_probe.jpg")


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

def test_frozen_photo_manifest_reprints_its_embedded_photo():
    # the forever-contract for embedded photos: a poster printed with a pinned photo must
    # still reprint that photo from the file alone, forever. The frozen fixture carries a
    # v1 embedded JPEG; it must load, survive the untrusted-photo filter, and reprint.
    spec, manifest = _spec_from_fixture("manifest_photo_v1.json")
    provenance.drop_unembedded_photos(spec)
    assert spec.hotspots[0]["photo"].startswith(provenance.PHOTO_DATA_PREFIX)
    assert provenance.load_photo(spec.hotspots[0]["photo"]).size == (96, 96)
    img = Image.new("RGB", (16, 16), (20, 20, 20))
    buf = io.BytesIO(); img.save(buf, "PNG", pnginfo=provenance.manifest_pnginfo(manifest))
    c = _client()
    r = c.post("/api/reprint", files={"file": ("photo_v1.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    assert Image.open(io.BytesIO(r.content)).size == (9 * 300, 12 * 300)
