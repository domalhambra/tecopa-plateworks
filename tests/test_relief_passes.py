# tests/test_relief_passes.py
"""The relief extension seam (app/relief.py): the registry a future rendering module
plugs into instead of editing the composition chain.

Two things are under test, and the first matters more than the second:

1. The seam is a STRICT NO-OP while the registry is empty. `shaded_relief` is the
   function every shipped poster's pixels come out of, so the mechanism that lets the
   next module in must not move a single byte on its own (the forever-contract).
2. A registered pass actually reaches the picture, at each stage, with the shared
   intermediates (slope/aspect, cast shadow, sky occlusion) already on the frame -- so
   a new technique never re-derives a gradient or re-marches a shadow.
"""
import numpy as np
import pytest

from app import relief
from app.relief import (ReliefFrame, RELIEF_STAGES, register_relief_pass,
                        registered_relief_passes, shaded_relief,
                        unregister_relief_pass)


@pytest.fixture
def terrain():
    """A small deterministic hill field with real gradients to shade."""
    v, u = np.mgrid[0:70, 0:90].astype("float64")
    u /= 89.0
    v /= 69.0
    z = (0.5 + 0.5 * np.sin(2 * np.pi * 1.5 * u) * np.cos(2 * np.pi * 1.5 * v)
         + 0.4 * np.exp(-(((u - 0.5) ** 2 + (v - 0.5) ** 2) / 0.06)))
    return (1200.0 + 900.0 * z).astype("float32")


@pytest.fixture
def clean_registry():
    """Every test restores the empty shipped registry, pass or fail."""
    before = registered_relief_passes()
    assert all(not v for v in before.values()), "the registry must ship empty"
    yield
    for stage, names in registered_relief_passes().items():
        for name in names:
            unregister_relief_pass(stage, name)


def _render(elev, **kw):
    return shaded_relief(elev, res_m=30.0, elev_min=1200.0, elev_max=2100.0, **kw)


def test_registry_ships_empty():
    # The default state IS the contract: no pass, no pixel change, nothing to review
    # in a diff of a shipped poster.
    assert registered_relief_passes() == {s: [] for s in RELIEF_STAGES}


def test_empty_registry_is_byte_identical(terrain, clean_registry):
    # the archival sheet and a fully-knobbed one, both through the seam
    plain = _render(terrain)
    lit = _render(terrain, depth=1.0, shadow=0.8, sun_azimuth=140.0,
                  sun_altitude=22.0, golden=0.7)
    assert np.array_equal(plain, _render(terrain))
    assert np.array_equal(lit, _render(terrain, depth=1.0, shadow=0.8,
                                       sun_azimuth=140.0, sun_altitude=22.0,
                                       golden=0.7))


def test_a_registered_noop_pass_changes_nothing(terrain, clean_registry):
    # A pass that returns its argument must be invisible -- this is what makes
    # "gated at its pre-feature default" mean the same thing for a registered module
    # as it does for the hand-wired ones.
    before = _render(terrain, shadow=0.6)
    seen = []
    for stage in RELIEF_STAGES:
        register_relief_pass(stage, f"noop-{stage}",
                             lambda arr, frame, s=stage: (seen.append(s), arr)[1])
    after = _render(terrain, shadow=0.6)
    assert seen == list(RELIEF_STAGES), "every stage must run, in composition order"
    assert np.array_equal(before, after)


def test_disabled_pass_never_runs(terrain, clean_registry):
    calls = []

    def boom(arr, frame):
        calls.append(1)
        return arr * 0.0

    register_relief_pass("grade", "off", boom, enabled=lambda f: f.extras.get("on"))
    assert np.array_equal(_render(terrain), _render(terrain))
    assert calls == []
    # and it DOES run once its knob says so
    out = _render(terrain, extras={"on": True})
    assert calls == [1]
    assert out.max() == 0


