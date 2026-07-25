# tests/test_relief_rev.py
"""The relief-chain revision (app/spec.RELIEF_REVS).

Rev 1 is the relief chain exactly as shipped. Rev 2 pins it to float32 and computes
the wide blurs on a decimated pyramid -- materially cheaper, and the same picture, but
NOT the same bytes. No engine version rides the file, so the rev is the only thing
standing between a customer's reprint and a poster that quietly changed. These tests
are that guarantee:

  1. rev 1 renders what it always rendered, and is what an old manifest deserializes to;
  2. the rev is omitted from the manifest at 1, so pre-v1.13 files re-stamp unchanged;
  3. rev 2's picture is the same picture (a bounded per-pixel difference, asserted --
     the claim has a test behind it, not a promise);
  4. rev 2 still satisfies "one spec, painted at many sizes" -- the pyramid decision is
     made on a ground grid, so the proof still predicts the print.
"""
import json
import os

import numpy as np
import pytest
from PIL import Image

from app import relief, render, serialize
from app.spec import CompositionSpec, RELIEF_REVS, SpecError

REGION_DIR = "regions/lassen_ca"


def _cfg():
    return json.load(open(os.path.join(REGION_DIR, "region.json")))


def _spec(**kw):
    cfg = _cfg()
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    # 27 x 36 km at 9x12 in = exactly 10 m/px at 300 dpi, so the same spec clears the
    # zoom cap at BOTH the proof and the final dpi (test_render.py's crop)
    crop = (cx - 13500, cy - 18000, cx + 13500, cy + 18000)
    d = dict(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
             print_w_in=9, print_h_in=12, native_resolution_m=10,
             tracks=[np.array([[crop[0] + 2000, crop[1] + 2000],
                               [crop[2] - 2000, crop[3] - 2000]])],
             hotspots=[], seed=7)
    d.update(kw)
    return CompositionSpec(**d)


def _terrain(ny=220, nx=180):
    v, u = np.mgrid[0:ny, 0:nx].astype("float64")
    u /= nx - 1
    v /= ny - 1
    z = (0.5 + 0.5 * np.sin(2 * np.pi * 1.5 * u) * np.cos(2 * np.pi * 1.5 * v)
         + 0.4 * np.exp(-(((u - 0.5) ** 2 + (v - 0.5) ** 2) / 0.06)))
    return (900.0 + 1400.0 * z).astype("float32")


# --------------------------------------------------------------------------
# 1 + 2. the gate itself
# --------------------------------------------------------------------------

def test_rev_1_is_the_default():
    # A spec built without the field -- which is every spec deserialized from a
    # manifest printed before v1.13 -- must land on the shipped chain.
    assert _spec().relief_rev == 1
    assert serialize.spec_from_json(serialize.spec_to_json(_spec())).relief_rev == 1


def test_rev_is_omitted_from_the_manifest_at_1():
    at1 = serialize.spec_to_json(_spec())
    assert "relief_rev" not in at1        # pre-feature manifests re-stamp byte-identically
    at2 = serialize.spec_to_json(_spec(relief_rev=2))
    assert at2["relief_rev"] == 2
    assert serialize.spec_from_json(at1).relief_rev == 1
    assert serialize.spec_from_json(at2).relief_rev == 2


@pytest.mark.parametrize("bad", [0, 3, 1.5, "2", True, None])
def test_a_crafted_rev_is_refused(bad):
    with pytest.raises(SpecError):
        _spec(relief_rev=bad).validate(96)


def test_both_revs_validate():
    for rev in RELIEF_REVS:
        _spec(relief_rev=rev).validate(96)


def test_rev_1_renders_deterministically():
    """Determinism is the whole reprint promise; it must hold on each chain."""
    a = np.asarray(render.rasterize(_spec(), 96, region_dir=REGION_DIR))
    b = np.asarray(render.rasterize(_spec(), 96, region_dir=REGION_DIR))
    assert np.array_equal(a, b)


def test_rev_2_renders_deterministically():
    a = np.asarray(render.rasterize(_spec(relief_rev=2), 96, region_dir=REGION_DIR))
    b = np.asarray(render.rasterize(_spec(relief_rev=2), 96, region_dir=REGION_DIR))
    assert np.array_equal(a, b)


# --------------------------------------------------------------------------
# 3. rev 2 is the same picture
# --------------------------------------------------------------------------

def test_rev_1_carries_float64_and_rev_2_does_not():
    """The rev-2 saving IS the dtype: np.radians returns a float64 scalar, which under
    NEP 50 is strong, so shading float32 terrain used to widen the whole downstream
    RGB composition to float64 for precision nobody asked for."""
    slope, aspect = relief.slope_aspect(_terrain(), 30.0)
    assert relief.shade_from(slope, aspect, rev=1).dtype == np.float64
    assert relief.shade_from(slope, aspect, rev=2).dtype == np.float32


