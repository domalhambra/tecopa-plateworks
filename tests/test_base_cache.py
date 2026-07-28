# tests/test_base_cache.py
"""The base-layer cache: the store, the key, and cached-vs-cold pixel equality.

The cache exists because ~90% of every proof is terrain that the knob being dragged
cannot change (see docs/superpowers/plans/2026-07-26-base-layer-cache.md). That makes
it a correctness risk as much as a speed win: a cache that serves a stale base produces
a proof that no longer predicts the print, which is the one bug class this product
cannot have. These tests are the guard, and the field-enumeration test below is the
one that keeps it honest as the spec grows.
"""
import dataclasses
import json
import os

import numpy as np
import pytest

from app import basecache


def test_put_then_get_returns_the_entry():
    c = basecache.BaseCache(1000)
    c.put("k", "payload", 10)
    assert c.get("k") == "payload"
    assert c.stats()["entries"] == 1
    assert c.stats()["bytes"] == 10


def test_missing_key_returns_none_and_counts_a_miss():
    c = basecache.BaseCache(1000)
    assert c.get("nope") is None
    assert c.stats()["misses"] == 1
    assert c.stats()["hits"] == 0


def test_eviction_is_least_recently_used_and_respects_the_budget():
    c = basecache.BaseCache(100)
    c.put("a", "A", 40)
    c.put("b", "B", 40)
    c.get("a")                       # 'a' is now the most recently used
    c.put("c", "C", 40)              # 120 > 100, so the LRU ('b') goes
    assert c.get("b") is None
    assert c.get("a") == "A"
    assert c.get("c") == "C"
    assert c.stats()["bytes"] <= 100


def test_an_entry_larger_than_the_budget_is_never_admitted():
    # admitting it would evict everything else and then be evicted itself
    c = basecache.BaseCache(100)
    c.put("small", "S", 50)
    c.put("huge", "H", 500)
    assert c.get("huge") is None
    assert c.get("small") == "S"


def test_replacing_a_key_does_not_double_count_its_bytes():
    c = basecache.BaseCache(1000)
    c.put("k", "v1", 100)
    c.put("k", "v2", 100)
    assert c.get("k") == "v2"
    assert c.stats()["bytes"] == 100


def test_a_zero_budget_disables_the_cache_entirely():
    c = basecache.BaseCache(0)
    assert not c.enabled
    c.put("k", "v", 1)
    assert c.get("k") is None
    assert c.stats()["entries"] == 0


def test_the_default_budget_holds_both_proof_tiers_of_one_composition():
    """The budget has to be sized against the PAIR, not the biggest single entry.

    A knob drag renders the composition twice -- the sync 96 dpi draft and the queued
    200 dpi refine -- and both must stay resident or each evicts the other and the drag
    hits nothing. Measured on an 18x24 High-relief sheet of lassen_ca, the worst case
    this plate can carry. The original 256 MB default admitted the 254 MB refine on its
    own and looked fine, while actually scoring 0 hits out of 4 on a three-position
    drag; nothing failed, it was just silently slow. Hence a test rather than a comment.
    """
    draft, refine = 59 * 1_000_000, 254 * 1_000_000
    c = basecache.BaseCache(basecache.DEFAULT_MB * 1_000_000)
    c.put("refine", "R", refine)
    c.put("draft", "D", draft)
    assert c.get("refine") == "R" and c.get("draft") == "D", (
        f"DEFAULT_MB={basecache.DEFAULT_MB} cannot hold a "
        f"{(draft + refine) // 1_000_000} MB draft+refine pair, so a knob drag on a "
        f"High-relief 18x24 thrashes and the cache buys nothing")


def test_clear_empties_the_store():
    c = basecache.BaseCache(1000)
    c.put("k", "v", 10)
    c.clear()
    assert c.get("k") is None
    assert c.stats()["bytes"] == 0


def test_luminance_matches_the_inline_expression():
    """_paint_base used to compute this inline. It is now shared with the cache-hit
    path, and the two must be the same expression or a hit would light markers
    differently from a cold render."""
    from app import render
    rgb = np.random.default_rng(0).integers(0, 256, (40, 30, 3), dtype=np.uint8)
    want = (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]) / 255.0
    assert np.array_equal(render._luminance(rgb), want)


# ---- the plate fingerprint ---------------------------------------------------------

