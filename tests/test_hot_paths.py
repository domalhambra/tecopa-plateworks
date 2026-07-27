# tests/test_hot_paths.py
"""Differential tests for the vectorized hot paths.

Four scalar loops were replaced with array maths for speed: the visit rasterizer
behind the hotspot pass, the track-colour ramp, the DEM point sampler, and the
polyline projection. Every one of them feeds pixels, so "faster" is only acceptable
if it is also *identical* -- a poster printed before the rewrite must reprint
byte-for-byte after it (the forever-contract).

Each test therefore keeps the ORIGINAL scalar implementation inline and asserts the
new one agrees on adversarial input: degenerate tracks, duplicate vertices, points
outside the plate, values exactly on a ramp stop, NaN and infinity. They are cheap
and they are the reason the rewrites can be trusted; do not replace them with a
"looks about right" tolerance.
"""
import dataclasses
import json
import os

import numpy as np
import pytest
import rasterio

from app import density, render
from app.ingest import Track
from app.spec import CompositionSpec

REGION_DIR = "regions/lassen_ca"


def _cfg():
    return json.load(open(os.path.join(REGION_DIR, "region.json")))


# --------------------------------------------------------------------------
# 1. density._rasterize_visits -- the upload path's visitation grid
# --------------------------------------------------------------------------

def _scalar_rasterize_visits(tracks, bounds, cell_m):
    """The pre-vectorization implementation, verbatim."""
    min_x, min_y, max_x, max_y = bounds
    nx = max(1, int((max_x - min_x) / cell_m))
    ny = max(1, int((max_y - min_y) / cell_m))
    sets = [[set() for _ in range(nx)] for _ in range(ny)]
    for i, t in enumerate(tracks):
        key = t.day or f"__anon-{i}"
        c = t.coords
        seg_len = np.hypot(np.diff(c[:, 0]), np.diff(c[:, 1]))
        for j in range(len(c) - 1):
            n_pts = max(2, int(seg_len[j] / (cell_m * 0.5)) + 1)
            xs = np.linspace(c[j, 0], c[j + 1, 0], n_pts)
            ys = np.linspace(c[j, 1], c[j + 1, 1], n_pts)
            for x, y in zip(xs, ys):
                gx = int((x - min_x) / cell_m)
                gy = int((max_y - y) / cell_m)
                if 0 <= gx < nx and 0 <= gy < ny:
                    sets[gy][gx].add(key)
    return np.array([[len(sets[j][i]) for i in range(nx)] for j in range(ny)],
                    dtype=float), nx, ny


def _fuzz_tracks(rng, bounds):
    tracks = []
    for k in range(int(rng.integers(1, 7))):
        n = int(rng.integers(0, 2) if rng.random() < 0.15 else rng.integers(0, 40))
        coords = (np.column_stack([rng.uniform(bounds[0] - 8000, bounds[2] + 8000, n),
                                   rng.uniform(bounds[1] - 8000, bounds[3] + 8000, n)])
                  if n else np.zeros((0, 2)))
        if n >= 2 and rng.random() < 0.3:
            coords[1] = coords[0]                    # a duplicated vertex
        day = None if rng.random() < 0.3 else f"2026-01-{int(rng.integers(1, 4)):02d}"
        tracks.append(Track(track_id=f"t{k}", coords=coords, day=day))
    return tracks


@pytest.mark.parametrize("cell_m", [250.0, 1000.0, 3333.0])
def test_visit_grid_matches_the_scalar_rasterizer(cell_m):
    bounds = (500000.0, 4400000.0, 560000.0, 4470000.0)
    rng = np.random.default_rng(0)
    for _ in range(25):
        tracks = _fuzz_tracks(rng, bounds)
        want, nxw, nyw = _scalar_rasterize_visits(tracks, bounds, cell_m)
        got, nxg, nyg = density._rasterize_visits(tracks, bounds, cell_m)
        assert (nxg, nyg) == (nxw, nyw)
        assert np.array_equal(got, want)


def test_shared_days_still_count_as_one_visit():
    """The grid counts DISTINCT journeys, not track segments -- the property the
    grid-of-sets encoded and the (cell, key) de-duplication has to preserve."""
    bounds = (0.0, 0.0, 10000.0, 10000.0)
    line = np.array([[1000.0, 5000.0], [9000.0, 5000.0]])
    same_day = [Track("a", line, "2026-01-01"), Track("b", line.copy(), "2026-01-01")]
    two_days = [Track("a", line, "2026-01-01"), Track("b", line.copy(), "2026-01-02")]
    g1, _, _ = density._rasterize_visits(same_day, bounds, 500.0)
    g2, _, _ = density._rasterize_visits(two_days, bounds, 500.0)
    assert g1.max() == 1
    assert g2.max() == 2


