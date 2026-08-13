# tests/test_water.py
"""Water cartography beyond the flat fill: the lake depth vignette (Imhof's littoral
shelf), tapered rivers, and the label budget that keeps water names on the sheet.

The contract, in the order it matters: `water_depth` 0.0 is a STRICT no-op so every
poster printed before the knob existed reprints byte-identically; the graded fill is
DPI-stable (it is sized in ground metres, like every other length in the engine); and
it is bounded in memory -- the distance field runs on a decimated grid, the same
argument `relief._blur` makes for wide kernels."""
import json
import os

import numpy as np
import pytest

from app import render
from app.spec import CompositionSpec, STYLE_BOUNDS, SpecError

REGION_DIR = "regions/lassen_ca"
EAGLE = (690098.0, 4500256.0)      # Eagle Lake: 81 km2, the plate's shapeliest water


def _cfg(region_dir=REGION_DIR):
    with open(os.path.join(region_dir, "region.json")) as f:
        return json.load(f)


def _spec(**kw):
    """A 12x12 in sheet on an 18.5 km square around Eagle Lake -- 10.3 m/px at 150 dpi,
    just clear of the plate's 10 m floor so the zoom cap does not refuse the fixture."""
    cfg = _cfg()
    cx, cy = EAGLE
    half = 18500.0 / 2
    base = dict(region_id="lassen_ca", crs=cfg["crs"],
                crop=(cx - half, cy - half, cx + half, cy + half),
                print_w_in=12.0, print_h_in=12.0,
                native_resolution_m=cfg["native_resolution_m"],
                tracks=[], hotspots=[])
    base.update(kw)
    return CompositionSpec(**base)


def test_spec_carries_water_depth_with_a_noop_default():
    s = _spec()
    assert s.water_depth == 0.0
    assert STYLE_BOUNDS["water_depth"] == (0.0, 1.0)
    s.validate(dpi=150)


@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan")])
def test_out_of_bounds_water_depth_is_refused(bad):
    with pytest.raises(SpecError):
        _spec(water_depth=bad).validate(dpi=150)


def test_zero_is_byte_identical_to_the_flat_fill():
    """The additive-default rule: the knob at 0 must not move one byte."""
    cfg = _cfg()
    a = np.asarray(render.rasterize(_spec(), 150, REGION_DIR, cfg=cfg))
    b = np.asarray(render.rasterize(_spec(water_depth=0.0), 150, REGION_DIR, cfg=cfg))
    assert np.array_equal(a, b)


def test_zero_never_enters_the_vignette_path_at_all():
    """Stronger than equal pixels: at the default the graded compositor is not reached,
    so the flat-fill path is the pre-feature one rather than a reconstruction of it.
    (Verified once against the pre-change render as byte-identical; this is the form
    of that check a test can keep holding.)"""
    cfg = _cfg()
    calls = []
    real = render._draw_lake_vignette
    render._draw_lake_vignette = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    try:
        render.rasterize(_spec(), 150, REGION_DIR, cfg=cfg)
        assert calls == []
        render.rasterize(_spec(water_depth=0.4), 150, REGION_DIR, cfg=cfg)
        assert calls == [1]
    finally:
        render._draw_lake_vignette = real


def test_vignette_pales_the_shore_and_deepens_the_open_water():
    """The whole point of the technique: a lake stops being one flat chip. Sampled
    against the distance field itself, so the assertion is about shore-vs-centre and
    not about any one pixel."""
    cfg = _cfg()
    spec = _spec(water_depth=1.0)
    out_w, out_h = spec.pixel_size(150)
    hydro = render._load_hydro(REGION_DIR)
    mask, t = render._lake_depth_field(hydro, spec, out_w, out_h, None)
    assert mask.any(), "the fixture must actually contain water"

    flat = np.asarray(render.rasterize(_spec(), 150, REGION_DIR, cfg=cfg)).astype(int)
    grad = np.asarray(render.rasterize(spec, 150, REGION_DIR, cfg=cfg)).astype(int)

    shore = mask & (t < 0.15)
    deep = mask & (t > 0.85)
    assert shore.sum() > 500 and deep.sum() > 500
    # luminance: the shore shelf lifts above the flat fill, the open water sinks below
    lum = lambda a: a[..., :3].mean(axis=2)
    assert lum(grad)[shore].mean() > lum(flat)[shore].mean() + 4
    assert lum(grad)[deep].mean() < lum(flat)[deep].mean() - 4


