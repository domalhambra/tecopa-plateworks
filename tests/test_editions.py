# tests/test_editions.py
"""Living editions: the poster is the save file.

/api/continue resurrects a session from a poster's embedded manifest, bumps the
edition, and extends the lineage chain; the next final carries EDITION N in the
cartouche and the parent's sha256 in its manifest. Re-dropping a file already on the
poster is skipped. The manifest is untrusted input, so continue reuses reprint's whole
hardening posture (photo sanitization, geometry bound, full validate) and every hostile
manifest 422s or sanitizes cleanly. A frozen edition fixture pins the forever-contract
for the new lineage keys, and edition-1 output stays byte-identical to before."""
import hashlib
import io
import json
import os

import numpy as np
import pytest
from PIL import Image

from app import provenance, render, wallpaper
from app.spec import CompositionSpec, SpecError, EDITION_MAX

REGION_DIR = "regions/lassen_ca"


# ---- helpers ----

def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

def _sample():
    return open("tests/fixtures/sample.gpx", "rb").read()

def _next_year():
    """A genuinely different in-region file: the same corridor a year later. Different
    bytes (so upload dedup keeps it) and a 2025 date (so the year span widens)."""
    return _sample().replace(b"2024-06-01", b"2025-06-01")

def _gpx(name, data):
    return ("files", (name, data, "application/gpx+xml"))

def _crop(j, km_wide=40.0, ar=0.75):
    cfg = json.load(open(f"{REGION_DIR}/region.json"))
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (km_wide * 1000.0 / region_w); ch = cw / ar
    x0 = ovw * 0.5 - cw / 2; y0 = ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch}

def _final_png(c, files, proof_extra=None, upload_extra=None):
    """Upload -> proof -> final; returns (session_id, final_png_bytes, upload_json)."""
    j = c.post("/api/upload", files=files, data=(upload_extra or {})).json()
    sid = j["session"]
    data = {"session_id": sid, **_crop(j), "print_w": 6, "print_h": 8, "title": "Trip"}
    data.update(proof_extra or {})
    r = c.post("/api/proof", data=data)
    assert r.status_code == 200, r.text
    png = c.post("/api/final", data={"session_id": sid}).content
    return sid, png, j

def _embed(manifest):
    img = Image.new("RGB", (16, 16), (20, 20, 20))
    buf = io.BytesIO(); img.save(buf, "PNG", pnginfo=provenance.manifest_pnginfo(manifest))
    return buf.getvalue()

def _base_manifest(c):
    """A valid edition-1 manifest from a real final (region built, geometry sane)."""
    _, png, _ = _final_png(c, [_gpx("2024.gpx", _sample())])
    return provenance.extract(png)


# ---- unit: spec edition field ----

def test_edition_defaults_to_one_and_serializes():
    from app import serialize
    spec = provenance.manifest_to_spec(json.load(open("tests/fixtures/manifest_v1.json")))
    assert spec.edition == 1
    back = serialize.spec_from_json(serialize.spec_to_json(spec))
    assert back.edition == 1

@pytest.mark.parametrize("bad", [0, 1000, -1, 2.5, True, "3"])
def test_edition_out_of_bounds_rejected(bad):
    spec = provenance.manifest_to_spec(json.load(open("tests/fixtures/manifest_v1.json")))
    spec.edition = bad
    with pytest.raises(SpecError):
        spec.validate(300)

@pytest.mark.parametrize("ok", [1, 2, EDITION_MAX])
def test_edition_in_bounds_accepted(ok):
    spec = provenance.manifest_to_spec(json.load(open("tests/fixtures/manifest_v1.json")))
    spec.edition = ok
    spec.validate(300)


# ---- unit: cartouche edition line ----

def _spec(**kw):
    base = dict(region_id="lassen_ca", crs="EPSG:32610",
                crop=(674744.83, 4459659.23, 714744.83, 4512992.56),
                print_w_in=9, print_h_in=12, native_resolution_m=10,
                tracks=[np.array([[680000.0, 4470000.0], [700000.0, 4500000.0]])],
                track_days=["2024-06-01"], hotspots=[])
    base.update(kw)
    return CompositionSpec(**base)

def test_stats_line_edition_one_has_no_edition_prefix():
    line = render._stats_line(_spec(edition=1), 300)
    assert "EDITION" not in line

def test_stats_line_edition_two_prepends_edition_and_year_span():
    line = render._stats_line(
        _spec(edition=3, track_days=["2024-06-01", "2026-07-04"]), 300)
    assert line.startswith("EDITION 3 · 2024–2026")

