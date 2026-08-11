# tests/test_looks.py
"""The seam's first shipped module (app/looks.py): soft multi-directional light and
atmospheric haze as spec knobs. The contract under test: 0.0 is a strict no-op (every
existing poster reprints byte-identically), the knobs move pixels deterministically,
the effect is DPI-stable, and the light pass composes exactly with the scale-keyed
depth blend rather than double-applying it."""
import numpy as np
import pytest

from app import looks, relief, render
from app.relief import registered_relief_passes, shaded_relief
from app.spec import CompositionSpec, STYLE_BOUNDS, SpecError


def _spec(**kw):
    # The crop is sized ABOVE the zoom cap on purpose: ZoomTooTightError subclasses
    # SpecError, so a too-tight fixture would let the bounds tests below pass on the
    # wrong exception. 18000 m over 18 in at 96 dpi is 10.4 m/px, just clear of the
    # 10 m data floor, so the only thing validate() can object to is the knob.
    base = dict(region_id="lassen_ca", crs="EPSG:32610",
                crop=(0.0, 0.0, 18000.0, 24000.0), print_w_in=18.0, print_h_in=24.0,
                native_resolution_m=10.0, tracks=[], hotspots=[])
    base.update(kw)
    return CompositionSpec(**base)


def test_spec_carries_the_two_knobs_with_noop_defaults():
    s = _spec()
    assert s.soft_light == 0.0 and s.haze_strength == 0.0
    assert STYLE_BOUNDS["soft_light"] == (0.0, 1.0)
    assert STYLE_BOUNDS["haze_strength"] == (0.0, 1.0)
    s.validate(dpi=96)                       # defaults pass validation


@pytest.mark.parametrize("field", ["soft_light", "haze_strength"])
@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan")])
def test_out_of_bounds_knob_is_refused(field, bad):
    s = _spec(**{field: bad})
    with pytest.raises(SpecError):
        s.validate(dpi=96)


@pytest.fixture
def terrain():
    """The seam tests' deterministic hill field (mirrors test_relief_passes)."""
    v, u = np.mgrid[0:70, 0:90].astype("float64")
    u /= 89.0
    v /= 69.0
    z = (0.5 + 0.5 * np.sin(2 * np.pi * 1.5 * u) * np.cos(2 * np.pi * 1.5 * v)
         + 0.4 * np.exp(-(((u - 0.5) ** 2 + (v - 0.5) ** 2) / 0.06)))
    return (1200.0 + 900.0 * z).astype("float32")


def _render(elev, **kw):
    return shaded_relief(elev, res_m=30.0, elev_min=1200.0, elev_max=2100.0, **kw)


def test_looks_registers_the_shipped_passes():
    assert registered_relief_passes("light") == ["soft-light"]
    assert registered_relief_passes("finish") == ["haze"]
    assert set(render.RELIEF_EXTRAS) == {"soft_light", "haze"}


def test_zero_knobs_are_byte_identical_to_an_empty_registry(terrain):
    """The additive-default rule, applied to the shipped passes themselves."""
    with_passes = _render(terrain, shadow=0.6,
                          extras={"soft_light": 0.0, "haze": 0.0})
    for stage in ("light", "finish"):
        for name in registered_relief_passes(stage):
            relief.unregister_relief_pass(stage, name)
    try:
        empty = _render(terrain, shadow=0.6)
    finally:
        looks.register()
    assert np.array_equal(with_passes, empty)


def test_soft_light_moves_pixels_and_is_deterministic(terrain):
    plain = _render(terrain)
    lit = _render(terrain, extras={"soft_light": 0.6})
    assert not np.array_equal(plain, lit)
    assert np.array_equal(lit, _render(terrain, extras={"soft_light": 0.6}))


