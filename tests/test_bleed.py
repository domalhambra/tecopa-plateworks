# tests/test_bleed.py
"""Bleed/trim (v1.12) -- the contract suite.

- bleed_in 0 (the default; every pre-feature manifest) is the EXACT pre-feature
  sheet: sheet_geometry returns the spec object itself, the trim box is the canvas;
- the canvas is trim + 2*bleed; the zoom cap is judged on the TRIM mapping
  (ground-per-pixel is bleed-invariant, so toggling bleed can't flip a crop across
  the cap); the MP ceiling is judged on the CANVAS (that is what gets allocated);
- bleed is print-only (a screen has no trimmer) and the bleed band is REAL terrain
  (off-DEM refusal extends to it -- invariant 5);
- furniture measures from the trim box; the final PNG/PDF page carries the canvas.
"""
import io
import json
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app import render, serialize
from app.spec import CompositionSpec, SpecError, OffDemError, BLEED_MAX_IN
# _cfg/_spec: the same helpers as tests/test_profile_rev.py
from tests.test_profile_rev import _cfg, _spec

REGION_DIR = "regions/lassen_ca"


# ---- Task B1: the field, canvas vs trim ----

def test_default_zero_and_bounds():
    s = _spec()
    assert s.bleed_in == 0.0
    s.validate(96)
    _spec(bleed_in=0.125).validate(96)
    for bad in (-0.1, BLEED_MAX_IN + 0.01, float("nan"), float("inf")):
        with pytest.raises(SpecError):
            _spec(bleed_in=bad).validate(96)


def test_bleed_is_print_only():
    with pytest.raises(SpecError):
        _spec(bleed_in=0.125, output_kind="wallpaper", screen_ppi=460,
              print_w_in=2.62, print_h_in=5.7).validate(96)


def test_canvas_is_trim_plus_bleed_and_cap_is_trim_judged():
    s = _spec(print_w_in=9, print_h_in=12, bleed_in=0.125)
    assert s.pixel_size(96) == (round(9.25 * 96), round(12.25 * 96))
    assert s.pixel_size(300) == (2775, 3675)
    # ground_per_pixel is bleed-invariant (trim mapping)
    assert abs(_spec().ground_per_pixel(300) - s.ground_per_pixel(300)) < 1e-9
    # a crop exactly at the zoom-cap floor without bleed must still clear it WITH bleed
    _spec().validate(300)
    _spec(bleed_in=0.125).validate(300)


# ---- Task B2: manifest omission ----

def test_manifest_omits_bleed_at_zero_and_round_trips():
    assert "bleed_in" not in serialize.spec_to_json(_spec())
    j = serialize.spec_to_json(_spec(bleed_in=0.125))
    assert j["bleed_in"] == 0.125
    assert serialize.spec_from_json(j).bleed_in == 0.125
    assert serialize.spec_from_json(serialize.spec_to_json(_spec())).bleed_in == 0.0


# ---- Task B3: the sheet_geometry seam ----

def test_sheet_geometry_identity_at_zero():
    """The no-op proof: at bleed 0 the paint-spec IS the spec (same object -- no
    copy, no drift surface) and the trim box IS the canvas."""
    s = _spec()
    paint, trim = render.sheet_geometry(s, 96)
    assert paint is s
    assert trim == (0, 0, *s.pixel_size(96))


def test_sheet_geometry_grows_crop_by_the_bleed_ground_band():
    s = _spec(print_w_in=9, print_h_in=12, bleed_in=0.125)
    paint, trim = render.sheet_geometry(s, 300)
    gpi = (s.crop[2] - s.crop[0]) / s.print_w_in
    b = 0.125 * gpi
    assert paint.crop == pytest.approx((s.crop[0] - b, s.crop[1] - b,
                                        s.crop[2] + b, s.crop[3] + b))
    assert (paint.print_w_in, paint.print_h_in) == (9.25, 12.25)
    assert paint.bleed_in == 0.0                       # no consumer can double-apply
    assert paint.pixel_size(300) == s.pixel_size(300)  # one canvas, two views
    bpx = round(0.125 * 300)
    w, h = s.pixel_size(300)
    assert trim == (bpx, bpx, w - bpx, h - bpx)


def test_bleed_render_is_bigger_and_deterministic():
    s0, s1 = _spec(), _spec(bleed_in=0.125)
    r0 = render.rasterize(s0, 96, REGION_DIR)
    r1 = render.rasterize(s1, 96, REGION_DIR)
    assert r1.size == s1.pixel_size(96) and r1.size != r0.size
    assert np.array_equal(np.asarray(r1),
                          np.asarray(render.rasterize(s1, 96, REGION_DIR)))