def test_year_span_single_year_and_undated():
    assert render._year_span(_spec(track_days=["2024-06-01", "2024-09-01"])) == "2024"
    assert render._year_span(_spec(track_days=[None, None])) == ""
    line = render._stats_line(_spec(edition=2, track_days=[None]), 300)
    assert line.startswith("EDITION 2") and "·" in line  # edition present, no year token


# ---- unit: manifest lineage (the forever-contract) ----

def test_edition_one_manifest_omits_edition_and_lineage_keys():
    # the byte-identity guarantee: a first-edition manifest is unchanged by this feature
    m = provenance.build_manifest(_spec(edition=1), sources=[], lineage=[{"sha256": "x"}])
    assert "edition" not in m and "lineage" not in m

def test_edition_two_manifest_carries_edition_and_lineage():
    m = provenance.build_manifest(_spec(edition=2), sources=[],
                                  lineage=[{"sha256": "a", "edition": 1}])
    assert m["edition"] == 2 and m["lineage"] == [{"sha256": "a", "edition": 1}]

def test_lineage_capped_dropping_oldest():
    chain = [{"sha256": str(i), "edition": i} for i in range(provenance.LINEAGE_MAX + 5)]
    m = provenance.build_manifest(_spec(edition=2), sources=[], lineage=chain)
    assert len(m["lineage"]) == provenance.LINEAGE_MAX
    assert m["lineage"][0]["edition"] == 5        # oldest five dropped, newest kept

def test_frozen_v1_manifests_still_reprint_untouched():
    # adding the edition field must not disturb the existing print/wallpaper fixtures
    for fx in ("manifest_v1.json", "manifest_wallpaper_v1.json"):
        m = json.load(open(f"tests/fixtures/{fx}"))
        spec = provenance.manifest_to_spec(m)
        spec.validate(spec.final_dpi())
        assert spec.edition == 1
        assert "edition" not in provenance.build_manifest(spec, m.get("sources", []))


# ---- unit: bound_geometry (untrusted geometry bomb) ----

def test_bound_geometry_passes_a_sane_spec():
    provenance.bound_geometry(_spec())

def test_bound_geometry_rejects_too_many_tracks():
    with pytest.raises(SpecError):
        provenance.bound_geometry(_spec(
            tracks=[np.zeros((2, 2))] * (provenance.MAX_MANIFEST_TRACKS + 1),
            track_days=None))

def test_bound_geometry_rejects_too_many_points():
    big = np.zeros((provenance.MAX_MANIFEST_POINTS + 1, 2))
    with pytest.raises(SpecError):
        provenance.bound_geometry(_spec(tracks=[big], track_days=None))

def test_bound_geometry_rejects_too_many_hotspots():
    spots = [{"x": 0.0, "y": 0.0, "weight": 1}] * (provenance.MAX_MANIFEST_HOTSPOTS + 1)
    with pytest.raises(SpecError):
        provenance.bound_geometry(_spec(hotspots=spots))

def test_bound_geometry_rejects_non_n2_track_shape():
    with pytest.raises(SpecError):
        provenance.bound_geometry(_spec(tracks=[np.zeros((3, 3))], track_days=None))


# ---- endpoint: the ritual round-trip ----

def test_continue_ritual_round_trip():
    c = _client()
    # edition 1: compose a poster with a distinctive style
    sid1, final1, up1 = _final_png(
        c, [_gpx("2024.gpx", _sample())],
        proof_extra={"title": "Three Summers", "track_width_pt": 3.4,
                     "track_color": "#4a6936"})
    m1 = provenance.extract(final1)
    assert "edition" not in m1 and m1["spec"]["edition"] == 1

    # continue: a live session restored from the file alone
    cont = c.post("/api/continue",
                  files={"file": ("poster.png", final1, "image/png")}).json()
    sid2 = cont["session"]
    assert cont["edition"] == 2
    assert cont["prefill"]["title"] == "Three Summers"
    assert abs(cont["prefill"]["style"]["width"] - 3.4) < 1e-9
    assert cont["prefill"]["style"]["color"] == "#4a6936"
    assert len(cont["tracks"]) == len(up1["tracks"])          # tracks restored
    assert cont["files"] == ["2024.gpx"]
    assert len(cont["starter_crop"]) == 4                     # old crop projected

    # add year two, re-proof, final
    j2 = c.post("/api/upload", files=[_gpx("2025.gpx", _next_year())],
                data={"session_id": sid2}).json()
    assert j2["skipped_duplicates"] == []
    # the next-year file is a distinct hash -> its tracks append (sample.gpx is 5
    # tracks; the next-year variant is the same corridor, so it is 5 more)
    assert len(j2["tracks"]) == len(cont["tracks"]) + len(up1["tracks"])
    r = c.post("/api/proof", data={"session_id": sid2, **_crop(j2),
                                   "print_w": 6, "print_h": 8, "title": "Three Summers"})
    assert r.status_code == 200, r.text
    final2 = c.post("/api/final", data={"session_id": sid2}).content
    m2 = provenance.extract(final2)
    assert m2["edition"] == 2 and m2["spec"]["edition"] == 2
    # lineage: exactly the edition-1 file, hashed
    assert len(m2["lineage"]) == 1
    assert m2["lineage"][0]["sha256"] == hashlib.sha256(final1).hexdigest()
    assert m2["lineage"][0]["edition"] == 1
    # sources accumulated across both years
    assert len(m2["sources"]) == 2
    assert {s["filename"] for s in m2["sources"]} == {"2024.gpx", "2025.gpx"}

    # a third generation: the chain grows
    cont3 = c.post("/api/continue",
                   files={"file": ("gen2.png", final2, "image/png")}).json()
    assert cont3["edition"] == 3
    assert [e["edition"] for e in cont3["prefill"]["lineage"]] == [1, 2]


