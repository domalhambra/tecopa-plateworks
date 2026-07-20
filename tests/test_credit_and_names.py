# tests/test_credit_and_names.py
"""Honesty & continuity, phase 5: the data credit rides the spec; the filename says
what the file is.

`spec.credit_text` is derived server-side from the region's sources.json at proof
time (never a client knob), bounded in validate() because a crafted manifest rides it
straight into the renderer, and painted as a third cartouche row when a title block
exists. `download_name` makes every deliverable self-documenting
(tecopa_<region>[_edition-<n>][_<years>][kind].<ext>) -- a pure function of the
spec, carried on the blob key so every serving path names the file the same way."""
import io
import json
import os
import time

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app import provenance, render
from app.spec import CompositionSpec, SpecError, CREDIT_MAX_CHARS, year_span

REGION_DIR = "regions/lassen_ca"

# what regions/lassen_ca/sources.json's four USGS datasets map to
LASSEN_CREDIT = ("Terrain USGS 3DEP - Water USGS NHD - "
                 "Land cover NLCD 2021 - Names USGS GNIS")


# ---- helpers (the test_editions idiom) ----

def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

def _sample():
    return open("tests/fixtures/sample.gpx", "rb").read()

def _gpx(name, data):
    return ("files", (name, data, "application/gpx+xml"))

def _crop(j, km_wide=40.0, ar=0.75):
    cfg = json.load(open(f"{REGION_DIR}/region.json"))
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (km_wide * 1000.0 / region_w); ch = cw / ar
    x0 = ovw * 0.5 - cw / 2; y0 = ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch}

def _proofed(c, files=None, proof_extra=None):
    j = c.post("/api/upload", files=files or [_gpx("2024.gpx", _sample())]).json()
    sid = j["session"]
    data = {"session_id": sid, **_crop(j), "print_w": 6, "print_h": 8, "title": "Trip"}
    data.update(proof_extra or {})
    r = c.post("/api/proof", data=data)
    assert r.status_code == 200, r.text
    return sid, j

def _embed(manifest):
    img = Image.new("RGB", (16, 16), (20, 20, 20))
    buf = io.BytesIO(); img.save(buf, "PNG", pnginfo=provenance.manifest_pnginfo(manifest))
    return buf.getvalue()

def _spec(**kw):
    base = dict(region_id="lassen_ca", crs="EPSG:32610",
                crop=(674744.83, 4459659.23, 714744.83, 4512992.56),
                print_w_in=9, print_h_in=12, native_resolution_m=10,
                tracks=[np.array([[680000.0, 4470000.0], [700000.0, 4500000.0]])],
                track_days=["2024-06-01"], hotspots=[])
    base.update(kw)
    return CompositionSpec(**base)


# ---- unit: year_span lives on spec.py (one implementation for main + render) ----

def test_year_span_relocated_to_spec():
    assert year_span(["2024-06-01", "2026-07-04"]) == "2024–2026"
    assert year_span(["2024-06-01", "2024-09-01"]) == "2024"
    assert year_span([None, None]) == ""
    assert year_span(None) == ""

def test_render_year_span_delegates_to_spec():
    s = _spec(track_days=["2023-01-01", "2025-12-31"])
    assert render._year_span(s) == year_span(s.track_days) == "2023–2025"

def test_year_span_ignores_non_ascii_digits():
    # str.isdigit() accepts Unicode digits ('٢٠٢٣'.isdigit() is True), but those are
    # not latin-1 encodable: they'd ride download_name into the hand-built
    # Content-Disposition header and 500 the reprint AFTER the full render was spent.
    # Not [0-9] -> not a year; the day still renders, it just carries no span.
    assert year_span(["٢٠٢٣-06-01"]) == ""            # Arabic-Indic digits
    assert year_span(["²⁰²⁴-06-01", "2024-06-01"]) == "2024"   # superscripts

def test_download_name_is_latin1_safe_for_crafted_track_days():
    from app.main import download_name
    name = download_name(_spec(track_days=["٢٠٢٣-06-01"]))
    assert name == "tecopa_lassen_ca.png"
    name.encode("latin-1")   # what Starlette's header encoding requires


# ---- unit: download_name ----

def test_download_name_edition_one_has_no_edition_suffix():
    from app.main import download_name
    s = _spec(edition=1, track_days=["2024-06-01"])
    assert download_name(s) == "tecopa_lassen_ca_2024.png"

def test_download_name_edition_three_with_span():
    from app.main import download_name
    s = _spec(edition=3, track_days=["2024-06-01", "2026-07-04"])
    assert download_name(s) == "tecopa_lassen_ca_edition-3_2024-2026.png"
    # charset by construction: [a-z0-9._-] only
    assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789._-" for c in download_name(s))