def test_plate_fingerprint_changes_when_an_asset_is_rebuilt(tmp_path):
    """Rebuilding a region must invalidate the cache. (mtime_ns, size) rather than a
    content hash: hashing a 188 MB DEM on every proof would cost more than the render
    the cache exists to skip."""
    from app import render
    cfg = {"dem_path": "dem.tif"}
    (tmp_path / "dem.tif").write_bytes(b"one")
    first = render._plate_fingerprint(str(tmp_path), cfg)
    assert first == render._plate_fingerprint(str(tmp_path), cfg)   # stable
    (tmp_path / "dem.tif").write_bytes(b"two-different-length")
    assert render._plate_fingerprint(str(tmp_path), cfg) != first


def test_plate_fingerprint_tolerates_a_missing_asset(tmp_path):
    # labels.json / landcover.tif are optional; absence is part of the identity
    from app import render
    fp = render._plate_fingerprint(str(tmp_path), {"dem_path": "dem.tif"})
    assert isinstance(fp, str) and fp


# ---- the key and its mask contract -------------------------------------------------

from app.spec import CompositionSpec

REGION_DIR = "regions/lassen_ca"


def _cfg():
    with open(os.path.join(REGION_DIR, "region.json")) as f:
        return json.load(f)


def _live_spec(**kw):
    """A spec with EVERYTHING switched on, so no field is inert and every one of them
    is expected to reach the key. A field masked only because the feature that reads it
    happens to be off would be a false pass."""
    cfg = _cfg()
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    crop = (cx - 13500, cy - 18000, cx + 13500, cy + 18000)
    d = dict(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
             print_w_in=9, print_h_in=12, native_resolution_m=10,
             tracks=[np.array([[crop[0] + 2000, crop[1] + 2000],
                               [crop[2] - 2000, crop[3] - 2000]])],
             track_days=["2026-05-01"],
             hotspots=[{"x": cx, "y": cy, "weight": 2}],
             title_text="GOLDEN", credit_text="USGS 3DEP", seed=7,
             contours=True, compass=True, biome=True, labels=True,
             label_place="smart", track_weave=True, track_color_by="elevation",
             profile=True, oblique=0.4,
             light_mode="journey", top_clear_frac=0.1, bottom_clear_frac=0.1)
    d.update(kw)
    return CompositionSpec(**d)


# One perturbation per field type. Explicit rather than clever, because a wrong
# perturbation here would make the guard below pass vacuously.
_PERTURB = {
    "crop": lambda s: dataclasses.replace(s, crop=tuple(v + 10.0 for v in s.crop)),
    "tracks": lambda s: dataclasses.replace(
        s, tracks=[np.asarray(t, float) + 7.0 for t in s.tracks]),
    "track_days": lambda s: dataclasses.replace(s, track_days=["2019-02-03"]),
    "hotspots": lambda s: dataclasses.replace(
        s, hotspots=list(s.hotspots) + [{"x": 1.0, "y": 2.0, "weight": 1}]),
    "track_rgb": lambda s: dataclasses.replace(s, track_rgb=(1, 2, 3)),
}


def _perturb(spec, name):
    if name in _PERTURB:
        return _PERTURB[name](spec)
    v = getattr(spec, name)
    if isinstance(v, bool):
        return dataclasses.replace(spec, **{name: not v})
    if isinstance(v, int):
        return dataclasses.replace(spec, **{name: v + 1})
    if isinstance(v, float):
        return dataclasses.replace(spec, **{name: v + 0.5})
    if isinstance(v, str):
        return dataclasses.replace(spec, **{name: v + "-x"})
    raise AssertionError(f"no perturbation defined for {name} ({type(v).__name__}) -- "
                         f"add one to _PERTURB so the guard below cannot pass vacuously")


def _key(spec, dpi=96):
    from app import render
    return render.base_cache_key(spec, dpi, REGION_DIR, _cfg())


def test_every_unmasked_spec_field_changes_the_key():
    """The guard that keeps this cache honest as the spec grows.

    Enumerating the dataclass means a field added next year is in this test the day it
    lands: either it is deliberately masked, or changing it MUST change the key. The
    failure direction is the point -- an unclassified field costs a cache miss (slow
    but correct), where an allowlist would serve stale terrain and the proof would stop
    predicting the print."""
    from app import render
    base = _live_spec()
    key = _key(base)
    masked = set(render.BASE_KEY_MASK_ALWAYS)
    for f in dataclasses.fields(CompositionSpec):
        alt = _perturb(base, f.name)
        if f.name in masked:
            assert _key(alt) == key, f"{f.name} is masked but still changed the key"
        else:
            assert _key(alt) != key, (
                f"{f.name} is not masked, so it may reach _paint_terrain -- it MUST be "
                f"in the key, or added to the mask with a reason")


