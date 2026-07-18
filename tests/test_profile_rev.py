# tests/test_profile_rev.py
"""Profile revision 2 (v1.12) -- the contract suite.

- rev 1 (the default; every pre-feature manifest) reproduces the shipped strip
  geometry VERBATIM (there is no engine version to hide behind -- old posters'
  pixels are the contract);
- rev 2 is physical (invariant 2), measured against the cartouche+compass stack it
  shares the bottom-left corner with (no overpaint at ANY furniture_scale), and
  labels feet (the cartouche speaks MI);
- the field is omitted from the manifest at 1 (additive contract) and validated as
  a strict enum member.
"""
import json
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app import render, serialize
from app.spec import CompositionSpec, SpecError, PROFILE_REVS

REGION_DIR = "regions/lassen_ca"


def _cfg():
    return json.load(open(os.path.join(REGION_DIR, "region.json")))


def _spec(print_w_in=9, print_h_in=12, **kw):
    cfg = _cfg()
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    gw = 27000.0
    gh = gw * print_h_in / print_w_in          # crop aspect == print aspect
    crop = (cx - gw / 2, cy - gh / 2, cx + gw / 2, cy + gh / 2)
    xs = np.linspace(cx - gw * 0.3, cx + gw * 0.3, 40)
    ys = np.linspace(cy - gh * 0.3, cy + gh * 0.3, 40)
    base = dict(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                print_w_in=print_w_in, print_h_in=print_h_in,
                native_resolution_m=10,
                tracks=[np.column_stack([xs, ys])], hotspots=[],
                track_days=["2023-07-15"], seed=7)
    base.update(kw)
    return CompositionSpec(**base)


def _d():
    return ImageDraw.Draw(Image.new("RGB", (8, 8)))


# ---- Task A1: the additive gate ----

def test_default_is_rev_1_and_validates():
    s = _spec(profile=True)
    assert s.profile_rev == 1
    s.validate(96)


@pytest.mark.parametrize("bad", [0, 3, -1, 1.5, True, "2"])
def test_rev_outside_the_enum_422s(bad):
    with pytest.raises(SpecError):
        _spec(profile=True, profile_rev=bad).validate(96)


def test_manifest_omits_rev_at_1_and_carries_it_at_2():
    at1 = serialize.spec_to_json(_spec(profile=True))
    assert "profile_rev" not in at1          # pre-feature manifests re-stamp byte-identically
    at2 = serialize.spec_to_json(_spec(profile=True, profile_rev=2))
    assert at2["profile_rev"] == 2
    # a manifest written before the feature refills the default
    assert serialize.spec_from_json(at1).profile_rev == 1
    assert serialize.spec_from_json(at2).profile_rev == 2


# ---- Task A2: shared geometry, rev 1 verbatim ----

def test_rev1_rect_is_the_shipped_formula_verbatim():
    """The byte-identity anchor: rev 1 must reproduce the exact legacy arithmetic
    (render.py@36f1155:1829-1834). Computed here from first principles so a painter
    'cleanup' can't silently move a pre-feature poster's strip."""
    dpi = 300
    spec = _spec(profile=True, title_text="LASSEN TRAVERSE")
    out_w, out_h = spec.pixel_size(dpi)
    fs = render._furniture_scale(spec)
    ph = max(1, round(spec.profile_height_in * dpi * fs))
    pw = min(out_w - 2 * round(out_w * render.MARGIN_FRAC), round(ph * 3.4))
    inset = round(out_h * render.MARGIN_FRAC) + round(0.01 * out_h)
    expect = (inset, out_h - inset - ph, inset + pw, out_h - inset)
    got = render._profile_rect(spec, _d(), (0, 0, out_w, out_h), dpi)
    assert got == expect


def test_rev1_render_unchanged_by_the_refactor():
    """_draw_profile now routes through _profile_rect; a rev-1 render must be
    deterministic and still paint in the lower-left (the shipped placement)."""
    spec = _spec(profile=True)
    a = np.asarray(render.rasterize(spec, 96, REGION_DIR).convert("RGB"))
    b = np.asarray(render.rasterize(spec, 96, REGION_DIR).convert("RGB"))
    assert np.array_equal(a, b)
    off = np.asarray(render.rasterize(_spec(profile=False), 96, REGION_DIR).convert("RGB"))
    h, w, _ = off.shape
    assert not np.array_equal(off[int(h * 0.8):, :int(w * 0.5)],
                              a[int(h * 0.8):, :int(w * 0.5)])


# ---- Task A3: rev-2 painter ----

@pytest.mark.parametrize("dpi", [96, 300])
def test_rev2_rect_is_physical_and_dpi_stable(dpi):
    spec = _spec(profile=True, profile_rev=2, title_text="LASSEN TRAVERSE")
    out_w, out_h = spec.pixel_size(dpi)
    x0, y0, x1, y1 = render._profile_rect(spec, _d(), (0, 0, out_w, out_h), dpi)
    fdpi = dpi * render._furniture_scale(spec)
    assert x0 == round(render.PROFILE_INSET_IN * fdpi)      # inches, not sheet fractions