def test_vignette_is_deterministic():
    cfg = _cfg()
    a = np.asarray(render.rasterize(_spec(water_depth=0.7), 150, REGION_DIR, cfg=cfg))
    b = np.asarray(render.rasterize(_spec(water_depth=0.7), 150, REGION_DIR, cfg=cfg))
    assert np.array_equal(a, b)


def test_depth_field_is_dpi_stable():
    """One spec, painted at many sizes (invariant 1): the SAME ground must carry the
    same depth, so the field is compared at two dpi on the ground, not in pixels."""
    from scipy.ndimage import zoom
    spec = _spec(water_depth=1.0)
    hydro = render._load_hydro(REGION_DIR)
    fine_w, fine_h = spec.pixel_size(150)
    coarse_w, coarse_h = spec.pixel_size(75)
    m_f, t_f = render._lake_depth_field(hydro, spec, fine_w, fine_h, None)
    m_c, t_c = render._lake_depth_field(hydro, spec, coarse_w, coarse_h, None)
    up = zoom(t_c, (t_f.shape[0] / t_c.shape[0], t_f.shape[1] / t_c.shape[1]), order=1)
    up = up[:t_f.shape[0], :t_f.shape[1]]
    both = m_f & (zoom(m_c.astype("float32"),
                       (t_f.shape[0] / t_c.shape[0], t_f.shape[1] / t_c.shape[1]),
                       order=1)[:t_f.shape[0], :t_f.shape[1]] > 0.5)
    assert both.sum() > 1000
    assert np.abs(up[both] - t_f[both]).mean() < 0.06


def test_vignette_composites_only_the_water_pixels():
    """Water is a few percent of a sheet, so the blend must never allocate full-sheet
    planes. The naive form measured 2216 MB / 23.7 s on a 300 dpi 18x24; selecting the
    masked pixels first brought it to 506 MB / 7.5 s. This pins the property that got
    it there -- no intermediate in the blend may be sheet-shaped."""
    import tracemalloc
    from PIL import Image
    spec = _spec(water_depth=1.0)
    out_w, out_h = spec.pixel_size(150)
    hydro = render._load_hydro(REGION_DIR)
    mask, _ = render._lake_depth_field(hydro, spec, out_w, out_h, None)
    water_frac = mask.mean()
    assert water_frac < 0.5, "fixture should be mostly land, or this proves nothing"
    img = Image.new("RGBA", (out_w, out_h), (200, 190, 170, 255))
    tracemalloc.start()
    render._draw_lake_vignette(img, hydro, spec, out_w, out_h, None, 1.0)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    sheet_rgba = out_w * out_h * 4
    # generous: the sheet buffer itself, the depth field, the mask, and headroom --
    # but nowhere near the ~14x sheet the full-plane form cost
    assert peak < sheet_rgba * 5, f"peak {peak/1e6:.0f} MB on a {sheet_rgba/1e6:.0f} MB sheet"