def test_the_furniture_and_track_fields_never_key_the_terrain():
    """Phase 2: labels are drawn AFTER the cached unit, so the sheet furniture, the
    track geometry and the place-name switches stop being terrain inputs -- with place
    names ON as much as off. This replaces the conditional BASE_KEY_MASK_UNLABELLED,
    which existed only because _draw_labels used to run inside the cached region."""
    from app import render
    assert not hasattr(render, "BASE_KEY_MASK_UNLABELLED"), (
        "the conditional mask is gone -- fold any new entry into BASE_KEY_MASK_ALWAYS")
    for name in ("title_text", "title_pt", "label_pt", "credit_text", "edition",
                 "compass", "furniture_scale", "profile", "profile_height_in",
                 "tracks", "track_days", "track_width_pt",
                 "labels", "label_place"):
        assert name in render.BASE_KEY_MASK_ALWAYS, f"{name} should be masked outright"
        for spec in (_live_spec(labels=False), _live_spec(labels=True)):
            assert _key(_perturb(spec, name)) == _key(spec), (
                f"{name} still keys the terrain (labels={spec.labels})")


@pytest.mark.parametrize("name", sorted(_MASK_TERRAIN_CASES := {
    "furniture": {"labels": True, "label_place": "smart", "profile": True,
                  "compass": True, "contours": True},
    "oblique": {"labels": True, "label_place": "smart", "oblique": 0.5,
                "profile": True, "compass": True},
}))
def test_every_masked_field_leaves_the_terrain_byte_identical(name):
    """The mask's real safety claim, tested directly against the painter.

    `test_every_unmasked_spec_field_changes_the_key` only proves the mask is
    self-consistent -- it would happily pass with a WRONG entry in the mask. This one
    proves each entry is correct: perturb it, repaint the terrain, and the pixels (and
    the oblique context) must not move. A wrong mask entry is a stale poster, so the
    claim deserves a test that can actually catch one."""
    from app import render
    spec = _live_spec(**_MASK_TERRAIN_CASES[name])
    want_img, want_ctx, _ = render._paint_terrain(spec, 96, REGION_DIR, _cfg())
    want = np.asarray(want_img)
    for field in render.BASE_KEY_MASK_ALWAYS:
        got_img, got_ctx, _ = render._paint_terrain(_perturb(spec, field), 96,
                                                    REGION_DIR, _cfg())
        assert np.array_equal(np.asarray(got_img), want), (
            f"{field} is masked but MOVES THE TERRAIN -- the cache would serve a stale "
            f"base for it. Remove it from BASE_KEY_MASK_ALWAYS.")
        assert (want_ctx is None) == (got_ctx is None)
        if want_ctx is not None:
            assert np.array_equal(got_ctx.elev, want_ctx.elev)


def test_the_terrain_is_cached_with_its_alpha_intact():
    """_paint_terrain hands back RGBA and _apply_labels draws onto it, so the cache
    must store four channels -- storing RGB to save 25% would be WRONG, not merely
    lossy. _draw_hydro fills lakes at 235 alpha (so the lakebed relief ghosts through),
    and _draw_glyph_rotated composites curved labels with img.alpha_composite, which
    reads that destination alpha. Rebuilding it as opaque would move the pixels of any
    curved name crossing a lake.

    Both halves are asserted: that sub-255 alpha really is reachable (otherwise this
    test would pass vacuously the day hydro stops being translucent), and that what
    the cache stores preserves it."""
    from app import basecache, render
    spec = _live_spec(labels=False)
    himg, _, _ = render._paint_terrain(spec, 96, REGION_DIR, _cfg())
    alpha = np.asarray(himg)[..., 3]
    assert himg.mode == "RGBA"
    assert alpha.min() < 255, (
        "no translucent pixels in this terrain -- the alpha-preservation claim below "
        "is untested. Pick a crop with a lake, or re-derive whether RGB is now safe.")
    cache = basecache.BaseCache(400_000_000)
    render.rasterize(spec, 96, region_dir=REGION_DIR, base_cache=cache)
    terrain, _ = next(iter(cache._entries.values()))
    assert terrain.shape[2] == 4, "the cache dropped the alpha channel"
    assert np.array_equal(terrain, np.asarray(himg))


def test_dpi_and_plate_are_part_of_the_key():
    s = _live_spec()
    assert _key(s, dpi=96) != _key(s, dpi=200)


# ---- cached vs cold ----------------------------------------------------------------