@pytest.mark.parametrize("stage", RELIEF_STAGES)
def test_each_stage_reaches_the_picture(terrain, clean_registry, stage):
    def darken(arr, frame):
        return arr * 0.5

    base = _render(terrain, shadow=0.5)
    register_relief_pass(stage, "darken", darken, enabled=lambda f: True)
    out = _render(terrain, shadow=0.5)
    assert not np.array_equal(base, out), f"stage {stage} never reached the sheet"
    assert out.mean() < base.mean()


def test_registering_the_same_name_replaces_it(terrain, clean_registry):
    register_relief_pass("grade", "x", lambda a, f: a)
    register_relief_pass("grade", "x", lambda a, f: a)
    assert registered_relief_passes("grade") == ["x"]


def test_unknown_stage_is_refused(clean_registry):
    with pytest.raises(ValueError):
        register_relief_pass("varnish", "x", lambda a, f: a)


def test_frame_carries_the_shared_intermediates(terrain, clean_registry):
    """The point of the frame: the expensive fields the core already computed are
    handed to the pass, so a new technique costs its own maths and nothing else."""
    seen = {}

    def capture(arr, frame):
        seen["frame"] = frame
        return arr

    register_relief_pass("finish", "capture", capture)
    _render(terrain, shadow=0.7, depth=0.5, sun_azimuth=200.0, sun_altitude=30.0)
    f = seen["frame"]
    assert isinstance(f, ReliefFrame)
    assert f.elev.shape == terrain.shape and not np.isnan(f.elev).any()
    assert f.norm.min() >= 0.0 and f.norm.max() <= 1.0
    for name in ("tex", "val", "cast", "ao"):
        got = getattr(f, name)
        assert got is not None and got.shape == terrain.shape, name
        assert got.min() >= 0.0 and got.max() <= 1.0, name
    # the shadow march is the frame's, not a second one
    assert f.shadow == 0.7 and f.sun_azimuth == 200.0


def test_frame_shares_one_slope_aspect_field(terrain, clean_registry):
    seen = {}
    register_relief_pass("light", "cap", lambda a, f: (seen.setdefault("f", f), a)[1])
    _render(terrain)
    f = seen["f"]
    assert f.terrain() is f.terrain(), "slope/aspect must be computed once"
    slope, aspect = f.terrain()
    assert slope.shape == aspect.shape == terrain.shape
    # a pass's own light matches the core's hillshade on the same bearing
    assert np.array_equal(f.light_from(315, 45),
                          relief.hillshade(f.elev, f.res_m, 315, 45, f.z_factor))


def test_frame_px_is_ground_relative(terrain, clean_registry):
    """A pass sizing anything in pixels breaks invariant 1/2; `frame.px` is the one
    conversion, and it must track the render resolution."""
    fine = ReliefFrame(elev=terrain, res_m=5.0, norm=terrain * 0, elev_min=0.0,
                       elev_max=1.0, seed=7, azimuth=315, altitude=45, z_factor=1.0)
    coarse = ReliefFrame(elev=terrain, res_m=20.0, norm=terrain * 0, elev_min=0.0,
                         elev_max=1.0, seed=7, azimuth=315, altitude=45, z_factor=1.0)
    assert fine.px(100.0) == 20.0
    assert coarse.px(100.0) == 5.0        # same ground, a quarter of the pixels


def test_a_pass_may_write_in_place(terrain, clean_registry):
    """The contract says a pass MAY consume its argument -- the whole engine composites
    in place now, and a pass that allocates a fresh sheet would give that back."""
    def in_place(arr, frame):
        arr *= 0.25
        return arr

    register_relief_pass("finish", "inplace", in_place)
    out = _render(terrain)
    assert out.mean() < 120         # visibly darkened, no exception from the writes


def test_render_extras_registry_ships_empty_and_stays_no_op():
    """render.relief_extra is the spec-side half of the seam: empty by default, so
    _paint_base passes extras=None and the shaded_relief call is the pre-seam one."""
    from app import render
    assert render.RELIEF_EXTRAS == {}
    assert render._relief_extras(object()) is None