def test_download_name_dayless_has_no_span():
    from app.main import download_name
    s = _spec(track_days=[None])
    assert download_name(s, fmt="pdf") == "tecopa_lassen_ca.pdf"

def test_download_name_film_and_wallpaper_kinds():
    from app.main import download_name
    s = _spec(edition=2, track_days=["2024-06-01", "2025-06-01"])
    assert download_name(s, kind="_film", fmt="webp") == \
        "tecopa_lassen_ca_edition-2_2024-2025_film.webp"
    assert download_name(s, kind="_wallpapers", fmt="zip") == \
        "tecopa_lassen_ca_edition-2_2024-2025_wallpapers.zip"


# ---- unit: credit_line (derived from sources.json) ----

def _region_stub(tmp_path, sources=None, write=True):
    class R:
        dir = str(tmp_path)
    if write:
        with open(os.path.join(str(tmp_path), "sources.json"), "w") as f:
            json.dump({"assets": {}, "sources": sources or []}, f)
    return R()

def test_credit_line_maps_the_known_datasets(tmp_path):
    from app.main import credit_line
    r = _region_stub(tmp_path, [
        {"dataset": "USGS 3DEP 10 m DEM"},
        {"dataset": "USGS NHD waterbodies + network flowlines"},
        {"dataset": "NLCD 2021 land cover (30 m)"},
        {"dataset": "USGS GNIS Landforms"},
    ])
    assert credit_line(r) == LASSEN_CREDIT

def test_credit_line_unrecognized_dataset_passes_through_verbatim(tmp_path):
    # the point of data-driving this: a future non-PD plate automatically carries
    # its required credit instead of relying on memory.
    from app.main import credit_line
    r = _region_stub(tmp_path, [{"dataset": "USGS 3DEP 10 m DEM"},
                                {"dataset": "Ordnance Survey OpenData (OGL v3)"}])
    assert credit_line(r) == "Terrain USGS 3DEP - Ordnance Survey OpenData (OGL v3)"

def test_credit_line_missing_or_empty_sources_is_blank(tmp_path):
    from app.main import credit_line
    assert credit_line(_region_stub(tmp_path, write=False)) == ""   # no sources.json
    assert credit_line(_region_stub(tmp_path, sources=[])) == ""    # empty list

def test_credit_line_is_always_spec_valid(tmp_path):
    # derived truth must never 422 a proof: non-ASCII drops, the length caps
    from app.main import credit_line
    r = _region_stub(tmp_path, [{"dataset": "Données Québec " + "x" * 300}])
    line = credit_line(r)
    assert len(line) <= CREDIT_MAX_CHARS
    _spec(credit_text=line).validate(300)


# ---- unit: the spec field (bounded, drift-tolerant) ----

def test_credit_text_defaults_empty_and_serializes():
    from app import serialize
    m = json.load(open("tests/fixtures/manifest_v1.json"))
    spec = provenance.manifest_to_spec(m)                 # old manifest: no field
    assert spec.credit_text == ""
    back = serialize.spec_from_json(serialize.spec_to_json(_spec(credit_text="A - B")))
    assert back.credit_text == "A - B"

def test_spec_to_json_omits_the_default_credit_text():
    # the additive contract (docs/MANIFEST.md): an added key is OMITTED when absent,
    # so a pre-credit poster's manifest re-stamps byte-identically on reprint --
    # emitting "credit_text": "" would falsify the forever-contract's sha256 check.
    from app import serialize
    assert "credit_text" not in serialize.spec_to_json(_spec())
    assert serialize.spec_to_json(_spec(credit_text="A"))["credit_text"] == "A"

def test_credit_text_bounds_rejected():
    with pytest.raises(SpecError, match=str(CREDIT_MAX_CHARS)):
        _spec(credit_text="x" * (CREDIT_MAX_CHARS + 1)).validate(300)
    with pytest.raises(SpecError):
        _spec(credit_text="evil\x07bytes").validate(300)
    with pytest.raises(SpecError):
        _spec(credit_text=None).validate(300)
    _spec(credit_text="Terrain USGS 3DEP").validate(300)  # a real credit passes


# ---- unit: the cartouche grows a credit row ----