CACHE_MATRIX = {
    "plain": {},
    "contours": {"contours": True},
    "labels_anchor": {"labels": True, "label_place": "anchor"},
    "labels_smart": {"labels": True, "label_place": "smart"},
    "oblique": {"oblique": 0.6},
    "oblique_labels": {"oblique": 0.6, "labels": True, "contours": True},
    "biome": {"biome": True},
    "bleed": {"bleed_in": 0.125},
    "journey": {"light_mode": "journey", "sun_azimuth_deg": 140.0,
                "sun_altitude_deg": 22.0, "golden_strength": 0.8},
}


@pytest.mark.parametrize("name", sorted(CACHE_MATRIX))
def test_a_cache_hit_is_pixel_identical_to_a_cold_render(name):
    """The cache may only ever be invisible. Anything else is a proof that stops
    predicting the print."""
    from app import basecache, render
    # the matrix entry wins over the all-off baseline (a case that turns a knob ON
    # must not be silently overridden by the baseline's OFF value)
    spec = _live_spec(**{"labels": False, "oblique": 0.0, "contours": False,
                         "biome": False, "profile": False, "light_mode": "archival",
                         "label_place": "anchor", **CACHE_MATRIX[name]})
    cold = np.asarray(render.rasterize(spec, 96, region_dir=REGION_DIR))
    cache = basecache.BaseCache(400_000_000)
    warm = np.asarray(render.rasterize(spec, 96, region_dir=REGION_DIR,
                                       base_cache=cache))          # miss, fills
    hit = np.asarray(render.rasterize(spec, 96, region_dir=REGION_DIR,
                                      base_cache=cache))           # hit
    assert cache.stats()["hits"] == 1
    assert np.array_equal(cold, warm)
    assert np.array_equal(cold, hit)


def test_a_route_knob_hits_the_cache_and_a_terrain_knob_misses_it():
    from app import basecache, render
    spec = _live_spec(labels=False)
    cache = basecache.BaseCache(400_000_000)
    render.rasterize(spec, 96, region_dir=REGION_DIR, base_cache=cache)
    render.rasterize(dataclasses.replace(spec, track_rgb=(10, 20, 30)), 96,
                     region_dir=REGION_DIR, base_cache=cache)
    assert cache.stats()["hits"] == 1, "a route-ink knob must reuse the terrain"
    render.rasterize(dataclasses.replace(spec, shadow_strength=0.1), 96,
                     region_dir=REGION_DIR, base_cache=cache)
    assert cache.stats()["hits"] == 1, "a terrain knob must NOT reuse it"


# Some knobs are inert on the DEFAULT composition, which would make the "the knob is
# live" half of the assertion below pass vacuously -- so the case gets a composition
# where it bites, rather than the assertion getting weakened.
_PHASE2_SPEC_EXTRAS = {
    # At 13 pt the 29 place names inside this crop never collide, so smart placement
    # resolves every one of them to its anchor and label_place moves nothing. (Verified:
    # 0 px at 13 pt, 1175 px at 26 pt.) Nothing is wrong with smart placement; the knob
    # simply has no work to do until the type is big enough to overlap.
    "label_place": {"label_pt": 26.0},
}


@pytest.mark.parametrize("field,value", [
    ("track_width_pt", 3.5),        # smart placement used the route as an obstacle
    ("title_text", "A DIFFERENT TITLE"),   # the keep-out measured the cartouche
    ("compass", False),
    ("profile", False),
    ("furniture_scale", 1.2),
    ("edition", 2),
    ("labels", False),              # the place-name switch itself
    ("label_place", "anchor"),
])
def test_phase2_serves_the_knobs_phase1_could_not(field, value):
    """The point of moving the cut before labels: with place names ON and smart
    placement, changing the furniture or the route must now REUSE the terrain and still
    produce exactly what a cold render produces.

    Both halves matter. A hit alone would pass vacuously if the knob did nothing, so
    this also asserts the picture actually changed -- the knob is live, and the cache
    served it correctly anyway."""
    from app import basecache, render
    spec = _live_spec(labels=True, label_place="smart", contours=True, profile=True,
                      compass=True,
                      **_PHASE2_SPEC_EXTRAS.get(field, {}))
    alt = dataclasses.replace(spec, **{field: value})
    cache = basecache.BaseCache(400_000_000)
    first = np.asarray(render.rasterize(spec, 96, region_dir=REGION_DIR,
                                        base_cache=cache))
    warm = np.asarray(render.rasterize(alt, 96, region_dir=REGION_DIR,
                                       base_cache=cache))
    assert cache.stats()["hits"] == 1, f"{field} should reuse the cached terrain"
    cold = np.asarray(render.rasterize(alt, 96, region_dir=REGION_DIR))
    assert np.array_equal(warm, cold), f"{field} served a stale sheet"
    assert not np.array_equal(first, warm), (
        f"{field} changed nothing, so the hit above proves nothing")


