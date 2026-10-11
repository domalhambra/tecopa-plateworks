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
    """A genuinely different in-region file: the same corridor a year later. ALL FIVE days
    shift to 2025 (not just the first), so every track is a distinct journey (a real repeat
    visit earns its own worn-path weight) rather than a same-day/same-coords duplicate that
    track-level dedup would fold. Different bytes too, so file-level dedup keeps it."""
    return _sample().replace(b"2024-", b"2025-")

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
    assert cont["year_span"] == "2024"                        # the echo: what the file holds
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


def test_continue_preserves_a_title_less_poster():
    # a poster composed with the "-" (no title) choice must stay title-less across
    # editions: the prefill sends "-" back, not "" (which _build_spec would re-resolve
    # to the region name and regrow a title block).
    c = _client()
    _, png, _ = _final_png(c, [_gpx("2024.gpx", _sample())], proof_extra={"title": "-"})
    assert provenance.extract(png)["spec"]["title_text"] == ""   # "-" -> no title
    cont = c.post("/api/continue", files={"file": ("p.png", png, "image/png")}).json()
    assert cont["prefill"]["title"] == "-"           # round-trips as the no-title sentinel


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


# ---- endpoint: proof_form, the proof fields that rebuild the file's spec ----
# /api/continue names the exact /api/proof form fields for the poster it opened, so no
# client (the studio, the tecopa tool) copies the spec -> form mapping. The proof of
# the mapping is a round trip: send proof_form + starter_crop back to /api/proof, and
# the spec it stamps is the file's spec.

# The two spec fields the round trip does not compare exactly, and why:
#   edition -- /api/continue bumps it: the child is one past the parent.
#   crop    -- it goes CRS metres -> overview px -> CRS metres, so it is compared
#              within 1e-3 m and not bit for bit.
# Every other field must come back equal. No field is left out because the form
# cannot carry it.
_ROUND_TRIP_SKIP = {"edition", "crop"}

# What /api/proof reads from the form that proof_form never holds: the session and
# the crop are the caller's, and sun_hour is the scrubber's input -- a file carries
# the RESOLVED sun (sun_azimuth_deg + sun_altitude_deg), which wins at re-proof.
_NOT_IN_PROOF_FORM = {"session_id", "x0", "y0", "x1", "y1", "sun_hour"}

def _proof_params():
    import inspect
    from app import main
    return set(inspect.signature(main.proof).parameters)

def _as_form(proof_form):
    """proof_form the way a multipart form sends it: a boolean is "true"/"false"."""
    return {k: ("true" if v else "false") if isinstance(v, bool) else v
            for k, v in proof_form.items()}

def _proof_form_round_trip(c, ar=0.75, **proof_fields):
    """Upload -> proof -> final -> continue -> proof again from proof_form +
    starter_crop. Returns (first stamped spec, second stamped spec, continue answer)."""
    from app import session
    j = c.post("/api/upload", files=[_gpx("2024.gpx", _sample())]).json()
    sid1 = j["session"]
    r = c.post("/api/proof", data={"session_id": sid1, **_crop(j, ar=ar), **proof_fields})
    assert r.status_code == 200, r.text
    first = session.get(sid1)["spec"]
    png = c.post("/api/final", data={"session_id": sid1}).content
    cont = c.post("/api/continue", files={"file": ("p.png", png, "image/png")}).json()
    form = cont["proof_form"]
    assert set(form) <= _proof_params() - _NOT_IN_PROOF_FORM, sorted(form)
    assert all(v is not None for v in form.values()), form   # every value fits a form
    x0, y0, x1, y1 = cont["starter_crop"]
    r = c.post("/api/proof", data={"session_id": cont["session"], "x0": x0, "y0": y0,
                                   "x1": x1, "y1": y1, **_as_form(form)})
    assert r.status_code == 200, r.text
    return first, session.get(cont["session"])["spec"], cont