def test_title_block_metrics_grow_when_credit_present():
    d = ImageDraw.Draw(Image.new("RGBA", (100, 100)), "RGBA")
    s0 = _spec(title_text="Eagle Lake")
    s1 = _spec(title_text="Eagle Lake", credit_text=LASSEN_CREDIT)
    m0 = render._title_block_metrics(s0, d, dpi=96)
    m1 = render._title_block_metrics(s1, d, dpi=96)
    assert m1["bh"] > m0["bh"], "credit row did not add height to the plate"
    assert m1["credit"] == LASSEN_CREDIT.upper()          # tracked caps, like the stats

def test_credit_paints_only_inside_a_title_block():
    w = h = 500
    blank = lambda: Image.new("RGBA", (w, h), (128, 128, 128, 255))
    with_credit = render._draw_title_block(
        blank(), _spec(title_text="Eagle Lake", credit_text="Terrain USGS 3DEP"),
        w, h, dpi=96)
    without = render._draw_title_block(
        blank(), _spec(title_text="Eagle Lake"), w, h, dpi=96)
    assert not np.array_equal(np.asarray(with_credit), np.asarray(without))
    # no title block (clean mode) -> no credit painted, the sheet is untouched
    base = np.asarray(blank().convert("RGB"))
    clean = render._draw_title_block(
        blank(), _spec(title_text="", credit_text="Terrain USGS 3DEP"), w, h, dpi=96)
    assert np.array_equal(base, np.asarray(clean.convert("RGB")))


# ---- endpoint: proof stamps the credit; the manifest carries it ----

def test_proof_stamps_credit_text_on_the_session_spec():
    from app import session
    c = _client()
    sid, _ = _proofed(c)
    spec = session.get(sid)["spec"]
    assert spec.credit_text == LASSEN_CREDIT
    png = c.post("/api/final", data={"session_id": sid}).content
    m = provenance.extract(png)
    assert m["spec"]["credit_text"] == LASSEN_CREDIT

def test_reprint_rejects_a_crafted_credit_text():
    c = _client()
    sid, _ = _proofed(c)
    png = c.post("/api/final", data={"session_id": sid}).content
    base = provenance.extract(png)
    for bad in ("x" * (CREDIT_MAX_CHARS + 1), "evil\x07credit", "café"):
        m = json.loads(json.dumps(base))
        m["spec"]["credit_text"] = bad
        r = c.post("/api/reprint", files={"file": ("x.png", _embed(m), "image/png")})
        assert r.status_code == 422, r.text
        assert "credit_text" in r.json()["detail"]


# ---- endpoint: every serving path names the file the same way ----

def test_sync_final_content_disposition_is_self_documenting():
    c = _client()
    sid, _ = _proofed(c)
    r = c.post("/api/final", data={"session_id": sid})
    assert r.status_code == 200
    # sample.gpx's tracks are all 2024, edition 1 -> no edition suffix, a year span
    assert 'filename="tecopa_lassen_ca_2024.png"' in r.headers["content-disposition"]

def test_job_result_serves_the_blob_keys_basename():
    c = _client()
    sid, _ = _proofed(c)
    sub = c.post("/api/final/submit", data={"session_id": sid})
    assert sub.status_code == 200, sub.text
    jid = sub.json()["job"]
    for _ in range(3000):
        s = c.get(f"/api/jobs/{jid}").json()
        if s["state"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert s["state"] == "done", s
    r = c.get(f"/api/jobs/{jid}/result")
    assert r.headers["content-type"] == "image/png"
    assert 'filename="tecopa_lassen_ca_2024.png"' in r.headers["content-disposition"]

def test_reprint_names_the_file_from_the_reprinted_spec():
    c = _client()
    sid, _ = _proofed(c)
    png = c.post("/api/final", data={"session_id": sid}).content
    r = c.post("/api/reprint", files={"file": ("poster.png", png, "image/png")})
    assert r.status_code == 200, r.text
    assert 'filename="tecopa_lassen_ca_2024.png"' in r.headers["content-disposition"]

def test_reprint_survives_crafted_unicode_track_days():
    # a crafted manifest whose track_days use Arabic-Indic digits used to 500
    # (UnicodeEncodeError in the latin-1 Content-Disposition header) AFTER the full
    # print-resolution render was spent. Now: no ASCII year, no span -- a clean 200.
    c = _client()
    sid, _ = _proofed(c)
    png = c.post("/api/final", data={"session_id": sid}).content
    m = json.loads(json.dumps(provenance.extract(png)))
    m["spec"]["track_days"] = ["٢٠٢٣-06-01"]
    r = c.post("/api/reprint", files={"file": ("x.png", _embed(m), "image/png")})
    assert r.status_code == 200, r.text
    assert 'filename="tecopa_lassen_ca.png"' in r.headers["content-disposition"]