def test_the_cached_arrays_are_read_only():
    """A tripwire, not a guarantee: nothing writes to the base today (_ink_tracks
    copies to float, the vector painters build their own images), so freezing costs
    nothing -- and turns a future in-place write from a silently poisoned cache into an
    immediate exception."""
    from app import basecache, render
    spec = _live_spec(labels=False, oblique=0.5)
    cache = basecache.BaseCache(400_000_000)
    render.rasterize(spec, 96, region_dir=REGION_DIR, base_cache=cache)
    rgb, ctx = next(iter(cache._entries.values()))
    assert not rgb.flags.writeable
    assert ctx is not None and not ctx.elev.flags.writeable
    with pytest.raises(ValueError):
        rgb[0, 0, 0] = 1


def test_a_disabled_cache_is_the_pre_cache_path():
    from app import basecache, render
    spec = _live_spec(labels=False)
    off = basecache.BaseCache(0)
    a = np.asarray(render.rasterize(spec, 96, region_dir=REGION_DIR, base_cache=off))
    b = np.asarray(render.rasterize(spec, 96, region_dir=REGION_DIR))
    assert np.array_equal(a, b)
    assert off.stats()["entries"] == 0


def test_a_failing_render_is_not_cached():
    """The off-DEM guard lives inside _paint_terrain. A hit implies it passed for exactly
    this key (it reads only crop + plate + oblique band), and a failure must re-raise
    every time rather than being remembered."""
    from app import basecache, render
    from app.spec import OffDemError
    cfg = _cfg()
    bx = cfg["bounds"]
    off_plate = (bx[2] + 60000, bx[3] + 60000, bx[2] + 87000, bx[3] + 96000)
    spec = _live_spec(labels=False, crop=off_plate)
    cache = basecache.BaseCache(400_000_000)
    for _ in range(2):
        with pytest.raises(OffDemError):
            render.rasterize(spec, 96, region_dir=REGION_DIR, base_cache=cache)
    assert cache.stats()["entries"] == 0


def test_an_overridden_cfg_is_part_of_the_key():
    """rasterize takes cfg as an OVERRIDE -- scripts/render_lightsweep.py renders a
    turntable as {**cfg, "light_azimuth": az}, same spec and dpi and plate every frame.
    If cfg were outside the key, that whole sweep would collapse onto one cached
    terrain."""
    s = _live_spec()
    from app import render
    a = render.base_cache_key(s, 96, REGION_DIR, _cfg())
    b = render.base_cache_key(s, 96, REGION_DIR, {**_cfg(), "light_azimuth": 123.0})
    assert a != b


def test_caller_supplied_plate_data_bypasses_the_cache():
    """hydro/labels passed in are plate data the caller pre-loaded (the wallpaper
    bundle). Only the plate's FILES are in the key, so data handed in cannot be
    verified against it -- refuse to cache rather than risk a base keyed on a plate it
    was not painted from."""
    from app import basecache, render
    spec = _live_spec(labels=False)
    cache = basecache.BaseCache(400_000_000)
    a = np.asarray(render.rasterize(spec, 96, region_dir=REGION_DIR, base_cache=cache,
                                    hydro=render._load_hydro(REGION_DIR)))
    assert cache.stats()["entries"] == 0
    b = np.asarray(render.rasterize(spec, 96, region_dir=REGION_DIR))
    assert np.array_equal(a, b)


# ---- the endpoints -----------------------------------------------------------------

def test_the_proof_endpoint_reuses_the_terrain_across_a_style_knob():
    """End to end: two proofs of the same composition differing only in route ink must
    paint the terrain once."""
    from tests.test_main import _client, _upload, _crop
    from app import main as main_mod
    main_mod.BASE_CACHE.clear()
    before = main_mod.BASE_CACHE.stats()["hits"]
    c = _client(); j = _upload(c)
    data = {"session_id": j["session"], **_crop(j, km_wide=30.0),
            "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data=data).status_code == 200
    assert c.post("/api/proof", data={**data, "track_color": "#b24c2b"}).status_code == 200
    assert main_mod.BASE_CACHE.stats()["hits"] > before


def test_the_final_path_does_not_use_the_cache():
    """A final renders at 300 dpi -- a different key, so it could never hit -- and a
    39 MP entry would evict everything the proof loop depends on."""
    import inspect
    from app import main as main_mod
    src = inspect.getsource(main_mod._render_to_blob)
    assert "base_cache" not in src