def _assert_same_picture(first, second):
    """The second spec is the first in every field but the two named above; a
    failure names each field that differs."""
    from app import serialize
    a, b = (json.loads(json.dumps(serialize.spec_to_json(s))) for s in (first, second))
    diff = [f"{k}: {str(a.get(k))[:80]} -> {str(b.get(k))[:80]}"
            for k in sorted(set(a) | set(b))
            if k not in _ROUND_TRIP_SKIP and a.get(k) != b.get(k)]
    assert not diff, "proof_form did not restore: " + "; ".join(diff)
    assert second.edition == first.edition + 1
    drift = max(abs(p - q) for p, q in zip(first.crop, second.crop))
    assert drift < 1e-3, f"crop moved {drift} m: {first.crop} -> {second.crop}"

def test_proof_form_restores_a_styled_poster():
    c = _client()
    styled = {"print_w": 6, "print_h": 8, "title": "Three Summers", "bleed": 0.125,
              "contours": "true", "compass": "false", "biome": "true", "labels": "true",
              "track_width_pt": 3.4, "track_halo": 0.4, "track_color": "#4a6936",
              "marker_size_in": 0.31, "marker_ring": 0.12, "photo_style": "polaroid",
              "furniture_scale": 1.2, "terrain_depth": 0.8, "shadow_strength": 0.3,
              "oblique": 0.35, "soft_light": 0.4, "haze_strength": 0.25,
              "water_depth": 0.5, "dry_lakes": "true", "golden_strength": 0.4,
              "profile": "true", "profile_height_in": 1.1,
              "track_color_by": "elevation", "label_place": "anchor",
              "track_weave": "false"}
    first, second, cont = _proof_form_round_trip(c, **styled)
    # the first proof really left the defaults: a default-only round trip proves nothing
    plain = _spec()
    moved = {n for n in ("print_w_in", "print_h_in", "title_text", "bleed_in", "contours",
                         "compass", "biome", "labels", "track_width_pt", "track_halo",
                         "track_rgb", "marker_diameter_in", "marker_ring",
                         "photo_frame_style", "furniture_scale", "terrain_depth",
                         "shadow_strength", "oblique", "soft_light", "haze_strength",
                         "water_depth", "dry_lakes", "golden_strength", "profile",
                         "profile_height_in", "track_color_by")
             if getattr(first, n) != getattr(plain, n)}
    assert len(moved) == 26, moved
    # these two leave the FORM defaults ("smart", true), which are not the spec's
    assert first.label_place == "anchor" and first.track_weave is False
    _assert_same_picture(first, second)
    form = cont["proof_form"]
    assert form["track_color"] == "#4a6936"       # the #rrggbb string the form takes
    assert form["contours"] is True and form["compass"] is False   # JSON booleans
    assert form["output"] == "print" and form["light_mode"] == "archival"
    # an archival print holds no sun and no device
    assert not {"sun_azimuth_deg", "sun_altitude_deg", "wallpaper_preset",
                "custom_px_w", "custom_px_h", "custom_ppi"} & set(form)
    # additive: the answer's other keys are the ones it had before
    assert set(cont) - {"proof_form"} == {
        "session", "region", "name", "overview", "overview_size", "tracks",
        "track_days", "hotspots", "starter_crop", "recovered", "skipped_duplicates",
        "edition", "files", "year_span", "journey_light", "final_dpi", "prefill"}

def test_proof_form_restores_a_title_less_poster():
    c = _client()
    first, second, cont = _proof_form_round_trip(c, print_w=6, print_h=8, title="-")
    assert first.title_text == ""
    assert cont["proof_form"]["title"] == "-"     # "" would regrow the region name
    _assert_same_picture(first, second)

def test_proof_form_restores_journey_light():
    # the rebuilt tracks carry no timestamps, so the light comes back only through the
    # RESOLVED sun: light_mode + the two angles, and never the scrubber's sun_hour.
    c = _client()
    first, second, cont = _proof_form_round_trip(
        c, print_w=6, print_h=8, light_mode="journey", sun_hour=17.5)
    assert first.light_mode == "journey"
    form = cont["proof_form"]
    assert form["light_mode"] == "journey" and "sun_hour" not in form
    assert form["sun_azimuth_deg"] == first.sun_azimuth_deg
    assert form["sun_altitude_deg"] == first.sun_altitude_deg
    _assert_same_picture(first, second)