def test_reupload_of_a_file_already_on_the_poster_is_skipped():
    c = _client()
    j = c.post("/api/upload", files=[_gpx("2024.gpx", _sample())]).json()
    sid, n = j["session"], len(j["tracks"])
    j2 = c.post("/api/upload", files=[_gpx("again.gpx", _sample())],
                data={"session_id": sid}).json()
    assert j2["skipped_duplicates"] == ["again.gpx"]
    assert len(j2["tracks"]) == n                            # no journeys double-counted

def test_intra_batch_duplicate_is_collapsed():
    c = _client()
    solo = c.post("/api/upload", files=[_gpx("solo.gpx", _sample())]).json()
    j = c.post("/api/upload", files=[_gpx("a.gpx", _sample()),
                                     _gpx("b.gpx", _sample())]).json()
    assert j["skipped_duplicates"] == ["b.gpx"]
    assert len(j["tracks"]) == len(solo["tracks"])   # the duplicate added nothing


# ---- endpoint: reprint of an edition is a re-render, not a bump ----

def test_reprint_of_an_edition_preserves_edition_and_lineage():
    c = _client()
    _, final1, _ = _final_png(c, [_gpx("2024.gpx", _sample())])
    cont = c.post("/api/continue",
                  files={"file": ("p.png", final1, "image/png")}).json()
    sid2 = cont["session"]
    r = c.post("/api/proof", data={"session_id": sid2, **_crop(cont),
                                   "print_w": 6, "print_h": 8})
    assert r.status_code == 200, r.text
    ed2 = c.post("/api/final", data={"session_id": sid2}).content
    rp = c.post("/api/reprint", files={"file": ("ed2.png", ed2, "image/png")}).content
    a = provenance.extract(ed2)
    b = provenance.extract(rp)
    assert b["edition"] == a["edition"] == 2                 # reprint never bumps
    assert b["lineage"] == a["lineage"]                      # lineage carried verbatim


# ---- endpoint: reprint/inspect reports the edition ----

def test_inspect_reports_edition_and_lineage():
    c = _client()
    m = json.load(open("tests/fixtures/manifest_edition_v1.json"))
    png = _embed(m)
    r = c.post("/api/reprint/inspect", files={"file": ("ed.png", png, "image/png")}).json()
    assert r["edition"] == 3
    assert [e["edition"] for e in r["lineage"]] == [1, 2]


# ---- the forever-contract: a frozen edition file still continues + reprints ----

def test_frozen_edition_fixture_reprints_and_continues():
    c = _client()
    m = json.load(open("tests/fixtures/manifest_edition_v1.json"))
    spec = provenance.manifest_to_spec(m)
    spec.validate(spec.final_dpi())
    assert spec.edition == 3
    png = _embed(m)
    # reprint preserves edition 3 + its two-ancestor lineage
    rp = c.post("/api/reprint", files={"file": ("ed3.png", png, "image/png")}).content
    rm = provenance.extract(rp)
    assert rm["edition"] == 3 and len(rm["lineage"]) == 2
    # continue -> a fourth edition; the chain gains the fixture's own hash
    cont = c.post("/api/continue", files={"file": ("ed3.png", png, "image/png")}).json()
    assert cont["edition"] == 4
    chain = cont["prefill"]["lineage"]
    assert [e["edition"] for e in chain] == [1, 2, 3]
    assert chain[-1]["sha256"] == hashlib.sha256(png).hexdigest()


# ---- endpoint: wallpaper continues too ----

