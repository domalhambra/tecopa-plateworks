# tests/test_ink_cache.py
"""The route-ink cache: the seam, the sparse packing, the key, and cached-vs-cold
pixel equality.

With terrain served from the base cache, the route ink is what is left of a warm knob --
89% of it at 18x24/200 dpi -- and for 20 of the base cache's 26 masked fields re-inking
an identical route is pure waste (see
docs/superpowers/plans/2026-07-27-route-ink-cache.md).

Like the base cache, this is a correctness risk as much as a speed win: a stale ink
layer is a proof that no longer predicts the print. Two tests carry that weight, and
they are not redundant --
`test_every_unmasked_spec_field_changes_the_ink_key` proves the mask is self-consistent
(it would pass happily with a WRONG entry in it), and
`test_every_masked_field_leaves_the_ink_byte_identical` proves each entry is actually
true, by repainting the layer and comparing pixels.
"""
import dataclasses

import numpy as np
import pytest

from app import basecache, render
from app.spec import CompositionSpec
from tests.test_base_cache import REGION_DIR, _cfg, _live_spec, _perturb

DPI = 96


def _spec(n_journeys=3, share_day=False, **kw):
    """`_live_spec` with several dated journeys that cross.

    Three journeys matter: with one, `track_weave` and `track_days` are no-ops and any
    claim about them passes vacuously. Crossing matters too -- it is what makes the
    worn-width (desire-path) terms non-zero, so those rasterizations are live."""
    s = _live_spec(**kw)
    x0, y0, x1, y1 = s.crop
    tracks, days = [], []
    for i in range(n_journeys):
        y = y0 + (y1 - y0) * (i + 1) / (n_journeys + 1)
        tracks.append(np.array([[x0 + 1500, y], [x1 - 1500, y + (y1 - y0) * 0.10]]))
        days.append("2026-05-01" if share_day else f"2026-0{i + 1}-01")
    cx = (x0 + x1) / 2
    tracks.append(np.array([[cx - 1000, y0 + 1500], [cx + 1000, y1 - 1500]]))
    days.append(days[0])
    return dataclasses.replace(s, tracks=tracks, track_days=days)


def _layers(spec, ctx=None):
    return list(render._ink_layers(spec, *spec.pixel_size(DPI), DPI,
                                   render._journey_groups(spec), ctx=ctx,
                                   track_colors=render._track_color_arrays(
                                       spec, REGION_DIR, _cfg())))


def _same_layers(a, b):
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        for name in ("cas", "op", "gf", "ink"):
            u, v = getattr(x, name), getattr(y, name)
            if (u is None) != (v is None):
                return False
            if u is not None and not np.array_equal(u, v):
                return False
    return True


# ---- the sparse packing ------------------------------------------------------------

@pytest.mark.parametrize("kw", [{}, {"track_halo": 0.0}, {"track_color_by": "elevation"}],
                         ids=["plain", "no_halo", "colour_field"])
def test_packing_a_layer_and_expanding_it_composites_identically(kw):
    """The packing claim, stated as what actually matters.

    A layer is stored on its SUPPORT -- the pixels where the casing or ink coverage is
    non-zero, ~1% of a poster after the feather blur. `cas` and `op` round-trip exactly
    (that is how the support is defined). `gf` and the colour field do NOT: off the
    support they come back as 0 instead of their original values. That is sound rather
    than lucky, because both are only ever multiplied by an `op` that is exactly 0
    there -- so the assertion to make is on the COMPOSITE, not on the arrays."""
    spec = _spec(**kw)
    layer = _layers(spec)[0]
    packed = render._ink_pack(layer)
    back = render._ink_unpack(packed)

    assert np.array_equal(back.op, layer.op), "the ink opacity must round-trip exactly"
    if layer.cas is not None:
        assert np.array_equal(back.cas, layer.cas), "the casing must round-trip exactly"

    rng = np.random.default_rng(3)
    img = rng.random((*layer.shape, 3), dtype=np.float32)
    assert np.array_equal(render._composite_ink_layer(img.copy(), spec, back),
                          render._composite_ink_layer(img.copy(), spec, layer))