def test_proof_form_restores_a_wallpaper_preset():
    c = _client()
    p = wallpaper.PRESETS["desktop_fhd"]
    first, second, cont = _proof_form_round_trip(
        c, ar=p.aspect, output="wallpaper", wallpaper_preset="desktop_fhd")
    form = cont["proof_form"]
    assert form["output"] == "wallpaper" and form["wallpaper_preset"] == "desktop_fhd"
    assert not {"custom_px_w", "custom_px_h", "custom_ppi"} & set(form)
    _assert_same_picture(first, second)

def test_proof_form_restores_a_custom_device():
    # a device the table does not carry comes back as the same custom device
    c = _client()
    first, second, cont = _proof_form_round_trip(
        c, ar=1600 / 900, output="wallpaper", wallpaper_preset="custom",
        custom_px_w=1600, custom_px_h=900, custom_ppi=120)
    form = cont["proof_form"]
    assert form["output"] == "wallpaper" and form["wallpaper_preset"] == "custom"
    assert (form["custom_px_w"], form["custom_px_h"], form["custom_ppi"]) == (1600, 900, 120.0)
    _assert_same_picture(first, second)

def test_proof_form_keys_are_proof_route_parameters():
    # every key is a real /api/proof form field (FastAPI ignores an unknown one, so a
    # misspelled key would silently lose a picture decision) -- and, between a
    # journey-light print and a custom device, every form field the route reads is
    # named, so a field added to the route cannot be forgotten here.
    from app import main
    params = _proof_params()
    wp = wallpaper.custom_preset(1600, 900, 120.0).spec_fields()
    forms = [main._proof_form_for(s) for s in (
        _spec(),
        _spec(light_mode="journey", sun_azimuth_deg=250.0, sun_altitude_deg=20.0),
        _spec(**wp))]
    for form in forms:
        assert set(form) <= params, sorted(set(form) - params)
        assert not set(form) & _NOT_IN_PROOF_FORM
        assert all(v is not None for v in form.values())
    assert set().union(*forms) == params - _NOT_IN_PROOF_FORM


def test_proof_form_makes_each_value_of_a_crafted_spec_a_form_scalar():
    # the spec comes out of an uploaded file, and validate() still lets these through:
    # a title that is not a string, a bool in a number field, a journey with no sun
    from app import main
    form = main._proof_form_for(_spec(title_text=["x", "y"], oblique=True,
                                      track_width_pt=True, light_mode="journey",
                                      sun_azimuth_deg=None, sun_altitude_deg=None))
    assert form["title"] == "-"
    assert form["oblique"] == 1.0 and type(form["oblique"]) is float
    assert type(form["track_width_pt"]) is float
    assert "sun_azimuth_deg" not in form and "sun_altitude_deg" not in form
    assert all(isinstance(v, (str, bool, int, float)) for v in form.values())
    # a title of spaces would regrow the region name at the next proof
    assert main._proof_form_for(_spec(title_text="   "))["title"] == "-"


# ---- endpoint: hostile manifests (the untrusted-input surface) ----

def test_continue_rejects_a_png_without_a_manifest():
    c = _client()
    img = Image.new("RGB", (16, 16), (5, 5, 5))
    buf = io.BytesIO(); img.save(buf, "PNG")
    r = c.post("/api/continue", files={"file": ("plain.png", buf.getvalue(), "image/png")})
    assert r.status_code == 422 and "manifest" in r.json()["detail"].lower()

_VALID_MANIFEST = None

def _valid_manifest():
    """One real edition-1 manifest for the crafted cases below, rendered one time."""
    global _VALID_MANIFEST
    if _VALID_MANIFEST is None:
        _VALID_MANIFEST = json.dumps(_base_manifest(_client()))
    return json.loads(_VALID_MANIFEST)

