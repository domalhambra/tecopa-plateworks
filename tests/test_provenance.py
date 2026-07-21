# tests/test_provenance.py
"""Self-describing posters: the manifest round-trips, a reprint is pixel-identical to
the final (photos included -- they ride the file as embedded bytes), untrusted photos
are kept only as size-bounded embedded JPEGs, the privacy toggle omits the manifest,
and a frozen v1 manifest stays loadable forever (the user's printed-file contract)."""
import base64
import hashlib
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


# ---- unit: the single untrusted-manifest door (spec_from_manifest) ----

def test_spec_from_manifest_runs_the_whole_guard_chain():
    # one call = parse + drop-unembedded-photos + bound_geometry + validate. A bare photo
    # path in the manifest is dropped (not opened), and the returned spec is already valid.
    m = json.load(open("tests/fixtures/manifest_v1.json"))
    m["spec"]["hotspots"] = [{"x": 690000.0, "y": 4485000.0, "weight": 1, "photo": "/etc/passwd"}]
    spec = provenance.spec_from_manifest(m)
    assert "photo" not in spec.hotspots[0]                 # bare path dropped, never opened
    spec.validate(spec.final_dpi())                        # already gated -> still passes

def test_spec_from_manifest_accepts_every_legacy_engine_name():
    # The engine has been named trailprint, tecopa-printworks, and now tecopa-plateworks.
    # MANIFEST.md: readers MUST treat all three as this engine — a file from any era opens.
    m = json.load(open("tests/fixtures/manifest_v1.json"))
    for engine in (provenance.ENGINE, *provenance.LEGACY_ENGINES):
        m["engine"] = engine
        spec = provenance.spec_from_manifest(m)
        spec.validate(spec.final_dpi())

def test_spec_from_manifest_rejects_a_malformed_manifest():
    try:
        provenance.spec_from_manifest({"spec": "not a spec dict"})
        assert False, "malformed manifest was not refused"
    except provenance.ManifestError as e:
        assert "malformed" in str(e).lower()

def test_spec_from_manifest_rejects_a_geometry_bomb():
    from app.spec import SpecError
    m = json.load(open("tests/fixtures/manifest_v1.json"))
    m["spec"]["tracks"] = [[[0.0, 0.0], [1.0, 1.0]]] * (provenance.MAX_MANIFEST_TRACKS + 1)
    try:
        provenance.spec_from_manifest(m)
        assert False, "geometry bomb was not refused"
    except SpecError:
        pass

def test_manifest_error_is_a_spec_error():
    # the whole point of the door: one `except SpecError` at the endpoint maps a bad
    # manifest AND a bad geometry to a single 422 path.
    from app.spec import SpecError
    assert issubclass(provenance.ManifestError, SpecError)


# ---- unit: region_pack (the manifest names its plate) ----

def test_region_pack_block_hashes_the_plate_bytes_on_disk():
    # the block names the plate the PIXELS come from: each asset the render reads,
    # hashed from its bytes on disk -- never trusted from sources.json (whose recorded
    # hashes can drift from the assets; see the sidecar-drift test below)
    rp = provenance.region_pack_block(REGION_DIR)
    assert set(rp) == {"pack_version", "assets"}
    assert len(rp["pack_version"]) == 12
    int(rp["pack_version"], 16)                            # 12 hex chars
    for name, digest in rp["assets"].items():
        with open(os.path.join(REGION_DIR, name), "rb") as f:
            assert digest == hashlib.sha256(f.read()).hexdigest(), name
    assert rp == provenance.region_pack_block(REGION_DIR)  # deterministic

def test_pack_identity_covers_only_the_assets_the_render_reads():
    # overview.png feeds the browser aim canvas (never rasterize); labels.json is only
    # read when the spec draws labels; landcover.tif only when the biome tint is on --
    # none may enter the identity of a poster whose pixels never touched it, or a
    # routine GNIS labels rebake / NLCD refresh would refuse exact-identical reprints
    # of every poster that never drew them.
    off = provenance.region_pack_block(REGION_DIR)
    assert "overview.png" not in off["assets"]
    assert "labels.json" not in off["assets"]
    assert "landcover.tif" not in off["assets"]
    on = provenance.region_pack_block(REGION_DIR, labels=True)
    assert "labels.json" in on["assets"]
    assert on["pack_version"] != off["pack_version"]
    tinted = provenance.region_pack_block(REGION_DIR, biome=True)
    assert "landcover.tif" in tinted["assets"]
    assert tinted["pack_version"] != off["pack_version"]
    assert tinted["pack_version"] != on["pack_version"]