def test_soft_light_full_knob_matches_the_core_blend(terrain):
    """The knob is an exact correction, not an approximation: at knob k with depth 0
    the composed weight is 1-(1-0)(1-k) = k, so k == MULTIDIR_MAX must reproduce the
    light plane the core's own depth blend builds at depth 1.0. A probe pass captures
    that plane in both configurations (depth also moves texture/atmosphere/salt, which
    is why the sheets differ but the LIGHT must not)."""
    k = relief.MULTIDIR_MAX             # the same weight the depth pass uses at d=1
    captured = {}

    def probe(arr, frame):
        captured[frame.extras.get("probe")] = np.array(arr, dtype="float64")
        return arr

    relief.register_relief_pass("light", "zz-probe", probe)   # runs after soft-light
    try:
        _render(terrain, extras={"soft_light": k, "probe": "knob"})
        _render(terrain, depth=1.0, extras={"probe": "depth"})
    finally:
        relief.unregister_relief_pass("light", "zz-probe")
    np.testing.assert_allclose(captured["knob"], captured["depth"],
                               rtol=0, atol=1e-6)


def test_soft_light_composes_with_depth_instead_of_double_applying(terrain):
    """At depth=1 the core already blended at MULTIDIR_MAX; a knob on top may only
    ADD the remaining headroom -- never darken below either input."""
    base = _render(terrain, depth=1.0)
    more = _render(terrain, depth=1.0, extras={"soft_light": 1.0})
    assert not np.array_equal(base, more)         # headroom exists above 0.55
    # and knob=0.0 with depth on is byte-identical (enabled gate)
    assert np.array_equal(base, _render(terrain, depth=1.0,
                                        extras={"soft_light": 0.0}))


def test_haze_sinks_low_ground_toward_the_haze_colour(terrain):
    plain = _render(terrain)
    hazed = _render(terrain, extras={"haze": 1.0})
    assert not np.array_equal(plain, hazed)
    assert np.array_equal(hazed, _render(terrain, extras={"haze": 1.0}))
    norm = (terrain - 1200.0) / 900.0
    low, high = norm < 0.15, norm > 0.85
    d = hazed.astype(int) - plain.astype(int)
    moved = np.abs(d).sum(axis=2)
    assert moved[low].mean() > 4 * max(moved[high].mean(), 0.25)
    # low ground moves TOWARD the cool haze: blue rises relative to red
    assert d[..., 2][low].mean() > d[..., 0][low].mean()


def test_both_knobs_are_dpi_stable(terrain):
    """One spec, painted at many sizes: the same ground at half the resolution must
    show the same effect (MAD of the upsampled coarse render vs fine, bounded like
    the engine's other proof-vs-final gates)."""
    from scipy.ndimage import zoom

    def _up(a, shape):
        return zoom(a.astype("float32"),
                    (shape[0] / a.shape[0], shape[1] / a.shape[1], 1.0),
                    order=1)[:shape[0], :shape[1]]

    knobs = {"soft_light": 0.6, "haze": 0.5}
    coarse_elev = zoom(terrain, 0.5, order=1)
    fine = shaded_relief(terrain, res_m=30.0, elev_min=1200.0, elev_max=2100.0,
                         extras=knobs)
    coarse = shaded_relief(coarse_elev, res_m=60.0, elev_min=1200.0,
                           elev_max=2100.0, extras=knobs)
    mad = np.abs(_up(coarse, fine.shape) - fine.astype("float32")).mean()
    # the same measurement with the knobs off: the baseline dpi drift the shipped
    # look already carries, which the knobs may not meaningfully add to
    plain_fine = shaded_relief(terrain, res_m=30.0, elev_min=1200.0, elev_max=2100.0)
    plain_coarse = shaded_relief(coarse_elev, res_m=60.0, elev_min=1200.0,
                                 elev_max=2100.0)
    mad0 = np.abs(_up(plain_coarse, plain_fine.shape)
                  - plain_fine.astype("float32")).mean()
    assert mad < mad0 + 2.0        # the knobs add no MORE dpi drift than the base look