# A crafted file can put any JSON value in any spec field. Each of these reached the
# render path as a TypeError or an IndexError, which is a 500 and not the 422 that
# provenance.spec_from_manifest promises (it "raises only SpecError").
_WRONG_TYPES = [
    ("print_w_in", "6"), ("print_h_in", None), ("print_w_in", [6]),
    ("native_resolution_m", "10"), ("bleed_in", "0.1"), ("top_clear_frac", [0]),
    ("bottom_clear_frac", {}), ("screen_ppi", "460"),
    ("crop", ["a", "b", "c", "d"]), ("crop", [1.0, 2.0, 3.0]), ("crop", "abcd"),
    ("crop", None), ("crop", [0.0, 0.0, True, 1.0]),
    # a JSON true is an int in Python, so it passed every range check as 1
    ("oblique", True), ("track_width_pt", True), ("soft_light", False),
    ("oblique", "0.5"), ("terrain_depth", None), ("track_max_darken", "x"),
    ("grain_strength", None), ("photo_box_in", {}), ("title_pt", "big"),
    ("label_pt", [9]), ("grain_cell_in", "0.01"),
    ("seed", "7"), ("seed", 7.5), ("seed", True),
    ("title_text", ["x", "y"]), ("title_text", {"a": 1}), ("title_text", 5),
    ("title_text", "x" * 201),
    ("region_id", ["lassen_ca"]), ("region_id", 5), ("region_id", {"a": 1}),
    ("crs", 7), ("crs", None),
    ("contours", "yes"), ("compass", [1]), ("dry_lakes", {}), ("profile", None),
    ("tracks", 5), ("tracks", "abc"),
]
# The reader is tolerant on purpose (invariant 7): it turns these into an empty list,
# so the file opens. The rule for them is only "never a 500".
_TOLERATED = [("hotspots", 5), ("hotspots", "abc"), ("track_days", 5)]

@pytest.mark.parametrize("field,value", _WRONG_TYPES,
                         ids=[f"{f}={json.dumps(v)[:24]}" for f, v in _WRONG_TYPES])
def test_a_crafted_field_type_is_a_422_on_both_file_verbs(field, value):
    c = _client()
    m = _valid_manifest()
    m["spec"][field] = value
    if field == "screen_ppi":                      # read only for a wallpaper
        m["spec"]["output_kind"] = "wallpaper"
    png = _embed(m)
    for verb in ("/api/continue", "/api/reprint"):
        r = c.post(verb, files={"file": ("x.png", png, "image/png")})
        assert r.status_code == 422, f"{verb}: {r.status_code} {r.text[:200]}"
        assert isinstance(r.json()["detail"], str)

@pytest.mark.parametrize("field,value", _TOLERATED,
                         ids=[f"{f}={json.dumps(v)}" for f, v in _TOLERATED])
def test_a_field_the_reader_tolerates_is_never_a_500(field, value):
    c = _client()
    m = _valid_manifest()
    m["spec"][field] = value
    png = _embed(m)
    for verb in ("/api/continue", "/api/reprint"):
        r = c.post(verb, files={"file": ("x.png", png, "image/png")})
        assert r.status_code in (200, 422), f"{verb}: {r.status_code} {r.text[:200]}"

def test_the_valid_manifest_behind_the_crafted_cases_still_reprints():
    # the cases above prove nothing if the base file is refused for another reason
    c = _client()
    png = _embed(_valid_manifest())
    assert c.post("/api/reprint", files={"file": ("x.png", png, "image/png")}).status_code == 200
    assert c.post("/api/continue", files={"file": ("x.png", png, "image/png")}).status_code == 200

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

def test_continue_tolerates_non_list_hotspots_and_track_days():
    # a crafted non-list container (hotspots: null / a number, track_days: a number)
    # must not 500 -- naive iteration (`for hs in None`, `list(5)`) would crash. It is
    # coerced to a safe shape and the request is a clean 200/422, never a 500.
    import copy
    c = _client()
    base = _base_manifest(c)
    for field, bad in [("hotspots", None), ("hotspots", 5), ("track_days", 7)]:
        m = copy.deepcopy(base)
        m["spec"][field] = bad
        r = c.post("/api/continue", files={"file": ("x.png", _embed(m), "image/png")})
        assert r.status_code in (200, 422), f"{field}={bad!r} -> {r.status_code}: {r.text}"