def test_depth_field_stays_bounded_in_memory():
    """A 300 dpi 18x24 sheet is 39 Mpx; a float64 distance transform over it is 311 MB.
    The field is computed on a decimated grid at a CONSTANT ground resolution instead --
    relief._blur's argument for wide kernels, applied to the distance transform."""
    spec = _spec(water_depth=1.0)
    hydro = render._load_hydro(REGION_DIR)
    out_w, out_h = spec.pixel_size(150)
    calls = {}
    real = render.distance_transform_edt

    def spy(arr, *a, **kw):
        calls["shape"] = arr.shape
        return real(arr, *a, **kw)

    render.distance_transform_edt = spy
    try:
        render._lake_depth_field(hydro, spec, out_w, out_h, None)
    finally:
        render.distance_transform_edt = real
    gpp = (spec.crop[2] - spec.crop[0]) / out_w
    assert calls["shape"][0] < out_h and calls["shape"][1] < out_w, \
        "the distance transform ran at full sheet resolution"
    # and the decimated grid is a constant GROUND resolution, which is what makes the
    # field dpi-stable rather than merely cheap
    grid_m = (spec.crop[2] - spec.crop[0]) / calls["shape"][1]
    assert grid_m == pytest.approx(render.VIGNETTE_GRID_M, rel=0.35)


# ---- tapered rivers ---------------------------------------------------------------

def _straight_river(spec, order, frac_y=0.5, n=41):
    """A due-east reach across the middle of the crop, as the baker would emit it:
    first vertex upstream, last downstream (NHD digitises downstream -- checked
    against the DEM on this plate at 226 reaches down vs 15 up)."""
    x0, y0, x1, y1 = spec.crop
    y = y0 + (y1 - y0) * frac_y
    xs = np.linspace(x0 + (x1 - x0) * 0.1, x0 + (x1 - x0) * 0.9, n)
    return {"crs": spec.crs, "lakes": [],
            "rivers": [{"coords": [[float(x), float(y)] for x in xs],
                        "order": order, "name": ""}]}


def _ink_profile(img, out_w, out_h):
    """Ink thickness (px) down each column -- how wide the river is drawn there."""
    a = np.asarray(img.convert("RGB")).astype(int)
    inked = np.abs(a - np.array(render.RIVER_COLOR)).sum(axis=2) < 90
    return inked.sum(axis=0)


def test_river_width_is_monotone_in_order_and_clamped():
    w = [render._river_width_pt(o) for o in range(1, 12)]
    assert w == sorted(w)
    assert w[-1] == render.RIVER_MAX_PT
    assert render._river_width_pt(3) == render.RIVER_BASE_PT


def test_an_order_three_reach_is_still_drawn_at_one_constant_width():
    """Order 3 is the headwater gauge: width(2) == width(3), so there is nothing to
    taper and the reach takes the original single-line path unchanged."""
    from PIL import Image
    spec = _spec()
    out_w, out_h = spec.pixel_size(150)
    img = Image.new("RGBA", (out_w, out_h), (255, 255, 255, 255))
    render._draw_hydro(img, _straight_river(spec, 3), spec, out_w, out_h, 150)
    prof = _ink_profile(img, out_w, out_h)
    lit = prof[prof > 0]
    assert lit.size > 100
    assert lit.max() - lit.min() <= 1        # constant to within rasterisation