def test_the_support_really_is_sparse():
    """The measurement the storage format rests on: a route ribbon is a hairline. If a
    change ever made the rasters dense, packing would cost MORE than storing them
    outright and this test is where that shows up."""
    layer = _layers(_spec())[0]
    packed = render._ink_pack(layer)
    dense = layer.op.nbytes + layer.gf.nbytes + layer.cas.nbytes
    assert render._ink_pack_bytes(packed) < dense / 4, (
        "the packed layer is no longer much smaller than the dense one -- re-derive "
        "whether the support is still worth indexing")


def test_a_packed_layer_is_read_only():
    """The base cache's `_freeze` tripwire, same reasoning: nothing writes to a packed
    layer today (`_ink_unpack` scatters into fresh arrays), so freezing costs nothing
    and turns a future in-place write from a silently poisoned cache into an
    exception."""
    packed = render._ink_pack(_layers(_spec())[0])
    for arr in packed[1:]:
        if arr is not None:
            assert not arr.flags.writeable


# ---- the key and its mask contract -------------------------------------------------

def _key(spec, dpi=DPI):
    return render.ink_cache_key(spec, dpi, REGION_DIR, _cfg())


def test_every_unmasked_spec_field_changes_the_ink_key():
    """The guard that keeps this cache honest as the spec grows: a field added next year
    is in this test the day it lands. The failure direction is the point -- an
    unclassified field costs a MISS (slow but correct), where an allowlist would serve a
    stale route under a fresh sheet."""
    base = _spec()
    key = _key(base)
    masked = set(render.INK_KEY_MASK_ALWAYS)
    for f in dataclasses.fields(CompositionSpec):
        alt = _perturb(base, f.name)
        if f.name in masked:
            assert _key(alt) == key, f"{f.name} is masked but still changed the ink key"
        else:
            assert _key(alt) != key, (
                f"{f.name} is not masked, so it may reach the ink layer -- it MUST be "
                f"in the key, or added to the mask with a reason")


def test_the_terrain_knobs_reach_the_ink_key_through_the_base_key():
    """The ink layer is not terrain-free: under High relief every coverage raster is
    warped through the oblique context, which is a pure function of the terrain. Folding
    the base key in covers that -- and the crop, the dpi and the plate -- in one move,
    and it is the safe direction anyway (a terrain knob is a base miss, so the render is
    slow regardless of what the ink cache does)."""
    s = _spec()
    for field in ("shadow_strength", "relief_rev", "oblique", "contours"):
        assert _key(_perturb(s, field)) != _key(s), f"{field} must reach the ink key"
    assert _key(s, dpi=96) != _key(s, dpi=200)


def test_the_halo_is_keyed_on_whether_it_is_zero_not_on_its_value():
    """`track_halo` scales a raster the layer stores unscaled, so its VALUE is a cache
    hit -- but zero skips building that raster at all, so the boundary is keyed."""
    on, off = _spec(track_halo=0.7), _spec(track_halo=0.0)
    assert _key(_spec(track_halo=0.2)) == _key(on), "the halo's value must not key"
    assert _key(off) != _key(on), "halo 0 skips the casing raster -- it must key"


@pytest.mark.parametrize("name", sorted(_MASK_INK_CASES := {
    "flat": {"oblique": 0.0},
    "oblique": {"oblique": 0.5},
    "weave": {"oblique": 0.0, "track_weave": True},
    "colour": {"oblique": 0.0, "track_color_by": "elevation"},
}))
def test_every_masked_field_leaves_the_ink_byte_identical(name):
    """The mask's real safety claim, tested against the painter rather than itself.

    `test_every_unmasked_spec_field_changes_the_ink_key` would pass with a WRONG entry
    in the mask; this one would not. Perturb each masked field, rebuild the layers, and
    every raster must be unmoved. A wrong entry here is a stale route under a fresh
    sheet -- a proof that stopped predicting the print."""
    spec = _spec(**_MASK_INK_CASES[name])
    ctx = None
    if spec.oblique:
        _, ctx, _ = render._paint_terrain(spec, DPI, REGION_DIR, _cfg())
    want = _layers(spec, ctx)
    for field in render.INK_KEY_MASK_ALWAYS:
        assert _same_layers(_layers(_perturb(spec, field), ctx), want), (
            f"{field} is masked but MOVES THE ROUTE INK -- the cache would serve a "
            f"stale layer for it. Remove it from INK_KEY_MASK_ALWAYS.")