def test_reprint_tolerates_non_list_hotspots():
    # the same untrusted-container guard hardens reprint (drop_unembedded_photos runs
    # before its render try/except, so a non-list hotspots used to 500).
    c = _client()
    m = _base_manifest(c)
    m["spec"]["hotspots"] = None
    r = c.post("/api/reprint", files={"file": ("x.png", _embed(m), "image/png")})
    assert r.status_code in (200, 422)

def test_duplicate_reupload_after_proof_keeps_the_proof():
    # re-dropping a file already on the poster changes nothing, so it must NOT force a
    # needless re-proof: the stamped spec survives and the final still renders.
    c = _client()
    j = c.post("/api/upload", files=[_gpx("2024.gpx", _sample())]).json()
    sid = j["session"]
    r = c.post("/api/proof", data={"session_id": sid, **_crop(j),
                                   "print_w": 6, "print_h": 8})
    assert r.status_code == 200, r.text
    dup = c.post("/api/upload", files=[_gpx("again.gpx", _sample())],
                 data={"session_id": sid}).json()
    assert dup["skipped_duplicates"] == ["again.gpx"]
    assert c.post("/api/final", data={"session_id": sid}).status_code == 200

def test_continue_drops_a_bare_photo_path():
    # a photo carried as a bare filesystem path (never as embedded bytes) must drop, not
    # ride into the resurrected session or 500 a later final. Only embedded bytes survive.
    c = _client()
    m = _base_manifest(c)
    uploads = os.environ["TECOPA_UPLOADS"]
    m["spec"]["hotspots"] = [{"x": 690000.0, "y": 4485000.0, "weight": 1,
                              "photo": os.path.join(uploads, "ghost", "9_gone.jpg")}]
    cont = c.post("/api/continue", files={"file": ("x.png", _embed(m), "image/png")})
    assert cont.status_code == 200, cont.text
    assert cont.json()["hotspots"][0]["photo"] is False

def test_continue_carries_an_embedded_photo_forward():
    # last year's poster carries its pinned photo INSIDE the file, so continuing to the
    # next edition restores that photo with no uploads dir -- the bytes are already here.
    import base64, io
    from PIL import Image as _Image
    from app import provenance
    c = _client()
    m = _base_manifest(c)
    buf = io.BytesIO(); _Image.new("RGB", (80, 80), (200, 30, 120)).save(buf, "JPEG", quality=90)
    uri = provenance.PHOTO_DATA_PREFIX + base64.b64encode(buf.getvalue()).decode("ascii")
    m["spec"]["hotspots"] = [{"x": 690000.0, "y": 4485000.0, "weight": 1, "photo": uri}]
    cont = c.post("/api/continue", files={"file": ("x.png", _embed(m), "image/png")})
    assert cont.status_code == 200, cont.text
    assert cont.json()["hotspots"][0]["photo"] is True     # the embedded photo survived


# ---- track-level dedup (a re-exported folder must not double-count journeys) ----
# A track's identity is its GEOMETRY (coords), not its file: the same recording arriving
# in a different file (a re-exported folder, or a continued edition) must dedup, while a
# genuinely different track is always kept. Fixtures make the "different" track differ in
# geometry, not just date -- coords is the key, so a date-only change would (correctly)
# still read as the same track.

# two distinct in-region single tracks (synthetic, so track counts are exact); the
# sample.gpx fixture parses to several tracks, which would make counts ambiguous here.
_PTS_A = [(40.4160, -120.6530), (40.4170, -120.6550), (40.4180, -120.6530),
          (40.4190, -120.6550), (40.4200, -120.6540)]
_PTS_B = [(40.4400, -120.6900), (40.4410, -120.6920), (40.4420, -120.6900),
          (40.4430, -120.6920), (40.4440, -120.6910)]