def test_an_order_four_reach_widens_downstream():
    """Measured at PRINT dpi on purpose. The taper is 0.5 pt over a whole reach, which
    is ~1 px at a 150 dpi proof and ~2 px at 300 -- it is a print-resolution refinement,
    and asserting it at proof dpi would only be testing integer rounding."""
    from PIL import Image
    spec = _spec()
    out_w, out_h = spec.pixel_size(300)
    img = Image.new("RGBA", (out_w, out_h), (255, 255, 255, 255))
    render._draw_hydro(img, _straight_river(spec, 4), spec, out_w, out_h, 300)
    prof = _ink_profile(img, out_w, out_h)
    cols = np.flatnonzero(prof > 0)
    head = prof[cols[:len(cols) // 5]].mean()      # upstream fifth
    mouth = prof[cols[-len(cols) // 5:]].mean()    # downstream fifth
    assert mouth > head + 1.2, f"no taper: head {head:.1f} px, mouth {mouth:.1f} px"


def test_the_taper_joins_continuously_at_a_confluence():
    """The reason the taper runs width(order-1) -> width(order): two order-3 reaches
    END at width(3), and the order-4 reach they feed STARTS at width(3). Get this
    backwards and every confluence gains a visible step."""
    assert render._river_taper_pt(3) == (render._river_width_pt(3),
                                         render._river_width_pt(3))
    for o in (4, 5, 6, 7):
        up_end = render._river_taper_pt(o - 1)[1]
        down_start = render._river_taper_pt(o)[0]
        assert down_start == up_end, f"step at the order {o-1}->{o} confluence"


def test_taper_is_dpi_stable_in_physical_units():
    """The taper is drawn in POINTS, so doubling the dpi doubles the pixel width and
    leaves the printed river the same size."""
    from PIL import Image
    spec = _spec()
    widths = {}
    for dpi in (150, 300):
        out_w, out_h = spec.pixel_size(dpi)
        img = Image.new("RGBA", (out_w, out_h), (255, 255, 255, 255))
        render._draw_hydro(img, _straight_river(spec, 7), spec, out_w, out_h, dpi)
        widths[dpi] = _ink_profile(img, out_w, out_h).max()   # the downstream end
    # a whole-pixel width quantises (2.7 pt is 5.6 px at 150 and 11.25 at 300, drawn as
    # 6 and 11), so the ratio lands near 2 rather than on it
    assert widths[300] == pytest.approx(widths[150] * 2, rel=0.15)


# ---- the label budget: water names must not be starved by rank ---------------------

def test_water_gets_a_reserved_share_of_the_label_budget():
    """Hydrography ranks last (river 40 of 100), so on any name-dense sheet the density
    cap was spent entirely on summits, lakes and flats before a river was ever
    considered -- the plate carries 30 distinct creek names and drew none of them. A
    small per-kind floor reserves a few slots without reordering the rest."""
    spec = _spec(labels=True, label_place="smart")
    out_w, out_h = spec.pixel_size(150)
    labels = render._load_labels(REGION_DIR)
    hydro = render._load_hydro(REGION_DIR)
    cands = render._label_candidates(labels, hydro, spec, out_w, out_h)
    kinds = {k for _, k, _, _, _ in cands}
    assert "river" in kinds, "fixture must contain river candidates to prove anything"
    cap = max(6, round(spec.print_w_in * spec.print_h_in / 100.0
                       * render.GEO_LABELS_PER_100IN2))
    # before: strict rank order starves them
    by_rank = sorted(cands, key=lambda c: -c[0])
    assert not any(k == "river" for _, k, _, _, _ in by_rank[:cap])
    # after: the floor hoists a couple into contention
    ordered = render._label_order(cands)
    assert any(k == "river" for _, k, _, _, _ in ordered[:cap])


def test_label_order_preserves_every_candidate_exactly_once():
    spec = _spec()
    out_w, out_h = spec.pixel_size(150)
    cands = render._label_candidates(render._load_labels(REGION_DIR),
                                     render._load_hydro(REGION_DIR),
                                     spec, out_w, out_h)
    ordered = render._label_order(cands)
    key = lambda c: (c[0], c[1], c[2])
    assert sorted(map(key, ordered)) == sorted(map(key, cands))
    assert len(ordered) == len(cands)


def test_label_order_keeps_rank_order_inside_and_outside_the_reserve():
    """The floor changes WHO is considered, never the ranking within either group --
    the strongest names still lead, and the reserve is filled strongest-first too."""
    cands = [(100, "range", "R", (0, 0), None),
             (85, "summit", "S1", (0, 0), None),
             (85, "summit", "S2", (0, 0), None),
             (66, "lake", "L1", (0, 0), None),
             (40, "river", "A", (0, 0), None),
             (40, "river", "B", (0, 0), None),
             (40, "river", "C", (0, 0), None)]
    ordered = render._label_order(cands)
    reserve = render.GEO_KIND_FLOOR.get("river", 0)
    rivers = [c[2] for c in ordered if c[1] == "river"]
    assert rivers[:reserve] == ["A", "B"][:reserve]        # reserve filled in order
    tail_ranks = [c[0] for c in ordered[reserve + render.GEO_KIND_FLOOR.get("lake", 0):]]
    assert tail_ranks == sorted(tail_ranks, reverse=True)  # the rest stays ranked


# ---- dry lakes (playa) -------------------------------------------------------------

PLAYA_REGION = "regions/susanville_reno"     # Honey Lake's pan, 25 km2


def _playa_spec(**kw):
    """Framed on the plate's LARGEST pan, with the centre clamped so the crop stays
    inside the DEM -- Honey Lake's pan sits against the plate's edge, and an unclamped
    frame trips the off-DEM guard (11% uncovered) rather than testing anything."""
    cfg = _cfg(PLAYA_REGION)
    playa = render._load_playa(PLAYA_REGION)
    def _area(p):
        c = np.asarray(p["coords"], float)
        x, y = c[:, 0], c[:, 1]
        return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))
    biggest = max(playa["playas"], key=_area)
    c = np.asarray(biggest["coords"], float)
    cx, cy = c[:, 0].mean(), c[:, 1].mean()
    half = 18500.0 / 2
    w, s, e, n = cfg["bounds"]
    cx = min(max(cx, w + half), e - half)
    cy = min(max(cy, s + half), n - half)
    base = dict(region_id="susanville_reno", crs=cfg["crs"],
                crop=(cx - half, cy - half, cx + half, cy + half),
                print_w_in=12.0, print_h_in=12.0,
                native_resolution_m=cfg["native_resolution_m"],
                tracks=[], hotspots=[])
    base.update(kw)
    return CompositionSpec(**base)


def test_dry_lakes_defaults_off_and_changes_nothing():
    cfg = _cfg(PLAYA_REGION)
    assert _playa_spec().dry_lakes is False
    a = np.asarray(render.rasterize(_playa_spec(), 150, PLAYA_REGION, cfg=cfg))
    b = np.asarray(render.rasterize(_playa_spec(dry_lakes=False), 150, PLAYA_REGION, cfg=cfg))
    assert np.array_equal(a, b)


def test_a_playa_is_drawn_as_pale_ground_never_as_water():
    """The whole reason playa is not in WATER_FTYPES: filled blue it drew Honey Lake as
    a 234 km2 slab. On the pan, the sheet must move AWAY from the lake colour."""
    cfg = _cfg(PLAYA_REGION)
    off = np.asarray(render.rasterize(_playa_spec(), 150, PLAYA_REGION, cfg=cfg)).astype(int)
    on = np.asarray(render.rasterize(_playa_spec(dry_lakes=True), 150, PLAYA_REGION,
                                     cfg=cfg)).astype(int)
    assert not np.array_equal(off, on)
    spec = _playa_spec(dry_lakes=True)
    out_w, out_h = spec.pixel_size(150)
    from PIL import Image, ImageDraw
    m = Image.new("1", (out_w, out_h), 0)
    d = ImageDraw.Draw(m)
    for pan in render._load_playa(PLAYA_REGION)["playas"]:
        pts = [render._crs_to_px_oblique(x, y, spec, out_w, out_h, None)
               for x, y, *_ in pan["coords"]]
        if len(pts) >= 3:
            d.polygon(pts, fill=1)
    pan_mask = np.asarray(m, dtype=bool)
    assert pan_mask.sum() > 5000
    # paler than before (salt ground lifts it), and further from the lake blue
    assert on[..., :3][pan_mask].mean() > off[..., :3][pan_mask].mean()
    dist = lambda a: np.abs(a[..., :3][pan_mask] - np.array(render.WATER_FILL)).sum(axis=1).mean()
    assert dist(on) > dist(off)


def test_the_stipple_is_deterministic_and_ground_sized():
    """Seeded from spec.seed like the paper grain, and its cell is a GROUND size, so
    the same pan carries the same speckle on a proof and on a final."""
    cfg = _cfg(PLAYA_REGION)
    a = np.asarray(render.rasterize(_playa_spec(dry_lakes=True), 150, PLAYA_REGION, cfg=cfg))
    b = np.asarray(render.rasterize(_playa_spec(dry_lakes=True), 150, PLAYA_REGION, cfg=cfg))
    assert np.array_equal(a, b)
    c = np.asarray(render.rasterize(_playa_spec(dry_lakes=True, seed=99), 150,
                                    PLAYA_REGION, cfg=cfg))
    assert not np.array_equal(a, c), "the stipple must follow the spec's seed"


def test_the_pan_edge_is_broken_not_continuous():
    """A playa's shore is an intermittent boundary, and the broken edge is what says
    'dry' before any colour does. Walk the ring and count how many of its pixels the
    edge inked: a solid outline marks nearly all of them, no outline marks none."""
    from PIL import Image, ImageDraw
    spec = _playa_spec(dry_lakes=True)
    out_w, out_h = spec.pixel_size(150)
    rings = []
    for pan in render._load_playa(PLAYA_REGION)["playas"]:
        pts = [render._crs_to_px_oblique(x, y, spec, out_w, out_h, None)
               for x, y, *_ in pan["coords"]]
        if len(pts) >= 3:
            rings.append(pts)
    solid = Image.new("1", (out_w, out_h), 0)
    dashed = Image.new("1", (out_w, out_h), 0)
    ds, dd = ImageDraw.Draw(solid), ImageDraw.Draw(dashed)
    for pts in rings:
        ds.line(list(pts) + [pts[0]], fill=1, width=1)
        render._dash_polygon(dd, pts, 1, 1,
                             render._pt_to_px(render.PLAYA_DASH_PT, 150),
                             render._pt_to_px(render.PLAYA_GAP_PT, 150))
    ring_px = np.asarray(solid, dtype=bool)
    inked = np.asarray(dashed, dtype=bool) & ring_px
    duty = inked.sum() / ring_px.sum()
    # the nominal duty cycle, with slack for the raster's own rounding on short segments
    nominal = render.PLAYA_DASH_PT / (render.PLAYA_DASH_PT + render.PLAYA_GAP_PT)
    assert 0.3 < duty < nominal + 0.2, f"edge duty {duty:.2f} is not a broken line"


def test_a_plate_without_playa_draws_nothing_and_does_not_crash():
    """rifle_aspen is mountains: bake_playa wrote no sidecar there, and turning the
    knob on must be a no-op rather than an error."""
    rd = "regions/rifle_aspen"
    assert render._load_playa(rd) is None
    cfg = _cfg(rd)
    w, s, e, n = cfg["bounds"]
    cx, cy = (w + e) / 2, (s + n) / 2
    half = 18500.0 / 2
    kw = dict(region_id="rifle_aspen", crs=cfg["crs"],
              crop=(cx - half, cy - half, cx + half, cy + half),
              print_w_in=12.0, print_h_in=12.0, native_resolution_m=10,
              tracks=[], hotspots=[])
    off = np.asarray(render.rasterize(CompositionSpec(**kw), 150, rd, cfg=cfg))
    on = np.asarray(render.rasterize(CompositionSpec(dry_lakes=True, **kw), 150, rd, cfg=cfg))
    assert np.array_equal(off, on)


def test_baking_playa_cannot_invalidate_an_existing_poster():
    """The property the whole sidecar design exists for. hydro.json is hashed into the
    plate's identity, so appending playa to it would have made EVERY poster ever
    printed report a plate mismatch on reprint. In its own file, excluded from the hash
    unless the sheet draws it, a plate's identity is unchanged for everyone else."""
    from app import provenance
    plain = provenance.region_pack_block(PLAYA_REGION)
    assert plain is not None
    assert "playa.json" not in plain["assets"]
    drawn = provenance.region_pack_block(PLAYA_REGION, dry_lakes=True)
    # ... and a sheet that DOES draw them still pins the file it drew
    if os.path.exists(os.path.join(PLAYA_REGION, "playa.json")):
        assert "playa.json" in drawn["assets"]
        assert drawn["pack_version"] != plain["pack_version"]
