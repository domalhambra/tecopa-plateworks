# tests/test_looks.py
"""The seam's first shipped module (app/looks.py): soft multi-directional light and
atmospheric haze as spec knobs. The contract under test: 0.0 is a strict no-op (every
existing poster reprints byte-identically), the knobs move pixels deterministically,
the effect is DPI-stable, and the light pass composes exactly with the scale-keyed
depth blend rather than double-applying it."""
import numpy as np
import pytest

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