def test_labels_rebake_keeps_the_labels_off_identity(tmp_path):
    # the README-documented maintenance step (scripts/build_labels.py re-bake) must not
    # break reprints of posters whose pixels never touched labels.json
    rdir = str(tmp_path / "lassen_ca")
    shutil.copytree(REGION_DIR, rdir)
    off = provenance.region_pack_block(rdir)
    on = provenance.region_pack_block(rdir, labels=True)
    with open(os.path.join(rdir, "labels.json"), "w") as f:    # the rebake: new GNIS bytes
        f.write('{"crs": "EPSG:32610", "features": []}')
    assert provenance.region_pack_block(rdir) == off           # labels-off reprints keep working
    assert provenance.region_pack_block(rdir, labels=True)["pack_version"] \
        != on["pack_version"]                                  # labels-on honestly changes

def test_pack_identity_comes_from_asset_bytes_not_the_sidecar(tmp_path):
    # sources.json can drift from the assets (a re-prep that crashed before the sidecar
    # write, a fresh clone with a synthetic test DEM): identity must follow the BYTES
    # the render reads, or a final stamps -- and a reprint verifies as 'verified' -- a
    # plate the pixels were never painted with.
    rdir = str(tmp_path / "lassen_ca")
    shutil.copytree(REGION_DIR, rdir)
    before = provenance.region_pack_block(rdir)
    src_path = os.path.join(rdir, "sources.json")
    src = json.load(open(src_path))
    src["assets"]["dem.tif"]["sha256"] = "0" * 64              # sidecar drift only
    json.dump(src, open(src_path, "w"))
    assert provenance.region_pack_block(rdir) == before        # bytes unchanged -> same plate
    with open(os.path.join(rdir, "dem.tif"), "ab") as f:       # asset drift only
        f.write(b"drift")
    assert provenance.region_pack_block(rdir)["pack_version"] \
        != before["pack_version"]                              # bytes changed -> new plate

def test_manifest_doc_derivation_worked_example():
    # docs/MANIFEST.md's worked example must satisfy its own documented formula, and
    # the frozen fixture stays the deliberate-MISMATCH example (it violates the
    # derivation on purpose so it can never match a real plate) -- a third-party
    # reimplementer unit-testing against the doc must never get a false failure.
    assert hashlib.sha256(("dem.tif:" + "0" * 64).encode()).hexdigest()[:12] \
        == "a15c11e69898"
    m = json.load(open("tests/fixtures/manifest_region_pack_v1.json"))
    assert m["region_pack"]["pack_version"] == "000000000000"  # never a real derivation

def test_region_pack_block_is_none_without_sources(tmp_path):
    # a region dir with no sources.json (a hand-built plate) -> None, callers omit
    assert provenance.region_pack_block(str(tmp_path)) is None

def test_default_manifest_omits_region_pack():
    # additive key: a build_manifest call that doesn't pass the block never emits it,
    # so every pre-pack manifest (incl. the frozen fixtures) is byte-for-byte unchanged
    spec, m = _spec_from_fixture()
    assert "region_pack" not in provenance.build_manifest(spec, m.get("sources", []))


# ---- the resurrection note: a strings(1)-readable tEXt twin of the zTXt manifest ----

def test_resurrection_note_is_pure_ascii_and_names_the_essentials():
    # a 2035 finder running strings(1) must learn: what the file is (its own save
    # file), where the recipe lives (the zTXt chunk + the CC0 schema doc), where the
    # AGPL engine lives, what plate painted it, that the data is public domain, and
    # how to bring it back. Pure function of the manifest -- no clock, no env.
    _, manifest = _spec_from_fixture()
    note = provenance.resurrection_note(manifest)
    assert note == provenance.resurrection_note(json.loads(json.dumps(manifest)))
    note.encode("ascii")                       # tEXt is latin-1; we stay plain ASCII
    assert "save file" in note
    assert '"trailprint"' in note and "docs/MANIFEST.md" in note
    assert "AGPL-3.0-or-later" in note
    assert "https://github.com/domalhambra/tecopa-plateworks" in note
    # pre-pack manifest (no region_pack): the plate line names the region, no version
    assert "plate lassen_ca" in note
    assert "USGS" in note and "/api/reprint" in note
    assert len(note.splitlines()) <= 8         # short enough to read in a hex dump