def test_dateless_tracks_each_count_separately():
    bounds = (0.0, 0.0, 10000.0, 10000.0)
    line = np.array([[1000.0, 5000.0], [9000.0, 5000.0]])
    tracks = [Track("a", line, None), Track("b", line.copy(), None)]
    grid, _, _ = density._rasterize_visits(tracks, bounds, 500.0)
    assert grid.max() == 2


# --------------------------------------------------------------------------
# 2. render._ramp_array -- the per-vertex track colour ramp
# --------------------------------------------------------------------------

@pytest.mark.parametrize("stops", [render._ELEV_RAMP, render._GRADE_RAMP])
def test_ramp_array_matches_the_scalar_ramp(stops):
    stop_ts = np.array([s[0] for s in stops])
    vals = np.concatenate([
        np.random.default_rng(7).uniform(-0.5, 1.5, 3000),
        np.array([0.0, 1.0, -0.0, np.nan, np.inf, -np.inf]),
        stop_ts, stop_ts - 1e-16, stop_ts + 1e-16,     # exactly on / astride a stop
        np.linspace(0.0, 1.0, 2001),                   # dense: hits half-way roundings
    ])
    want = np.array([render._ramp(stops, v) for v in vals], np.uint8)
    assert np.array_equal(render._ramp_array(stops, vals), want)


def test_ramp_array_handles_an_empty_track():
    assert render._ramp_array(render._ELEV_RAMP, np.zeros(0)).shape == (0, 3)


# --------------------------------------------------------------------------
# 3. render._sample_dem_open -- bulk DEM point sampling
# --------------------------------------------------------------------------

def _dem_path():
    return os.path.join(REGION_DIR, _cfg()["dem_path"])