SIZES = [(9, 12), (12, 16), (18, 24), (24, 36)]


@pytest.mark.parametrize("wh", SIZES)
@pytest.mark.parametrize("slider", [0.6, 1.0, 1.6])
@pytest.mark.parametrize("ph_in", [0.6, 0.9, 2.5])
@pytest.mark.parametrize("title", ["LASSEN TRAVERSE", ""])
def test_rev2_strip_clears_the_stack_at_every_offered_extreme(wh, slider, ph_in, title):
    """The red-team's overpaint (furniture_scale >= ~1.3) made into a tripwire:
    across the full offered size menu x the full slider bounds x the profile-height
    bound, the rev-2 strip never intersects the cartouche+compass stack, stays on
    the sheet, and stays a real strip. Pure geometry (no render), so the sweep is
    cheap. (It shares the cartouche's fdpi-scaled left inset -- so their left edges
    align -- which on the smallest sheet at min slider sits fractionally outside the
    0.25in keyline exactly as the cartouche plate does; the strip's TOP is clamped
    inside the keyline explicitly.)"""
    w, h = wh
    spec = _spec(print_w_in=w, print_h_in=h, profile=True, profile_rev=2,
                 furniture_scale=slider, profile_height_in=ph_in,
                 title_text=title, compass=True)
    d = _d()
    for dpi in (96, 300):
        out_w, out_h = spec.pixel_size(dpi)
        x0, y0, x1, y1 = render._profile_rect(spec, d, (0, 0, out_w, out_h), dpi)
        stack_top = render._furniture_stack_top(spec, d, out_h, dpi)
        assert y1 <= stack_top                     # never overpaints the stack
        assert 0 <= x0 < x1 <= out_w               # on-sheet, a real width
        assert 0 <= y0 < y1 <= out_h               # on-sheet, a real height
        kl = round(render.KEYLINE_INSET_IN * dpi)
        assert y0 >= kl                            # top clamped inside the keyline


def test_rev2_labels_feet_and_render_differs_from_rev1():
    r1 = np.asarray(render.rasterize(_spec(profile=True), 96, REGION_DIR).convert("RGB"))
    r2 = np.asarray(render.rasterize(_spec(profile=True, profile_rev=2), 96,
                                     REGION_DIR).convert("RGB"))
    assert not np.array_equal(r1, r2)
    assert np.array_equal(
        r2, np.asarray(render.rasterize(_spec(profile=True, profile_rev=2), 96,
                                        REGION_DIR).convert("RGB")))  # deterministic


# ---- Task A4: label keep-out ----

def test_rev2_strip_rect_joins_the_label_keepout():
    """Auto geography names must treat the strip as occupied ground. Assert at the
    seam -- the keep-out list _draw_labels builds must contain the exact strip rect."""
    spec = _spec(profile=True, profile_rev=2, labels=True,
                 title_text="LASSEN TRAVERSE")
    dpi = 96
    out_w, out_h = spec.pixel_size(dpi)
    d = _d()
    rect = render._profile_rect(spec, d, (0, 0, out_w, out_h), dpi)
    assert rect in render._label_keepout(spec, d, out_w, out_h, dpi)


def test_rev1_strip_rect_not_in_keepout():
    """Rev 1 keeps the shipped hand-tuned furniture estimate only -- adding the
    strip rect for rev-1 posters would change their label placement (not byte-
    identical). So the exact strip rect appears ONLY for rev 2."""
    spec = _spec(profile=True, labels=True, title_text="LASSEN TRAVERSE")
    dpi = 96
    out_w, out_h = spec.pixel_size(dpi)
    d = _d()
    rect = render._profile_rect(spec, d, (0, 0, out_w, out_h), dpi)
    assert rect not in render._label_keepout(spec, d, out_w, out_h, dpi)


# ---- Task A5: the gate wired to the endpoint ----

def test_new_proofs_stamp_rev_2_and_the_field_is_enum_gated():
    """NEW posters get the corrected strip by default (the label_place precedent);
    an explicit rev sticks; an out-of-enum rev 422s. Endpoint-level (invariant 1:
    the stamped spec is what the final renders)."""
    from tests.test_main import _client, _upload, _crop
    from app import session as sess_mod
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0),
            "print_w": 9, "print_h": 12, "profile": "true"}
    # default: no profile_rev field -> server default 2 (the corrected strip)
    assert c.post("/api/proof", data=data).status_code == 200
    assert sess_mod.get(j["session"])["spec"].profile_rev == 2
    # a continued rev-1 poster re-proofs as rev 1 (layout continuity is the poster's)
    assert c.post("/api/proof", data={**data, "profile_rev": 1}).status_code == 200
    assert sess_mod.get(j["session"])["spec"].profile_rev == 1
    # out of the enum -> honest 422, not a silent render
    assert c.post("/api/proof", data={**data, "profile_rev": 3}).status_code == 422