def test_the_route_fields_left_in_the_key_really_do_move_the_ink():
    """The other direction: the six fields deliberately NOT masked must each be there
    for a reason. A field that turned out to be inert is a missed cache hit, not a bug --
    but it should be found here and moved, not left to fossilise."""
    spec = _spec()
    want = _layers(spec)
    for field in ("track_rgb", "track_color_by", "track_weave", "tracks",
                  "track_days", "track_width_pt"):
        assert field not in render.INK_KEY_MASK_ALWAYS
        if field == "track_rgb":            # only reaches the layer through the field
            spec_c = _spec(track_color_by="elevation")
            assert not _same_layers(_layers(_perturb(spec_c, field)), _layers(spec_c))
            continue
        assert not _same_layers(_layers(_perturb(spec, field), None), want), (
            f"{field} is in the ink key but does not move the ink -- it could be masked")


# ---- the cache, end to end ---------------------------------------------------------

INK_MATRIX = {
    "plain": {},
    "weave": {"track_weave": True},
    "oblique": {"oblique": 0.5},
    "oblique_weave": {"oblique": 0.5, "track_weave": True},
    "colour": {"track_color_by": "elevation"},
    "no_halo": {"track_halo": 0.0},
    "one_journey": {"n_journeys": 1},
    "shared_day": {"share_day": True},
    "labels_smart": {"labels": True, "label_place": "smart"},
    "bleed": {"bleed_in": 0.125},
}


@pytest.mark.parametrize("name", sorted(INK_MATRIX))
def test_a_cache_hit_is_pixel_identical_to_a_cold_render(name):
    """The cache may only ever be invisible. Anything else is a proof that stops
    predicting the print."""
    spec = _spec(**INK_MATRIX[name])
    cold = np.asarray(render.rasterize(spec, DPI, region_dir=REGION_DIR))
    ink = basecache.BaseCache(400_000_000)
    warm = np.asarray(render.rasterize(spec, DPI, region_dir=REGION_DIR, ink_cache=ink))
    hit = np.asarray(render.rasterize(spec, DPI, region_dir=REGION_DIR, ink_cache=ink))
    assert ink.stats()["hits"] == 1
    assert np.array_equal(cold, warm)
    assert np.array_equal(cold, hit)


@pytest.mark.parametrize("field,value", [
    ("marker_ring", 0.2), ("marker_diameter_in", 0.4), ("photo_frame_style", "polaroid"),
    ("keyline", False), ("title_text", "OTHER"), ("furniture_scale", 1.3),
    ("compass", False), ("labels", False), ("edition", 4),
    ("track_halo", 0.2), ("track_max_darken", 0.4), ("profile_height_in", 1.4),
])
def test_a_furniture_or_symbol_knob_reuses_the_route(field, value):
    """The win, stated one knob at a time: none of these can change the route, so none
    of them may re-ink it. Both caches are supplied, because that is the studio's
    configuration -- and the ink hit has to survive it."""
    spec = _spec(labels=True, label_place="smart", track_weave=True)
    base, ink = basecache.BaseCache(800_000_000), basecache.BaseCache(400_000_000)
    render.rasterize(spec, DPI, region_dir=REGION_DIR, base_cache=base, ink_cache=ink)
    render.rasterize(dataclasses.replace(spec, **{field: value}), DPI,
                     region_dir=REGION_DIR, base_cache=base, ink_cache=ink)
    assert ink.stats()["hits"] == 1, f"{field} must reuse the inked route"


@pytest.mark.parametrize("field,value", [
    ("track_halo", 0.25), ("track_max_darken", 0.4), ("marker_diameter_in", 0.4),
    ("labels", False), ("furniture_scale", 1.3), ("title_text", "OTHER"),
])
def test_a_hit_under_a_changed_masked_field_still_matches_a_cold_render(field, value):
    """A hit is not the claim -- the sheet it produces has to be the sheet a COLD render
    of the changed spec would have produced. This is where the scalars deliberately held
    out of the layer earn their keep: `track_halo` and `track_max_darken` are read live
    at composite time, so serving a cached layer under a new value has to be exact, not
    merely close. Both caches are supplied, because that is the studio's configuration.
    """
    spec = _spec(labels=True, label_place="smart", track_weave=True)
    base, ink = basecache.BaseCache(800_000_000), basecache.BaseCache(400_000_000)
    render.rasterize(spec, DPI, region_dir=REGION_DIR, base_cache=base, ink_cache=ink)
    alt = dataclasses.replace(spec, **{field: value})
    warm = np.asarray(render.rasterize(alt, DPI, region_dir=REGION_DIR,
                                       base_cache=base, ink_cache=ink))
    assert ink.stats()["hits"] == 1, f"{field} must reuse the inked route"
    cold = np.asarray(render.rasterize(alt, DPI, region_dir=REGION_DIR))
    assert np.array_equal(cold, warm)