def _trk(name, pts, date="2024-06-01"):
    body = "".join(f'<trkpt lat="{la:.6f}" lon="{lo:.6f}">'
                   f'<time>{date}T07:3{i}:00Z</time></trkpt>' for i, (la, lo) in enumerate(pts))
    return f'<trk><name>{name}</name><trkseg>{body}</trkseg></trk>'

def _gpx_doc(*trks):
    return ('<?xml version="1.0"?><gpx version="1.1" creator="t" '
            'xmlns="http://www.topografix.com/GPX/1/1">' + "".join(trks) + '</gpx>').encode()

def _A():  return _gpx_doc(_trk("A", _PTS_A))                       # track A alone
def _A2(): return _gpx_doc(_trk("A-renamed", _PTS_A))              # A's geometry, different bytes
def _B():  return _gpx_doc(_trk("B", _PTS_B))                       # a distinct track
def _AB(): return _gpx_doc(_trk("A", _PTS_A), _trk("B", _PTS_B))   # a folder holding both


def test_track_key_survives_the_spec_json_round_trip():
    # the cross-edition guarantee: a track rebuilt from a serialized spec (what
    # /api/continue does) hashes identically to the freshly-parsed original, so re-dropping
    # last year's GPX onto a continued poster dedups.
    from app.main import _track_key, REGIONS
    from app.ingest import Track, load_tracks
    tracks = load_tracks(_A(), REGIONS["lassen_ca"].geo)
    assert tracks
    for t in tracks:
        rebuilt = Track(track_id="x", coords=np.asarray(t.coords.tolist(), dtype=float), day=t.day)
        assert _track_key(rebuilt) == _track_key(t)

def test_upload_dedups_a_track_already_on_the_poster():
    c = _client()
    j1 = c.post("/api/upload", files=[_gpx("a.gpx", _A())]).json()
    sid = j1["session"]; n1 = len(j1["tracks"])
    # a re-exported folder holding the SAME track plus a new one
    j2 = c.post("/api/upload", files=[_gpx("folder.gpx", _AB())],
                data={"session_id": sid}).json()
    assert j2["skipped_duplicate_tracks"] == 1          # track A was already present
    assert len(j2["tracks"]) == n1 + 1                  # only track B was added

def test_reexport_of_present_tracks_preserves_the_proof():
    # re-dropping tracks already on the poster (different file bytes, same geometry) must
    # be a no-op that does NOT force a re-proof.
    c = _client()
    j = c.post("/api/upload", files=[_gpx("a.gpx", _A())]).json(); sid = j["session"]
    assert c.post("/api/proof", data={"session_id": sid, **_crop(j),
                                      "print_w": 6, "print_h": 8}).status_code == 200
    j2 = c.post("/api/upload", files=[_gpx("again.gpx", _A2())],
                data={"session_id": sid}).json()
    assert j2["skipped_duplicate_tracks"] == 1
    assert c.post("/api/final", data={"session_id": sid}).status_code == 200   # proof survived

def test_intra_batch_track_dedup_on_a_fresh_session():
    # the same geometry dropped twice in one batch (two files) collapses to one track.
    c = _client()
    j = c.post("/api/upload", files=[_gpx("a.gpx", _A()),
                                     _gpx("a2.gpx", _A2()),
                                     _gpx("b.gpx", _B())]).json()
    assert j["skipped_duplicate_tracks"] == 1           # a.gpx and a2.gpx share geometry
    assert len(j["tracks"]) == 2                         # A + B

def test_continue_then_reexport_dedups_across_editions():
    # the headline scenario: finish an edition-1 poster, continue it, then drop a
    # re-exported folder that still contains last year's track plus a new one. Last year's
    # track dedups across the edition boundary; only the new track is added.
    c = _client()
    _, png, _ = _final_png(c, [_gpx("2024.gpx", _A())])
    sid = c.post("/api/continue", files={"file": ("poster.png", png, "image/png")}).json()["session"]
    j = c.post("/api/upload", files=[_gpx("folder.gpx", _AB())],
               data={"session_id": sid}).json()
    assert j["skipped_duplicate_tracks"] == 1            # edition-1 track carried in the poster
    assert len(j["tracks"]) == 2                         # edition-1 track + the new one