def test_resurrection_note_names_the_pack_version_when_present():
    _, manifest = _spec_from_fixture("manifest_region_pack_v1.json")
    note = provenance.resurrection_note(manifest)
    assert "plate lassen_ca 000000000000" in note

def test_final_carries_the_note_and_it_is_stable_across_renders():
    c = _client()
    sid = _stamped_session(c)
    png = c.post("/api/final", data={"session_id": sid}).content
    note = Image.open(io.BytesIO(png)).text["trailprint-note"]
    assert "save file" in note
    m = provenance.extract(png)
    assert m["region_pack"]["pack_version"] in note    # the plate version, when present
    # plain tEXt (NOT zip=True): the raw file bytes carry the readable sentence, which
    # is the whole point -- strings(1) finds it without any PNG tooling.
    assert b"save file" in png
    # same spec -> same note (the note is a pure function of the manifest)
    png2 = c.post("/api/final", data={"session_id": sid}).content
    assert Image.open(io.BytesIO(png2)).text["trailprint-note"] == note

def test_share_copy_carries_no_text_chunks_at_all():
    # embed_spec=false is the privacy path: no manifest AND no note -- pnginfo is
    # skipped entirely, so nothing textual rides the share copy.
    c = _client()
    sid = _stamped_session(c)
    png = c.post("/api/final", data={"session_id": sid, "embed_spec": "false"}).content
    assert Image.open(io.BytesIO(png)).text == {}


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


# ---- endpoint: region_pack rides the final and survives a reprint ----

def test_final_manifest_carries_the_region_pack():
    # the final names the plate it was painted on -- the server's live block, verbatim
    c = _client()
    sid = _stamped_session(c)
    png = c.post("/api/final", data={"session_id": sid}).content
    m = provenance.extract(png)
    rp = provenance.region_pack_block(REGION_DIR)
    assert m["region_pack"]["pack_version"] == rp["pack_version"]
    assert m["region_pack"]["assets"] == rp["assets"]

def test_reprint_restamps_the_region_pack_byte_identically():
    # the animation-block regression, generalized: a reprint REBUILDS the manifest, so
    # any block that isn't re-stamped silently vanishes from the reprint. The whole
    # manifest must round-trip byte-equal, region_pack included.
    c = _client()
    sid = _stamped_session(c)
    final_png = c.post("/api/final", data={"session_id": sid}).content
    r = c.post("/api/reprint", files={"file": ("poster.png", final_png, "image/png")})
    assert r.status_code == 200, r.text
    a = provenance.extract(final_png)
    b = provenance.extract(r.content)
    assert "region_pack" in b
    assert provenance._manifest_str(a) == provenance._manifest_str(b)
    # the resurrection note is a pure function of the manifest, so it must round-trip
    # byte-equal too -- a reprint that re-worded the note would break byte identity.
    assert Image.open(io.BytesIO(final_png)).text["trailprint-note"] \
        == Image.open(io.BytesIO(r.content)).text["trailprint-note"]


# ---- plate verification: the server checks the plate the file names ----
# The frozen mismatch fixture carries pack_version "000000000000" -- a real plate can
# never hash to that, so the MISMATCH path stays testable forever. The VERIFIED path
# rides runtime-built manifests, which stay true across future region rebuilds.

MISMATCH_FIXTURE = "manifest_region_pack_v1.json"

def _png_with_manifest(manifest):
    img = Image.new("RGB", (16, 16), (20, 20, 20))
    buf = io.BytesIO(); img.save(buf, "PNG", pnginfo=provenance.manifest_pnginfo(manifest))
    return buf.getvalue()