def test_wallpaper_poster_continues_in_wallpaper_mode():
    c = _client()
    j = c.post("/api/upload", files=[_gpx("2024.gpx", _sample())]).json()
    sid = j["session"]
    p = wallpaper.PRESETS["desktop_fhd"]
    r = c.post("/api/proof", data={"session_id": sid,
                                   **_crop(j, ar=p.aspect), "output": "wallpaper",
                                   "wallpaper_preset": "desktop_fhd"})
    assert r.status_code == 200, r.text
    wp = c.post("/api/final", data={"session_id": sid}).content
    cont = c.post("/api/continue", files={"file": ("wp.png", wp, "image/png")}).json()
    assert cont["prefill"]["output"] == "wallpaper"
    assert cont["prefill"]["wallpaper_preset"] == "desktop_fhd"


# ---- endpoint: hostile manifests (the untrusted-input surface) ----

def test_continue_rejects_a_png_without_a_manifest():
    c = _client()
    img = Image.new("RGB", (16, 16), (5, 5, 5))
    buf = io.BytesIO(); img.save(buf, "PNG")
    r = c.post("/api/continue", files={"file": ("plain.png", buf.getvalue(), "image/png")})
    assert r.status_code == 422 and "manifest" in r.json()["detail"].lower()

def test_continue_rejects_an_unbuilt_region():
    c = _client()
    m = _base_manifest(c)
    m["spec"]["region_id"] = "atlantis"; m["region_id"] = "atlantis"
    r = c.post("/api/continue", files={"file": ("x.png", _embed(m), "image/png")})
    assert r.status_code == 422 and "atlantis" in r.json()["detail"]

def test_continue_rejects_a_malformed_manifest():
    c = _client()
    m = _base_manifest(c)
    m["spec"] = "not a spec dict"
    r = c.post("/api/continue", files={"file": ("x.png", _embed(m), "image/png")})
    assert r.status_code == 422 and "malformed" in r.json()["detail"].lower()

def test_continue_sanitizes_a_crafted_photo_path():
    c = _client()
    m = _base_manifest(c)
    m["spec"]["hotspots"] = [{"x": 690000.0, "y": 4485000.0, "weight": 1,
                              "photo": "/etc/passwd"}]
    cont = c.post("/api/continue", files={"file": ("x.png", _embed(m), "image/png")})
    assert cont.status_code == 200, cont.text
    assert cont.json()["hotspots"][0]["photo"] is False     # the escape path was dropped

def test_continue_rejects_a_geometry_bomb():
    c = _client()
    m = _base_manifest(c)
    m["spec"]["tracks"] = [[[0.0, 0.0], [1.0, 1.0]]] * (provenance.MAX_MANIFEST_TRACKS + 1)
    r = c.post("/api/continue", files={"file": ("x.png", _embed(m), "image/png")})
    assert r.status_code == 422

def test_continue_rejects_a_bad_track_shape():
    c = _client()
    m = _base_manifest(c)
    m["spec"]["tracks"] = [[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]]   # (N,3)
    r = c.post("/api/continue", files={"file": ("x.png", _embed(m), "image/png")})
    assert r.status_code == 422

def test_continue_drops_garbage_lineage_and_non_dict_hotspots():
    c = _client()
    m = _base_manifest(c)
    m["edition"] = 2
    m["lineage"] = "not a list at all"                       # crafted garbage
    m["spec"]["hotspots"] = ["evil", {"x": 690000.0, "y": 4485000.0, "weight": 1}]
    cont = c.post("/api/continue", files={"file": ("x.png", _embed(m), "image/png")})
    assert cont.status_code == 200, cont.text
    body = cont.json()
    assert len(body["hotspots"]) == 1                        # the non-dict entry dropped
    # garbage lineage dropped; only the freshly-hashed parent remains
    assert len(body["prefill"]["lineage"]) == 1
    assert body["edition"] == 3                              # parent 2 -> child 3

def test_continue_clamps_a_crafted_huge_edition():
    c = _client()
    m = _base_manifest(c)
    m["edition"] = 10 ** 9                                   # absurd top-level edition
    cont = c.post("/api/continue", files={"file": ("x.png", _embed(m), "image/png")})
    assert cont.status_code == 200, cont.text
    assert cont.json()["edition"] == EDITION_MAX             # clamped, never overflows

def test_continue_drops_a_stale_photo_path_inside_uploads():
    # a path that resolves INSIDE uploads but no longer exists must drop, not 500 later
    c = _client()
    m = _base_manifest(c)
    uploads = os.environ["TRAILPRINT_UPLOADS"]
    m["spec"]["hotspots"] = [{"x": 690000.0, "y": 4485000.0, "weight": 1,
                              "photo": os.path.join(uploads, "ghost", "9_gone.jpg")}]
    cont = c.post("/api/continue", files={"file": ("x.png", _embed(m), "image/png")})
    assert cont.status_code == 200, cont.text
    assert cont.json()["hotspots"][0]["photo"] is False