@pytest.mark.parametrize("knobs", [
    {},                                                    # the archival sheet
    {"depth": 1.0},                                        # multidirectional + texture
    {"shadow": 1.0},                                       # cast shadow + occlusion
    {"depth": 1.0, "shadow": 1.0, "sun_azimuth": 140.0,
     "sun_altitude": 22.0, "golden": 0.8},                 # everything at once
])
def test_rev_2_is_the_same_picture(knobs):
    """'Same picture, different bytes' is the claim the rev gate rests on -- so bound
    it. A mean error well under one 8-bit step and a small tail means no one looking at
    the sheet can tell; anything looser would mean rev 2 is a LOOK change, which would
    need Dom's sign-off rather than a performance rev."""
    elev = _terrain()
    a = relief.shaded_relief(elev, 30.0, 900.0, 2300.0, rev=1, **knobs).astype(int)
    b = relief.shaded_relief(elev, 30.0, 900.0, 2300.0, rev=2, **knobs).astype(int)
    err = np.abs(a - b)
    assert err.mean() < 0.5, f"mean error {err.mean():.3f}/255 is a visible change"
    assert (err > 4).mean() < 0.02, "too many pixels moved by more than 4/255"


def test_rev_2_actually_takes_the_pyramid_for_a_wide_blur():
    """Guard the threshold: if a refactor silently routed every blur through the exact
    filter, rev 2 would keep its dtype win and quietly lose the larger one."""
    a = _terrain()
    wide = 40.0                                   # > BLUR_PYRAMID_SIGMA_PX
    assert np.array_equal(relief._blur(a, wide, rev=1),
                          relief.gaussian_filter(a, wide))
    assert not np.array_equal(relief._blur(a, wide, rev=2),
                              relief.gaussian_filter(a, wide))
    narrow = 4.0                                  # <= the threshold: exact on both revs
    assert np.array_equal(relief._blur(a, narrow, rev=2),
                          relief.gaussian_filter(a, narrow))


def test_the_pyramid_still_approximates_the_exact_blur():
    a = _terrain()
    exact = relief.gaussian_filter(a, 40.0)
    approx = relief._blur(a, 40.0, rev=2)
    span = float(a.max() - a.min())
    assert np.abs(exact - approx).mean() < 0.01 * span


# --------------------------------------------------------------------------
# 4. rev 2 keeps invariant 1
# --------------------------------------------------------------------------

def test_rev_2_proof_is_a_faithful_scale_of_the_final():
    """The pyramid threshold is in pixels, but every sigma feeding it is a GROUND
    distance over the grid resolution -- so the decimated grid lands on a fixed ground
    resolution and the proof and the final blur the same terrain. If that reasoning
    were wrong, the final would take the pyramid while the proof did not and the
    preview would stop predicting the print. This is that test."""
    spec = _spec(relief_rev=2, shadow_strength=0.8, tracks=[], hotspots=[])
    no_water = {"lakes": [], "rivers": []}
    proof = render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=no_water)
    final = render.rasterize(spec, dpi=300, region_dir=REGION_DIR, hydro=no_water)
    down = final.resize(proof.size, Image.LANCZOS)
    mad = np.abs(np.asarray(proof, np.float32)
                 - np.asarray(down, np.float32)).mean()
    # the same 3.0 bound test_render.py holds rev 1 to -- rev 2 may not be looser
    assert mad < 3.0, f"rev 2 proof is not a faithful scale of the final: {mad:.2f}/255"


def test_the_two_revs_agree_on_dpi_stability():
    """Rev 2 must not merely be stable -- it must be no LESS stable than rev 1, or the
    pyramid is leaking the render resolution into the picture."""
    def mad(rev):
        spec = _spec(relief_rev=rev, shadow_strength=0.8, tracks=[], hotspots=[])
        no_water = {"lakes": [], "rivers": []}
        p = render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=no_water)
        f = render.rasterize(spec, dpi=300, region_dir=REGION_DIR, hydro=no_water)
        return np.abs(np.asarray(p, np.float32)
                      - np.asarray(f.resize(p.size, Image.LANCZOS), np.float32)).mean()
    assert mad(2) < mad(1) + 0.25


# --------------------------------------------------------------------------
# 5. the endpoint stamps the rev, and a continued edition keeps its own
# --------------------------------------------------------------------------

def test_new_proofs_stamp_rev_2_and_the_field_is_enum_gated():
    """A NEW poster gets the current chain; an explicit rev sticks (that is how a
    continued edition keeps looking like its predecessor); an out-of-enum rev 422s
    rather than silently rendering something. Endpoint-level, because the STAMPED
    spec is what the final renders (invariant 1)."""
    from tests.test_main import _client, _upload, _crop
    from app import session as sess_mod
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0),
            "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 200
    assert sess_mod.get(j["session"])["spec"].relief_rev == 2
    assert c.post("/api/proof", data={**data, "relief_rev": 1}).status_code == 200
    assert sess_mod.get(j["session"])["spec"].relief_rev == 1
    assert c.post("/api/proof", data={**data, "relief_rev": 3}).status_code == 422


def test_a_manifest_without_the_rev_reprints_on_the_old_chain():
    """The forever-contract in one assertion: a spec that never heard of relief_rev --
    i.e. every poster already in a customer's hands -- comes back on rev 1."""
    payload = serialize.spec_to_json(_spec(relief_rev=2))
    del payload["relief_rev"]                    # a pre-v1.13 manifest
    assert serialize.spec_from_json(payload).relief_rev == 1