def test_inspect_reports_verified_for_a_runtime_final():
    c = _client()
    sid = _stamped_session(c)
    png = c.post("/api/final", data={"session_id": sid}).content
    body = c.post("/api/reprint/inspect", files={"file": ("p.png", png, "image/png")}).json()
    server_pv = provenance.region_pack_block(REGION_DIR)["pack_version"]
    assert body["plate"] == "verified"
    assert body["plate_file"] == server_pv and body["plate_server"] == server_pv

def test_inspect_reports_unverifiable_for_a_pre_pack_poster():
    # the frozen v1 fixture has no region_pack block -- soft forever-compat, never a fail
    _, manifest = _spec_from_fixture()
    c = _client()
    body = c.post("/api/reprint/inspect",
                  files={"file": ("v1.png", _png_with_manifest(manifest), "image/png")}).json()
    assert body["plate"] == "unverifiable"
    assert body["plate_file"] is None
    assert body["plate_server"] == provenance.region_pack_block(REGION_DIR)["pack_version"]

def test_inspect_reports_region_missing():
    _, manifest = _spec_from_fixture(MISMATCH_FIXTURE)
    manifest["region_id"] = "atlantis"
    manifest["spec"]["region_id"] = "atlantis"
    c = _client()
    body = c.post("/api/reprint/inspect",
                  files={"file": ("a.png", _png_with_manifest(manifest), "image/png")}).json()
    assert body["plate"] == "region_missing"
    assert body["plate_file"] == "000000000000"
    assert body["plate_server"] is None

def test_reprint_refuses_a_plate_mismatch_naming_both_versions():
    _, manifest = _spec_from_fixture(MISMATCH_FIXTURE)
    c = _client()
    r = c.post("/api/reprint", files={"file": ("m.png", _png_with_manifest(manifest), "image/png")})
    assert r.status_code == 422
    detail = r.json()["detail"]
    server_pv = provenance.region_pack_block(REGION_DIR)["pack_version"]
    assert "000000000000" in detail and server_pv in detail    # both plates named
    assert "reprint it exactly" in detail                      # readable verb, pinned

def test_reprint_of_a_mismatched_film_is_refused_before_queueing():
    # verification runs BEFORE the animated/still branch: a mismatched film must 422,
    # never enqueue a render against the wrong terrain.
    _, manifest = _spec_from_fixture(MISMATCH_FIXTURE)
    manifest["animation"] = {"max_frames": 12, "step_ms": 120,
                             "hold_ms": 1200, "leader_ms": 600, "dpi": 60}
    c = _client()
    r = c.post("/api/reprint", files={"file": ("f.png", _png_with_manifest(manifest), "image/png")})
    assert r.status_code == 422
    assert "000000000000" in r.json()["detail"]

def test_reprint_region_missing_names_the_plate_the_file_wants():
    _, manifest = _spec_from_fixture(MISMATCH_FIXTURE)
    manifest["region_id"] = "atlantis"
    manifest["spec"]["region_id"] = "atlantis"
    c = _client()
    r = c.post("/api/reprint", files={"file": ("a.png", _png_with_manifest(manifest), "image/png")})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "isn't built on this server" in detail
    assert "It was painted on plate 000000000000." in detail

def test_continue_refuses_a_plate_mismatch():
    _, manifest = _spec_from_fixture(MISMATCH_FIXTURE)
    c = _client()
    r = c.post("/api/continue", files={"file": ("m.png", _png_with_manifest(manifest), "image/png")})
    assert r.status_code == 422
    detail = r.json()["detail"]
    server_pv = provenance.region_pack_block(REGION_DIR)["pack_version"]
    assert "000000000000" in detail and server_pv in detail
    assert "continue it exactly" in detail                     # readable verb, pinned

def test_frozen_region_pack_fixture_verifies_and_refuses():
    # the forever-contract for the mismatch path: the fixture must load + validate
    # (the file itself is well-formed), inspect must answer mismatch, and reprint must
    # refuse it naming both plate versions.
    spec, manifest = _spec_from_fixture(MISMATCH_FIXTURE)
    spec.validate(300)
    assert manifest["region_pack"]["pack_version"] == "000000000000"
    png = _png_with_manifest(manifest)
    c = _client()
    body = c.post("/api/reprint/inspect", files={"file": ("f.png", png, "image/png")}).json()
    assert body["plate"] == "mismatch"
    assert body["plate_file"] == "000000000000"
    r = c.post("/api/reprint", files={"file": ("f.png", png, "image/png")})
    assert r.status_code == 422
    detail = r.json()["detail"]
    server_pv = provenance.region_pack_block(REGION_DIR)["pack_version"]
    assert "000000000000" in detail and server_pv in detail