def test_offdem_refusal_extends_to_the_bleed_band():
    """Invariant 5 across the trim line: a crop that renders clean at bleed 0 must
    refuse when the bleed band would overhang the DEM. Find a crop hugging the
    region's data edge that is clean without bleed, then assert bleed makes it
    refuse -- the point is the delta, not the absolute."""
    cfg = _cfg()
    bx = cfg["bounds"]
    gw = 27000.0
    gh = gw * 12 / 9
    # push the crop's south/west edge hard against the region bound so a fat bleed
    # band overhangs real data. Nudge inward until bleed 0 is clean.
    for pad in (0.0, 200.0, 500.0, 1000.0, 2000.0):
        crop = (bx[0] + pad, bx[1] + pad, bx[0] + pad + gw, bx[1] + pad + gh)
        s0 = _spec(crop=crop)
        try:
            render.rasterize(s0, 96, REGION_DIR)
        except OffDemError:
            continue                # still overhanging at bleed 0; nudge further in
        # bleed 0 is clean here -- a big bleed band must now overhang and refuse
        with pytest.raises(OffDemError):
            render.rasterize(_spec(crop=crop, bleed_in=0.5), 96, REGION_DIR)
        return
    pytest.skip("no crop on this synthetic DEM is clean at bleed 0 yet edge-close "
                "enough for a 0.5in band to overhang")


# ---- Task B4: furniture measures from the trim box ----

def _blank(w, h):
    return Image.new("RGB", (w, h), (240, 238, 230))


def test_keyline_measures_from_the_trim_box():
    w, h, b = 900, 1200, 12                      # 12 px of bleed on a fake canvas
    dpi = 96
    plain = np.asarray(render._draw_keyline(_blank(w, h), w, h, dpi))
    inset = round(render.KEYLINE_INSET_IN * dpi)
    shifted = np.asarray(render._draw_keyline(
        _blank(w + 2 * b, h + 2 * b), w + 2 * b, h + 2 * b, dpi,
        trim=(b, b, w + b, h + b)))
    # the same keyline, translated by exactly the bleed: trim-relative furniture
    assert np.array_equal(plain[inset:inset + 3, inset:inset + 3],
                          shifted[b + inset:b + inset + 3, b + inset:b + inset + 3])


def test_full_bleed_render_keeps_furniture_off_the_bleed_band():
    """End to end: on a bleed render, the outer band (everything past the trim box)
    contains terrain only -- no keyline ink. The keyline is the darkest furniture;
    assert the band is free of its ink color while the trim ring contains it."""
    s = _spec(bleed_in=0.125, title_text="LASSEN TRAVERSE", profile=True,
              profile_rev=2)
    img = np.asarray(render.rasterize(s, 96, REGION_DIR).convert("RGB"))
    bpx = round(0.125 * 96)
    kl = round(render.KEYLINE_INSET_IN * 96)
    ink = np.array(render.TERMINUS_INK)

    def has_ink(region):
        return (np.abs(region.astype(int) - ink).sum(axis=-1) < 60).any()

    assert not has_ink(img[:bpx, :])             # top bleed band: terrain only
    assert has_ink(img[bpx + kl, bpx + kl:img.shape[1] - bpx - kl])  # keyline row


# ---- Task B5: the deliverables ----

def test_pdf_page_grows_by_the_bleed():
    """9x12 + 0.125 bleed @300 -> 2775x3675 px -> 666x882 pt page. Follows the
    MediaBox assertion pattern of tests/test_main.py."""
    import re
    from app.main import _encode_final
    s = _spec(print_w_in=9, print_h_in=12, bleed_in=0.125)
    img = render.rasterize(s, 300, REGION_DIR)
    pdf = _encode_final(img.convert("RGB"), "pdf")
    m = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)", pdf)
    assert m and (round(float(m.group(1))), round(float(m.group(2)))) == (666, 882)


def test_proof_is_trim_only_but_stamped_spec_keeps_the_bleed():
    """Endpoint: the proof PNG comes back at the TRIM size (the bleed band cropped
    off the preview), while the STAMPED spec keeps bleed_in so the FINAL renders the
    full canvas. Uses the test_main session helpers."""
    from tests.test_main import _client, _upload, _crop
    from app import session as sess_mod
    from app.main import _proof_dpi
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0),
            "print_w": 9, "print_h": 12, "bleed": 0.125}
    r = c.post("/api/proof", data=data)
    assert r.status_code == 200
    spec = sess_mod.get(j["session"])["spec"]
    assert spec.bleed_in == 0.125                       # the final will carry the bleed
    pdpi = _proof_dpi(spec)
    trim_w = round(spec.print_w_in * pdpi)              # 9 in at proof dpi
    got_w, got_h = Image.open(io.BytesIO(r.content)).size
    assert abs(got_w - trim_w) <= 1                     # trim-only preview (+-1px rounding)
    # and it is SMALLER than the full canvas the final would deliver
    assert got_w < spec.pixel_size(pdpi)[0]