@pytest.mark.parametrize("field,value", [
    ("track_width_pt", 4.0), ("track_rgb", (10, 20, 30)), ("track_weave", False),
    ("track_color_by", "grade"), ("shadow_strength", 0.1),
])
def test_a_route_or_terrain_knob_does_not_reuse_the_route(field, value):
    spec = _spec(track_weave=True)
    ink = basecache.BaseCache(400_000_000)
    render.rasterize(spec, DPI, region_dir=REGION_DIR, ink_cache=ink)
    render.rasterize(dataclasses.replace(spec, **{field: value}), DPI,
                     region_dir=REGION_DIR, ink_cache=ink)
    assert ink.stats()["hits"] == 0, f"{field} must NOT reuse the inked route"


def test_a_disabled_cache_is_the_pre_cache_path():
    spec = _spec()
    off = basecache.BaseCache(0)
    a = np.asarray(render.rasterize(spec, DPI, region_dir=REGION_DIR, ink_cache=off))
    b = np.asarray(render.rasterize(spec, DPI, region_dir=REGION_DIR))
    assert np.array_equal(a, b)
    assert off.stats()["entries"] == 0


def test_a_time_lapse_prefix_is_never_cached():
    """A film frame inks a PREFIX of the journeys, and that subset is not derivable from
    the spec -- so it cannot be in the key. Refusing to cache it keeps that true by
    construction rather than by convention (the `hydro is not None` precedent in
    `_base_layer`). Nothing passes both today; this is the guard if something ever does.
    """
    spec = _spec()
    ink = basecache.BaseCache(400_000_000)
    w, h = spec.pixel_size(DPI)
    flat = np.full((h, w, 3), 200, np.uint8)
    groups = render._journey_groups(spec)
    a = render._ink_tracks(flat, spec, w, h, DPI, groups=groups[:1], ink_cache=ink,
                           ink_key="k")
    b = render._ink_tracks(flat, spec, w, h, DPI, groups=groups[:1])
    assert np.array_equal(a, b)
    assert ink.stats()["entries"] == 0, "a prefix must never be stored"


def test_the_final_path_does_not_use_the_cache():
    """A final renders at 300 dpi -- a different key, so it could never hit -- and the
    forever-contract is easier to keep if the final simply has no cache in it at all."""
    import inspect
    from app import main as main_mod
    assert "ink_cache" not in inspect.getsource(main_mod._render_to_blob)


def test_the_default_budget_holds_both_proof_tiers_of_one_composition():
    """Sized against the PAIR, not the biggest entry -- the base cache's 0-hits-out-of-4
    lesson. A knob drag renders the composition twice (the sync 96 dpi draft and the
    queued 200 dpi refine) and both must stay resident or each evicts the other."""
    from app import main as main_mod
    draft, refine = 2 * 1_000_000, 12 * 1_000_000
    c = basecache.BaseCache(main_mod.INK_CACHE.max_bytes)
    c.put("refine", "R", refine)
    c.put("draft", "D", draft)
    assert c.get("refine") == "R" and c.get("draft") == "D"


def test_the_proof_endpoint_reuses_the_route_across_a_furniture_knob():
    """End to end: two proofs of the same composition differing only in sheet furniture
    must ink the route once."""
    from app import main as main_mod
    from tests.test_main import _client, _crop, _upload
    main_mod.INK_CACHE.clear()
    before = main_mod.INK_CACHE.stats()["hits"]
    c = _client()
    j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0),
            "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 200
    assert c.post("/api/proof", data={**data, "title": "SECOND"}).status_code == 200
    assert main_mod.INK_CACHE.stats()["hits"] > before