@pytest.mark.parametrize("where", ["inside", "straddling", "corners", "single"])
def test_bulk_dem_sampling_matches_rasterio_sample(where):
    cfg = _cfg()
    bx = cfg["bounds"]
    rng = np.random.default_rng(3)
    if where == "inside":
        xy = np.column_stack([rng.uniform(bx[0], bx[2], 2000),
                              rng.uniform(bx[1], bx[3], 2000)])
    elif where == "straddling":                  # half the points off the plate
        xy = np.column_stack([rng.uniform(bx[0] - 5e4, bx[2] + 5e4, 1500),
                              rng.uniform(bx[1] - 5e4, bx[3] + 5e4, 1500)])
    elif where == "corners":
        xy = np.array([[bx[0], bx[1]], [bx[2], bx[3]], [bx[0], bx[3]],
                       [bx[2], bx[1]], [bx[0] - 1.0, bx[1] - 1.0]])
    else:
        xy = np.array([[(bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2]])
    with rasterio.open(_dem_path()) as ds:
        want = np.array([v[0] for v in ds.sample(
            [(float(x), float(y)) for x, y in xy])], dtype=float)
        got = np.asarray(render._sample_dem_open(ds, xy), dtype=float)
    assert np.array_equal(got, want, equal_nan=True)


def test_bulk_sampling_falls_back_when_the_window_would_be_huge(monkeypatch):
    """A trip scattered across a corridor plate must not pull the whole raster into
    memory to sample a few points -- past the budget it reverts to point reads, and
    the values are the same either way."""
    cfg = _cfg()
    bx = cfg["bounds"]
    xy = np.array([[bx[0] + 10.0, bx[1] + 10.0], [bx[2] - 10.0, bx[3] - 10.0]])
    with rasterio.open(_dem_path()) as ds:
        windowed = np.asarray(render._sample_dem_open(ds, xy), dtype=float)
        monkeypatch.setattr(render, "DEM_SAMPLE_WINDOW_MAX_PX", 1)
        per_point = np.asarray(render._sample_dem_open(ds, xy), dtype=float)
    assert np.array_equal(windowed, per_point, equal_nan=True)


# --------------------------------------------------------------------------
# 4. render._polyline_px -- projecting a route to sheet pixels
# --------------------------------------------------------------------------

def test_polyline_projection_matches_the_per_vertex_form():
    rng = np.random.default_rng(11)
    for _ in range(150):
        x0, y0 = rng.uniform(2e5, 8e5), rng.uniform(4e6, 5e6)
        crop = (x0, y0, x0 + rng.uniform(1e3, 1e5), y0 + rng.uniform(1e3, 1e5))
        out_w, out_h = int(rng.integers(10, 6000)), int(rng.integers(10, 6000))
        n = int(rng.integers(0, 50))
        track = (np.column_stack([rng.uniform(crop[0] - 1e4, crop[2] + 1e4, n),
                                  rng.uniform(crop[1] - 1e4, crop[3] + 1e4, n)])
                 if n else np.zeros((0, 2)))
        dx, dy = float(rng.integers(0, 400)), float(rng.integers(0, 400))
        want = [(px + dx, py + dy) for px, py in
                (render._crs_to_px(x, y, crop, out_w, out_h) for x, y in track)]
        assert render._polyline_px(track, crop, out_w, out_h, dx, dy) == want


def test_polyline_cache_returns_the_same_points_every_time():
    crop = (0.0, 0.0, 1000.0, 2000.0)
    tracks = [np.array([[10.0, 20.0], [900.0, 1900.0]]), np.zeros((0, 2))]
    cache = render._PolylineCache(tracks, crop, 100, 200, 3.0, 4.0)
    first = cache.points(0)
    assert cache.points(0) == first
    assert first == render._polyline_px(tracks[0], crop, 100, 200, 3.0, 4.0)
    assert cache.points(1) == []


# --------------------------------------------------------------------------
# 5. the font cache -- shared instances must not leak across threads
# --------------------------------------------------------------------------

def test_font_cache_returns_one_instance_per_thread_and_size():
    a = render._font(24)
    assert render._font(24) is a
    assert render._font(25) is not a
    out = {}

    def other():
        out["font"] = render._font(24)

    import threading
    t = threading.Thread(target=other)
    t.start()
    t.join()
    # Pillow's FreeTypeFont wraps one FT_Face and is not thread-safe; two render
    # threads must never share one (invariant 3 -- determinism).
    assert out["font"] is not a


def test_font_cache_follows_the_env_override(monkeypatch):
    plain = render._font(30)
    monkeypatch.setenv("TECOPA_FONT", "DejaVuSans.ttf")
    assert render._font(30) is not plain


# --------------------------------------------------------------------------
# 6. _composite_ink_layer -- the two alpha blends, restricted to the ink support
# --------------------------------------------------------------------------
# The blends used to run over the whole sheet for a raster that is non-zero on ~1% of
# it. Restricting them to the support is byte-identical by the same float argument the
# sparse packing already rests on: where `op` is 0 the blend is `img*1.0 + col*0.0`,
# which IS `img` in float32, and gaussian_filter's finite support makes `op` exactly 0.0
# off the ribbon. These tests keep the DENSE blend inline, verbatim, and assert the
# restricted one agrees -- the same shape as the four rewrites above.

def _dense_composite(img, spec, layer):
    """`_composite_ink_layer` as it stood before the support restriction, verbatim."""
    if layer.cas is not None:
        casing_op = (spec.track_halo * np.clip(layer.cas, 0, 1))[..., None]
        casing_col = np.array(render.TRACK_CASING, np.float32) / 255.0
        img = img * (1 - casing_op) + casing_col[None, None, :] * casing_op
    op = np.clip(layer.op, 0.0, spec.track_max_darken)
    op = (op * layer.gf)[..., None]
    if layer.ink is not None:
        img = img * (1 - op) + layer.ink * op
    else:
        ink = np.array(spec.track_rgb, np.float32) / 255.0
        img = img * (1 - op) + ink[None, None, :] * op
    return img


_COMP_DPI = 96


def _comp_spec(n_journeys=3, **kw):
    """Three dated journeys that CROSS. One journey makes the weave and the worn-width
    terms inert, so a claim about them would pass vacuously."""
    cfg = _cfg()
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    crop = (cx - 13500, cy - 18000, cx + 13500, cy + 18000)
    d = dict(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
             print_w_in=9, print_h_in=12, native_resolution_m=10,
             tracks=[], track_days=[], hotspots=[], seed=7)
    d.update(kw)
    s = CompositionSpec(**d)
    x0, y0, x1, y1 = s.crop
    tracks, days = [], []
    for i in range(n_journeys):
        y = y0 + (y1 - y0) * (i + 1) / (n_journeys + 1)
        tracks.append(np.array([[x0 + 1500, y], [x1 - 1500, y + (y1 - y0) * 0.10]]))
        days.append(f"2026-0{i + 1}-01")
    cxm = (x0 + x1) / 2
    tracks.append(np.array([[cxm - 1000, y0 + 1500], [cxm + 1000, y1 - 1500]]))
    days.append(days[0])
    return dataclasses.replace(s, tracks=tracks, track_days=days)


def _comp_layers(spec):
    colors = render._track_color_arrays(spec, REGION_DIR, _cfg())
    return list(render._ink_layers(spec, *spec.pixel_size(_COMP_DPI), _COMP_DPI,
                                   render._journey_groups(spec), track_colors=colors))


def _sheet(spec, seed=3):
    """A non-uniform float32 sheet in 0..1, so an off-support write cannot hide in a
    flat field the way it would against a constant background."""
    w, h = spec.pixel_size(_COMP_DPI)
    rng = np.random.default_rng(seed)
    return rng.random((h, w, 3), dtype=np.float32)


_COMP_CASES = {
    "plain": {},
    "no_halo": {"track_halo": 0.0},
    "halo_full": {"track_halo": 0.9},        # the STYLE_BOUNDS ceiling, not past it
    "colour_field": {"track_color_by": "elevation"},
    "weave": {"track_weave": True},
    "weave_colour": {"track_weave": True, "track_color_by": "elevation"},
    "low_darken": {"track_max_darken": 0.35},
    "single_journey": {"n_journeys": 1},
}


@pytest.mark.parametrize("case", list(_COMP_CASES), ids=list(_COMP_CASES))
def test_the_dense_composite_changes_nothing_off_the_ink_support(case):
    """The claim the whole restriction rests on, asserted on the OLD code: off the
    support the dense blend is an exact no-op, not merely a small one. If this ever
    fails, restricting the composite is unsound and needs a revision, not a merge."""
    spec = _comp_spec(**_COMP_CASES[case])
    for layer in _comp_layers(spec):
        img = _sheet(spec)
        out = _dense_composite(img.copy(), spec, layer)
        off = np.ones(layer.op.shape, bool)
        off.reshape(-1)[render._ink_support(layer)] = False
        assert np.array_equal(out[off], img[off]), (
            f"{case}: the dense blend moved {int((out[off] != img[off]).any(-1).sum())} "
            f"pixels that are off the ink support")


@pytest.mark.parametrize("case", list(_COMP_CASES), ids=list(_COMP_CASES))
def test_support_restricted_composite_is_byte_identical_to_the_dense_blend(case):
    """Bit-for-bit, not close: this is the forever-contract on the most exacting
    painter in the engine."""
    spec = _comp_spec(**_COMP_CASES[case])
    for layer in _comp_layers(spec):
        img = _sheet(spec)
        want = _dense_composite(img.copy(), spec, layer)
        got = render._composite_ink_layer(img.copy(), spec, layer)
        assert got.dtype == want.dtype
        assert np.array_equal(got, want), f"{case}: the composite moved"


def test_the_composite_and_the_packing_share_one_support_definition():
    """Two definitions of "the support" that could drift is the bug this forecloses:
    the packing drops `gf` and the colour field off ITS support, and the composite is
    only sound there if it blends over exactly the same pixels."""
    spec = _comp_spec(track_color_by="elevation")
    for layer in _comp_layers(spec):
        packed_idx = render._ink_pack(layer)[1]
        assert np.array_equal(render._ink_support(layer), packed_idx)


def test_inking_tracks_still_does_not_mutate_the_base_sheet():
    """`_ink_tracks` copies to float before compositing, and a time-lapse inks many
    journey prefixes onto ONE base -- so the base must survive being inked."""
    spec = _comp_spec()
    w, h = spec.pixel_size(_COMP_DPI)
    base = (np.random.default_rng(11).random((h, w, 3)) * 255).astype(np.uint8)
    before = base.copy()
    render._ink_tracks(base, spec, w, h, _COMP_DPI)
    assert np.array_equal(base, before)


def test_the_composite_writes_through_a_non_contiguous_sheet():
    """The scatter reaches `img` only if `reshape(-1, 3)` is a VIEW. On a non-contiguous
    sheet reshape silently COPIES, and without the guard every drop of ink would land in
    the copy and be thrown away -- a blank route, not a crash."""
    spec = _comp_spec()
    layer = _comp_layers(spec)[0]
    w, h = spec.pixel_size(_COMP_DPI)
    # a C-contiguous parent sliced down a channel-padded axis: the classic accidental view
    parent = np.random.default_rng(5).random((h, w, 4), dtype=np.float32)
    sheet = parent[:, :, :3]
    assert not sheet.flags.c_contiguous
    want = _dense_composite(np.ascontiguousarray(sheet), spec, layer)
    got = render._composite_ink_layer(sheet, spec, layer)
    assert np.array_equal(got, want)
    # and the ink actually landed -- otherwise "identical to the dense blend" could be
    # satisfied by a layer that inks nothing at all
    assert not np.array_equal(got, sheet)


def test_the_composite_is_a_no_op_for_a_layer_with_no_inked_pixels():
    """A spec whose route inks nothing (no tracks at all) has an empty support. The
    blends are skipped outright, and the sheet must come back untouched rather than
    scaled or zeroed."""
    spec = dataclasses.replace(_comp_spec(), tracks=[], track_days=[])
    w, h = spec.pixel_size(_COMP_DPI)
    layers = _comp_layers(spec)
    assert layers, "expected one summed layer even with no tracks"
    for layer in layers:
        assert render._ink_support(layer).size == 0
        img = _sheet(spec)
        before = img.copy()
        out = render._composite_ink_layer(img, spec, layer)
        assert np.array_equal(out, before)