# ---- plate verification: the report and the verbs must never disagree ----

def test_inspect_plate_verdict_follows_the_spec_region_like_reprint():
    # a crafted file can diverge the top-level region_id from spec.region_id; reprint
    # renders against spec.region_id, so the report's verdict must resolve the same
    # way -- never a 'verified' for a file the verb would refuse (or vice versa).
    _, manifest = _spec_from_fixture(MISMATCH_FIXTURE)
    manifest["region_id"] = "atlantis"                    # spec still says lassen_ca
    c = _client()
    body = c.post("/api/reprint/inspect",
                  files={"file": ("d.png", _png_with_manifest(manifest), "image/png")}).json()
    assert body["plate"] == "mismatch"                    # judged like reprint: lassen_ca
    assert body["region_available"] is True
    _, manifest = _spec_from_fixture(MISMATCH_FIXTURE)
    manifest["spec"]["region_id"] = "atlantis"            # top-level still says lassen_ca
    body = c.post("/api/reprint/inspect",
                  files={"file": ("e.png", _png_with_manifest(manifest), "image/png")}).json()
    assert body["plate"] == "region_missing"              # reprint would 422 region-missing
    assert body["region_available"] is False

def test_unmanifested_server_plate_skips_verification(monkeypatch):
    # MANIFEST.md: a hand-built plate (no sources.json) SKIPS verification and the file
    # prints. The verbs and the report must agree on that: continue proceeds, inspect
    # answers the same soft 'unverifiable' a pre-pack poster gets.
    monkeypatch.setattr(provenance, "region_pack_block", lambda *a, **k: None)
    _, manifest = _spec_from_fixture(MISMATCH_FIXTURE)
    png = _png_with_manifest(manifest)
    c = _client()
    body = c.post("/api/reprint/inspect", files={"file": ("h.png", png, "image/png")}).json()
    assert body["plate"] == "unverifiable"
    assert body["plate_server"] is None
    r = c.post("/api/continue", files={"file": ("h.png", png, "image/png")})
    assert r.status_code == 200, r.text

def test_falsy_pack_version_is_treated_as_absent_by_verdict_and_gate():
    # "" (or any falsy value) can never name a real plate; the verify gate skips it,
    # so inspect must not cry 'mismatch' for a file the verbs happily print.
    _, manifest = _spec_from_fixture(MISMATCH_FIXTURE)
    manifest["region_pack"]["pack_version"] = ""
    png = _png_with_manifest(manifest)
    c = _client()
    body = c.post("/api/reprint/inspect", files={"file": ("f.png", png, "image/png")}).json()
    assert body["plate"] == "unverifiable"
    assert body["plate_file"] is None
    r = c.post("/api/continue", files={"file": ("f.png", png, "image/png")})
    assert r.status_code == 200, r.text

def test_crafted_pack_version_is_never_echoed():
    # a pack_version is 12 hex chars or it is nothing: a crafted megabyte string (or a
    # non-string) must never ride back out in an error detail or the inspect report.
    _, manifest = _spec_from_fixture(MISMATCH_FIXTURE)
    manifest["region_pack"]["pack_version"] = "A" * 200_000
    c = _client()
    body = c.post("/api/reprint/inspect",
                  files={"file": ("g.png", _png_with_manifest(manifest), "image/png")}).json()
    assert body["plate"] == "unverifiable" and body["plate_file"] is None
    manifest["region_id"] = "atlantis"                    # the region-missing echo path
    manifest["spec"]["region_id"] = "atlantis"
    r = c.post("/api/reprint",
               files={"file": ("g.png", _png_with_manifest(manifest), "image/png")})
    assert r.status_code == 422
    assert len(r.json()["detail"]) < 500                  # honest 422, bounded body
    manifest["region_pack"]["pack_version"] = {"nested": ["json"]}   # non-string type
    body = c.post("/api/reprint/inspect",
                  files={"file": ("i.png", _png_with_manifest(manifest), "image/png")}).json()
    assert body["plate_file"] is None


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
