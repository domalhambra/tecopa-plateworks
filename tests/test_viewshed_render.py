# tests/test_viewshed_render.py
"""The viewshed wash on a sheet: the spec field, the mask `render` reads, and the pass.

docs/superpowers/specs/2026-11-01-viewshed-wash-design.md. The sweep has its own tests in
tests/test_viewshed.py. These hold what the sheet owes: off is a strict no-op, the mask
is the plate's and not the frame's, proof and final agree, and the terrain stays the
subject. Most tests paint a small plate written here, so the ground is known exactly."""
import json
import os
import time

import numpy as np
import pytest
import rasterio
from PIL import Image, ImageDraw
from rasterio.transform import from_origin

from app import looks, relief, render, viewshed
from app.relief import shaded_relief
from app.serialize import spec_from_json, spec_to_json
from app.spec import STYLE_BOUNDS, CompositionSpec, SpecError
from tests.conftest import synthetic_region

LEFT, TOP = 500_000.0, 4_500_000.0
CELL = 100.0                        # the plate's own cell, on the raster
SIZE = 600                          # 60 km square
NO_WATER = {"lakes": [], "rivers": []}


def _tower(height=1500.0, at=(150, 300), base=2000.0):
    """A bare plain with one sharp spike. A mark on top sees the plain right to the foot
    of the spike and off the edge of the plate: 60 km is well inside its horizon. (A
    rounded summit is not this. Its own shoulder hides the ground near it.)"""
    dem = np.full((SIZE, SIZE), base, dtype="float32")
    dem[at] += height
    return dem


def _wall(dem, row, cols=(0, SIZE), height=3000.0):
    """A ridge one east-west line of cells thick, here two cells so no ray misses it."""
    dem = dem.copy()
    dem[row:row + 2, cols[0]:cols[1]] += height
    return dem


def _plate(tmp_path, dem, cell=CELL, name="plate"):
    """A plate on disk: a DEM and a region.json. `native_resolution_m` on the record says
    10 m on purpose, so a grid that trusted a constant instead of the raster would differ."""
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    dem = np.asarray(dem, dtype="float32")
    h, w = dem.shape
    with rasterio.open(d / "dem.tif", "w", driver="GTiff", dtype="float32", count=1,
                       height=h, width=w, crs="EPSG:32611", nodata=np.nan,
                       transform=from_origin(LEFT, TOP, cell, cell)) as ds:
        ds.write(dem, 1)
    finite = dem[np.isfinite(dem)]
    cfg = dict(id=name, crs="EPSG:32611", dem_path="dem.tif",
               bounds=[LEFT, TOP - h * cell, LEFT + w * cell, TOP],
               native_resolution_m=10,
               elevation_min=float(finite.min()) if finite.size else 0.0,
               elevation_max=float(finite.max()) if finite.size else 1.0,
               light_azimuth=315, light_altitude=45, z_factor=1.0)
    (d / "region.json").write_text(json.dumps(cfg))
    return str(d), cfg


def _xy(row, col, cell=CELL):
    """The ground at the centre of cell (row, col)."""
    return LEFT + (col + 0.5) * cell, TOP - (row + 0.5) * cell


def _mark(row, col, **kw):
    x, y = _xy(row, col)
    return {"x": x, "y": y, "weight": 1, "mark": True, **kw}


# The sheet: the southern half of the plate's middle, 30 km across. Row 300 and below.
CROP = (LEFT + 15_000.0, TOP - 54_000.0, LEFT + 45_000.0, TOP - 34_000.0)


def _spec(hotspots=(), viewshed=1.0, crop=CROP, **kw):
    d = dict(region_id="plate", crs="EPSG:32611", crop=crop, print_w_in=3.0,
             print_h_in=(crop[3] - crop[1]) / (crop[2] - crop[0]) * 3.0,
             native_resolution_m=10.0, tracks=[], hotspots=list(hotspots), seed=7,
             title_text="-", compass=False, marker_diameter_in=0.1, viewshed=viewshed)
    d.update(kw)
    return CompositionSpec(**d)


def _paint(spec, region_dir, cfg, dpi=96, hydro=NO_WATER):
    return np.asarray(render.rasterize(spec, dpi=dpi, region_dir=region_dir, cfg=cfg,
                                       hydro=hydro).convert("RGB"), dtype=np.float32)


@pytest.fixture(autouse=True)
def _no_masks_across_tests():
    render._SEEN_MASKS.clear()
    yield
    render._SEEN_MASKS.clear()


@pytest.fixture
def sweeps(monkeypatch):
    """Counts the sweeps. A list, one entry a sweep, holding the cells it was given."""
    calls = []
    real = viewshed.seen_mask

    def counted(dem, res_m, cells):
        calls.append(list(cells))
        return real(dem, res_m, cells)
    monkeypatch.setattr(render.viewshed, "seen_mask", counted)
    return calls


def _quiet(a, b):
    """The fall in value from `a` (off) to `b` (on), as a fraction, mean over the array."""
    return 1.0 - float(b.mean()) / float(a.mean())


# ---- the field ----------------------------------------------------------------------

def test_the_field_defaults_off_and_is_bounded():
    assert _spec(viewshed=0.0).viewshed == 0.0
    assert CompositionSpec(region_id="x", crs="EPSG:32611", crop=CROP, print_w_in=3,
                           print_h_in=2, native_resolution_m=10, tracks=[],
                           hotspots=[]).viewshed == 0.0
    assert STYLE_BOUNDS["viewshed"] == (0.0, 1.0)


@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan")])
def test_a_knob_out_of_bounds_is_refused(bad):
    with pytest.raises(SpecError):
        _spec(viewshed=bad).validate(dpi=96)


def test_an_old_manifest_reads_as_off():
    payload = spec_to_json(_spec(viewshed=0.5))
    assert payload["viewshed"] == 0.5
    payload.pop("viewshed")
    assert spec_from_json(payload).viewshed == 0.0


# ---- off is off -----------------------------------------------------------------------

def test_off_is_a_strict_no_op(tmp_path):
    """The same spec at 0.0, with the pass registered and without it, gives the same
    bytes, in the relief and through the whole sheet."""
    plate = _plate(tmp_path, _tower())
    spec = _spec([_mark(150, 300)], viewshed=0.0)
    elev = np.asarray(_tower()[:80, :90], dtype="float32")
    kw = dict(res_m=30.0, elev_min=2000.0, elev_max=3500.0, shadow=0.6)
    with_pass = shaded_relief(elev, extras={"soft_light": 0.0, "haze": 0.0, "viewshed": 0.0},
                              **kw)
    sheet = _paint(spec, *plate)
    relief.unregister_relief_pass("finish", "viewshed")
    try:
        assert np.array_equal(with_pass, shaded_relief(elev, **kw))
        assert np.array_equal(sheet, _paint(spec, *plate))
    finally:
        looks.register()


def test_the_plate_is_not_read_when_off(tmp_path, monkeypatch):
    region_dir, cfg = _plate(tmp_path, _tower())

    def refused(*a, **kw):
        raise AssertionError("the plate was read for the wash at 0.0")
    monkeypatch.setattr(render.rasterio, "open", refused)
    assert render._seen_field(_spec([_mark(150, 300)], viewshed=0.0), region_dir, cfg,
                              CROP) is None


def test_the_extras_carry_the_strength_and_no_field(tmp_path):
    assert render._relief_extras(_spec(viewshed=0.0))["viewshed"] == 0.0
    assert render._relief_extras(_spec(viewshed=0.4))["viewshed"] == 0.4
    assert "seen" not in render._relief_extras(_spec(viewshed=0.4))


def test_no_marks_paints_as_off(tmp_path, sweeps):
    """A density spot is not a mark, so a knob at 1.0 has nothing to look from."""
    plate = _plate(tmp_path, _tower())
    density = [{"x": _xy(400, 300)[0], "y": _xy(400, 300)[1], "weight": 4}]
    on = _paint(_spec(density, viewshed=1.0), *plate)
    off = _paint(_spec(density, viewshed=0.0), *plate)
    assert np.array_equal(on, off)
    assert not sweeps


def test_a_density_spot_widens_nothing_until_it_is_named(tmp_path):
    region_dir, cfg = _plate(tmp_path, _tower())
    x, y = _xy(150, 300)
    assert render._seen_field(_spec([{"x": x, "y": y, "weight": 2}]), region_dir, cfg,
                              CROP) is None
    named = _spec([{"x": x, "y": y, "weight": 2, "label": "Camp"}])
    assert render._seen_field(named, region_dir, cfg, CROP) is not None


# ---- marks at the edges --------------------------------------------------------------

def test_a_mark_off_the_plate_is_ignored_and_does_not_fail(tmp_path):
    plate = _plate(tmp_path, _wall(_tower(), 200, cols=(0, 300)))
    region_dir, cfg = plate
    far = {"x": LEFT - 90_000.0, "y": TOP + 90_000.0, "weight": 1, "mark": True}
    good = _mark(150, 300)
    # among good marks: exactly the good mark's wash
    mixed = render._seen_field(_spec([far, good]), region_dir, cfg, CROP)
    alone = render._seen_field(_spec([good]), region_dir, cfg, CROP)
    assert np.array_equal(mixed.mask, alone.mask)
    # alone: nothing lands on the plate, and that is not "sees nothing"
    assert render._seen_field(_spec([far]), region_dir, cfg, CROP) is None
    assert np.array_equal(_paint(_spec([far], viewshed=1.0), *plate),
                          _paint(_spec([far], viewshed=0.0), *plate))


def test_a_plate_with_no_ground_does_not_quiet_the_sheet(tmp_path):
    """An all-False mask must never reach the pass. A plate all holes is the other way to
    get one, with a mark squarely on it."""
    region_dir, cfg = _plate(tmp_path, np.full((SIZE, SIZE), np.nan, dtype="float32"))
    assert render._seen_field(_spec([_mark(150, 300)]), region_dir, cfg, CROP) is None


@pytest.mark.parametrize("dx,dy", [(0.1, -0.1), (SIZE * CELL - 0.1, -0.1),
                                   (0.1, -(SIZE * CELL - 0.1)),
                                   (SIZE * CELL - 0.1, -(SIZE * CELL - 0.1))])
def test_a_mark_inside_the_outermost_cell_counts(tmp_path, dx, dy):
    """Past the last cell's centre, inside its edge: `seen_mask`'s rule, not a tighter one."""
    region_dir, cfg = _plate(tmp_path, _tower(height=0.0))
    mark = {"x": LEFT + dx, "y": TOP + dy, "weight": 1, "mark": True}
    assert render._seen_field(_spec([mark]), region_dir, cfg, CROP) is not None


def test_a_mark_in_a_hole_still_washes(tmp_path):
    dem = _tower(height=0.0)
    dem[148:153, 298:303] = np.nan
    region_dir, cfg = _plate(tmp_path, dem)
    field = render._seen_field(_spec([_mark(150, 300)]), region_dir, cfg, CROP)
    assert field is not None and field.mask.max() == 1.0


def test_a_ridge_off_the_sheet_still_blocks(tmp_path):
    """The ridge and the mark are both north of the sheet. The sheet's ground is seen from
    the hill on a clear plate, and quieted on a plate with the ridge, though no pixel of
    the sheet shows the ridge."""
    clear = _plate(tmp_path, _tower(), name="clear")
    ridged = _plate(tmp_path, _wall(_tower(), 280), name="ridged")
    marks = [_mark(150, 300)]
    assert _quiet(_paint(_spec(marks, 0.0), *clear), _paint(_spec(marks), *clear)) < 0.01
    assert _quiet(_paint(_spec(marks, 0.0), *ridged), _paint(_spec(marks), *ridged)) > 0.08


def test_a_mark_off_the_sheet_still_washes(tmp_path):
    """A ridge shades the sheet's west half only. The mark is off the sheet, and the sheet
    still splits along what it sees."""
    plate = _plate(tmp_path, _wall(_tower(), 280, cols=(0, 300)))
    marks = [_mark(150, 300)]
    off, on = _paint(_spec(marks, 0.0), *plate), _paint(_spec(marks), *plate)
    w = off.shape[1]
    # a band of the sheet well clear of the ray that grazes the ridge's end
    assert _quiet(off[:, : w // 4], on[:, : w // 4]) > 0.08
    assert _quiet(off[:, -w // 4:], on[:, -w // 4:]) < 0.01


def test_more_marks_only_grow_the_seen_ground(tmp_path):
    region_dir, cfg = _plate(tmp_path, _wall(_tower(), 280, cols=(0, 300)))
    one = render._seen_field(_spec([_mark(150, 300)]), region_dir, cfg, CROP).mask
    two = render._seen_field(_spec([_mark(150, 300), _mark(500, 100)]), region_dir, cfg,
                             CROP).mask
    assert (two >= one).all() and two.sum() > one.sum()


# ---- the grid and the store ----------------------------------------------------------

def test_the_grid_reads_the_plate_s_own_cell_from_the_raster(tmp_path):
    """The record says 10 m and the raster says 100 m. 100 m wins."""
    region_dir, cfg = _plate(tmp_path, _tower())
    field = render._seen_field(_spec([_mark(150, 300)]), region_dir, cfg, CROP)
    assert field.mask.shape == (SIZE, SIZE)
    assert field.transform.a == pytest.approx(CELL)
    assert field.transform.e == pytest.approx(-CELL)
    assert field.transform.c == pytest.approx(LEFT)
    assert field.transform.f == pytest.approx(TOP)


def test_the_grid_holds_the_budget_on_a_plate_past_it(tmp_path, monkeypatch):
    monkeypatch.setattr(viewshed, "GRID_BUDGET_CELLS", 10_000)
    region_dir, cfg = _plate(tmp_path, _tower())
    field = render._seen_field(_spec([_mark(150, 300)]), region_dir, cfg, CROP)
    assert field.mask.shape == (100, 100)
    assert field.transform.a == pytest.approx(600.0)
    assert field.mask.dtype == np.float32


def test_the_mask_is_the_plate_s_and_the_field_carries_the_window(tmp_path):
    region_dir, cfg = _plate(tmp_path, _tower())
    a = render._seen_field(_spec([_mark(150, 300)]), region_dir, cfg, (1.0, 2.0, 3.0, 4.0))
    b = render._seen_field(_spec([_mark(150, 300)]), region_dir, cfg, (5.0, 6.0, 7.0, 8.0))
    assert a.bounds == (1.0, 2.0, 3.0, 4.0) and b.bounds == (5.0, 6.0, 7.0, 8.0)
    assert a.mask is b.mask
    assert not a.mask.flags.writeable


def test_equal_sets_of_marks_share_one_sweep(tmp_path, sweeps):
    region_dir, cfg = _plate(tmp_path, _tower())
    m, n = _mark(150, 300), _mark(500, 100)
    first = render._seen_field(_spec([m, n]), region_dir, cfg, CROP)
    second = render._seen_field(_spec([n, m]), region_dir, cfg, CROP)
    third = render._seen_field(_spec([m, n, dict(n), {**m, "label": "Camp"}]), region_dir,
                               cfg, CROP)
    assert first.mask is second.mask is third.mask
    assert len(sweeps) == 1


def test_a_changed_plate_sweeps_again(tmp_path, sweeps):
    region_dir, cfg = _plate(tmp_path, _tower())
    spec = _spec([_mark(150, 300)])
    render._seen_field(spec, region_dir, cfg, CROP)
    dem = os.path.join(region_dir, "dem.tif")
    st = os.stat(dem)
    os.utime(dem, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    render._seen_field(spec, region_dir, cfg, CROP)
    assert len(sweeps) == 2


def test_the_store_holds_a_few_masks(tmp_path, sweeps):
    region_dir, cfg = _plate(tmp_path, _tower(height=0.0))
    for i in range(render.SEEN_MASKS_MAX + 3):
        render._seen_field(_spec([_mark(150 + i, 300)]), region_dir, cfg, CROP)
    assert len(render._SEEN_MASKS) == render.SEEN_MASKS_MAX <= 4
    assert len(sweeps) == render.SEEN_MASKS_MAX + 3
    # the newest is still held, and the oldest is gone
    render._seen_field(_spec([_mark(150 + render.SEEN_MASKS_MAX + 2, 300)]), region_dir, cfg, CROP)
    assert len(sweeps) == render.SEEN_MASKS_MAX + 3
    render._seen_field(_spec([_mark(150, 300)]), region_dir, cfg, CROP)
    assert len(sweeps) == render.SEEN_MASKS_MAX + 4


def test_a_new_strength_does_not_sweep_again(tmp_path, sweeps):
    plate = _plate(tmp_path, _wall(_tower(), 280))
    marks = [_mark(150, 300)]
    full = _paint(_spec(marks, 1.0), *plate)
    half = _paint(_spec(marks, 0.5), *plate)
    off = _paint(_spec(marks, 0.0), *plate)
    assert len(sweeps) == 1
    assert _quiet(off, half) < _quiet(off, full)


def test_a_crafted_file_stays_in_budget(tmp_path, sweeps):
    """1,000 marks on one spot are one place to look from, in less than the sweep's own
    budget test allows (tests/test_viewshed.py, 45 s)."""
    plate = _plate(tmp_path, _tower())
    crafted = [_mark(150, 300, label=f"m{i}") for i in range(1000)]
    started = time.perf_counter()
    _paint(_spec(crafted), *plate)
    assert time.perf_counter() - started < 45.0
    assert len(sweeps) == 1 and len(sweeps[0]) == 1


# ---- the look -------------------------------------------------------------------------

def _field_of(shape, seen=0.0):
    """A SeenField over `shape` whose every cell says `seen`, 1 m a cell."""
    h, w = shape
    mask = np.full((h, w), seen, dtype=np.float32)
    transform = rasterio.Affine(1.0, 0.0, 0.0, 0.0, -1.0, float(h))
    return render.SeenField(mask, transform, (0.0, 0.0, float(w), float(h)))


def _frame(shape, **extras):
    elev = np.full(shape, 1500.0, dtype=np.float32)
    return relief.ReliefFrame(elev=elev, res_m=1.0, norm=np.full(shape, 0.5, dtype=np.float32),
                              elev_min=1000.0, elev_max=2000.0, seed=1, azimuth=315.0,
                              altitude=45.0, z_factor=1.0, extras=extras)


@pytest.mark.parametrize("grey", [0.2, 0.35, 0.5, 0.65, 0.8, 1.0])
def test_unseen_ground_falls_at_most_15_percent(grey):
    """On a grey sheet at knob 1.0, on what prints: the tonal curve runs after this stage
    and steepens the midtones, so the fall is held after the curve as well as before."""
    shape = (8, 8)
    frame = _frame(shape, viewshed=1.0, seen=_field_of(shape))
    sheet = np.full(shape + (3,), grey, dtype=np.float32)
    quieted = looks._viewshed(sheet.copy(), frame)
    assert 0.08 < 1.0 - quieted.mean() / grey <= 0.15
    printed = relief._tonal_finish(sheet.copy()).mean()
    assert 0.08 < 1.0 - relief._tonal_finish(quieted).mean() / printed <= 0.15


def test_unseen_ground_loses_saturation_and_keeps_its_hue():
    shape = (4, 4)
    frame = _frame(shape, viewshed=1.0, seen=_field_of(shape))
    sheet = np.zeros(shape + (3,), dtype=np.float32)
    sheet[...] = (0.7, 0.5, 0.3)
    out = looks._viewshed(sheet.copy(), frame)[0, 0]
    assert out[0] > out[1] > out[2]                         # warm stays warm
    assert (out.max() - out.min()) / out.max() < (0.7 - 0.3) / 0.7


def test_seen_ground_is_left_exactly_as_it_is():
    shape = (300, 40)
    frame = _frame(shape, viewshed=1.0, seen=_field_of(shape, seen=1.0))
    rng = np.random.default_rng(4)
    sheet = rng.uniform(0.0, 1.0, shape + (3,)).astype("float32")
    assert np.array_equal(looks._viewshed(sheet.copy(), frame), sheet)


def test_a_sheet_that_sees_it_all_is_the_sheet_without_the_wash(tmp_path):
    plate = _plate(tmp_path, _tower())
    marks = [_mark(150, 300)]
    region_dir, cfg = plate
    field = render._seen_field(_spec(marks), region_dir, cfg, CROP)
    row0, col0 = int((TOP - CROP[3]) / CELL), int((CROP[0] - LEFT) / CELL)
    row1, col1 = int((TOP - CROP[1]) / CELL), int((CROP[2] - LEFT) / CELL)
    assert (field.mask[row0:row1, col0:col1] == 1.0).all()
    assert np.array_equal(_paint(_spec(marks), *plate), _paint(_spec(marks, 0.0), *plate))


def test_the_knob_scales_the_quieting():
    shape = (4, 4)
    sheet = np.full(shape + (3,), 0.5, dtype=np.float32)
    field = _field_of(shape)
    half = looks._viewshed(sheet.copy(), _frame(shape, viewshed=0.5, seen=field)).mean()
    full = looks._viewshed(sheet.copy(), _frame(shape, viewshed=1.0, seen=field)).mean()
    assert 0.5 - half == pytest.approx((0.5 - full) / 2, rel=1e-3)


def test_the_pass_writes_in_place_and_leaves_the_mask_alone():
    shape = (4, 4)
    field = _field_of(shape)
    field.mask.flags.writeable = False
    sheet = np.full(shape + (3,), 0.5, dtype=np.float32)
    assert looks._viewshed(sheet, _frame(shape, viewshed=1.0, seen=field)) is sheet
    assert sheet.mean() < 0.5


def test_the_pass_needs_the_knob_and_the_field():
    shape = (4, 4)
    enabled = {p[0]: p[2] for p in relief._RELIEF_PASSES["finish"]}["viewshed"]
    field = _field_of(shape)
    assert enabled(_frame(shape, viewshed=1.0, seen=field))
    assert not enabled(_frame(shape, viewshed=1.0))
    assert not enabled(_frame(shape, viewshed=0.0, seen=field))
    assert not enabled(_frame(shape))


def test_the_band_size_does_not_move_a_pixel(monkeypatch):
    """One band and many bands give the same bytes (docs/relief-passes.md, Memory)."""
    shape = (301, 37)
    rng = np.random.default_rng(9)
    mask = rng.uniform(0.0, 1.0, (40, 30)).astype("float32")
    transform = rasterio.Affine(10.0, 0.0, 0.0, 0.0, -10.0, 400.0)
    field = render.SeenField(mask, transform, (12.0, 20.0, 280.0, 380.0))
    frame = _frame(shape, viewshed=0.8, seen=field)
    sheet = rng.uniform(0.0, 1.0, shape + (3,)).astype("float32")
    monkeypatch.setattr(relief, "BAND_ROWS", 10 ** 9)
    whole = looks._viewshed(sheet.copy(), frame)
    for rows in (1, 7, 256):
        monkeypatch.setattr(relief, "BAND_ROWS", rows)
        assert np.array_equal(whole, looks._viewshed(sheet.copy(), frame)), f"{rows}-row bands"


def test_the_pass_samples_by_ground_not_by_pixel():
    """A mask split at x = 50 m lands at x = 50 m on a sheet of any size."""
    mask = np.ones((10, 10), dtype=np.float32)
    mask[:, 5:] = 0.0
    transform = rasterio.Affine(10.0, 0.0, 0.0, 0.0, -10.0, 100.0)
    field = render.SeenField(mask, transform, (0.0, 0.0, 100.0, 100.0))
    for side in (10, 100, 1000):
        shape = (side, side)
        sheet = np.full(shape + (3,), 0.5, dtype=np.float32)
        out = looks._viewshed(sheet, _frame(shape, viewshed=1.0, seen=field))[side // 2, :, 0]
        x = (np.arange(side) + 0.5) * 100.0 / side
        assert (out[x < 40.0] == 0.5).all() and (out[x > 60.0] < 0.5).all()


# ---- the edge -------------------------------------------------------------------------

def _edge_width_m(profile, cell):
    """Ground metres between 10% and 90% across a falling profile, read off by
    interpolation."""
    p = np.asarray(profile, dtype=float)
    p = (p - p.min()) / (p.max() - p.min())
    idx = np.arange(p.size)
    return (np.interp(0.1, p[::-1], idx[::-1]) - np.interp(0.9, p[::-1], idx[::-1])) * cell


def test_a_seen_edge_feathers_over_about_100_m(tmp_path):
    """Cells of 20 m, so the feather is set by the 100 m floor and not by the grid. A wall
    makes a long straight edge on the plate, and the mask crosses it over about 100 m."""
    n = 1000
    cell = 20.0
    dem = np.full((n, n), 1000.0, dtype="float32")
    dem[100, 500] += 1200.0
    dem[300:303, :] += 2000.0
    region_dir, cfg = _plate(tmp_path, dem, cell=cell)
    mark = {"x": LEFT + 500.5 * cell, "y": TOP - 100.5 * cell, "weight": 1, "mark": True}
    mask = render._seen_field(_spec([mark]), region_dir, cfg, CROP).mask
    profile = mask[270:330, 500]
    assert profile[0] == 1.0 and profile[-1] == 0.0
    width = _edge_width_m(profile, cell)
    assert 70.0 < width < 140.0, f"{width:.0f} m"


@pytest.mark.parametrize("res_m,feather_m", [(10.0, 100.0), (33.0, 100.0), (39.0, 117.0),
                                             (100.0, 300.0), (200.0, 600.0)])
def test_the_feather_is_100_m_or_three_cells(res_m, feather_m):
    """On Elko a cell is about 200 m, and a 100 m feather could not hide the cell's edge."""
    assert render._seen_feather_m(res_m) == pytest.approx(feather_m)


# ---- proof and final -------------------------------------------------------------------

def test_proof_and_final_agree_on_seen_ground(monkeypatch, sweeps):
    """The same mask object at both dpis, and the proof a faithful scale of the final, with
    the crop and the bound of test_proof_relief_is_a_faithful_scale_of_final."""
    region_dir = synthetic_region("lassen_ca")
    with open(os.path.join(region_dir, "region.json")) as f:
        cfg = json.load(f)
    b = cfg["bounds"]
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    crop = (cx - 13_500, cy - 18_000, cx + 13_500, cy + 18_000)
    mark = {"x": cx, "y": cy, "weight": 1, "mark": True}
    held = []
    real = render._seen_field

    def spy(*a, **kw):
        held.append(real(*a, **kw))
        return held[-1]
    monkeypatch.setattr(render, "_seen_field", spy)

    def paint(strength, dpi):
        spec = CompositionSpec(region_id=cfg["id"], crs=cfg["crs"], crop=crop, print_w_in=3,
                               print_h_in=4, native_resolution_m=10, tracks=[],
                               hotspots=[mark], seed=7, viewshed=strength,
                               marker_diameter_in=0.1)
        return render.rasterize(spec, dpi=dpi, region_dir=region_dir, cfg=cfg,
                                hydro=NO_WATER).convert("RGB")
    proof, final = paint(1.0, 96), paint(1.0, 300)
    assert held[0].mask is held[1].mask
    assert held[0].bounds != held[1].bounds             # integer pads, per dpi
    assert len(sweeps) == 1
    scaled = final.resize(proof.size, Image.LANCZOS)
    mad = np.abs(np.asarray(proof, np.float32) - np.asarray(scaled, np.float32)).mean()
    assert mad < 3.0, f"mean abs diff {mad:.2f}/255"
    # The wash itself, block by block: the fall from off to on is the same at both dpis.
    def fall(on, off):
        h, w = np.asarray(paint(1.0, 96)).shape[:2]
        on = np.asarray(on.resize((w, h), Image.LANCZOS), np.float32).mean(axis=2)
        off = np.asarray(off.resize((w, h), Image.LANCZOS), np.float32).mean(axis=2)
        d = (off - on)[: h // 16 * 16, : w // 16 * 16]
        return d.reshape(h // 16, 16, w // 16, 16).mean(axis=(1, 3))
    at_proof, at_final = fall(proof, paint(0.0, 96)), fall(final, paint(0.0, 300))
    assert at_proof.max() > 15.0, "the mark must leave ground unseen on this sheet"
    assert np.abs(at_proof - at_final).max() < 3.0


# ---- water and other seams ------------------------------------------------------------

def _lake(crop):
    x0, y0, x1, y1 = crop
    w, h = x1 - x0, y1 - y0
    ring = [[x0 + w * 0.3, y0 + h * 0.3], [x0 + w * 0.7, y0 + h * 0.3],
            [x0 + w * 0.7, y0 + h * 0.7], [x0 + w * 0.3, y0 + h * 0.7]]
    return {"lakes": [{"name": "", "coords": ring}], "rivers": []}


def _lake_mask(hydro, spec, img):
    h, w = img.shape[:2]
    mask = Image.new("1", (w, h))
    pts = render._lake_polygons_px(hydro, spec, w, h, None)
    assert pts, "the fixture's lake must draw"
    ImageDraw.Draw(mask).polygon(pts[0], fill=1)
    return np.asarray(mask)


@pytest.mark.parametrize("water_depth", [0.0, 0.5])
def test_water_keeps_its_colour(tmp_path, water_depth):
    """Water paints after the `finish` stage, so the wash never reaches it. The flat fill
    and the graded body are 235 of 255 opaque on purpose (`_draw_hydro`), so the lakebed's 8%
    ghost carries an 8% share of the wash and no more: at most 3 levels in a channel, where
    the ground beside the lake falls by more than 10 on average."""
    plate = _plate(tmp_path, _wall(_tower(), 280))
    marks = [_mark(150, 300)]
    hydro = _lake(CROP)
    spec_on = _spec(marks, 1.0, water_depth=water_depth)
    spec_off = _spec(marks, 0.0, water_depth=water_depth)
    on, off = _paint(spec_on, *plate, hydro=hydro), _paint(spec_off, *plate, hydro=hydro)
    water = _lake_mask(hydro, spec_on, on)
    assert np.abs(on - off)[water].max() <= 3.0
    land = ~water
    assert (off - on)[land].mean() > 10.0


def test_water_paints_after_the_finish_stage(tmp_path, monkeypatch):
    """The order the wash's promise rests on, read from the path itself."""
    region_dir, cfg = _plate(tmp_path, _tower())
    order = []
    real_hydro, real_pass = render._draw_hydro, looks._viewshed

    def hydro(*a, **kw):
        order.append("hydro")
        return real_hydro(*a, **kw)

    def wash(img, frame):
        order.append("wash")
        return real_pass(img, frame)
    monkeypatch.setattr(render, "_draw_hydro", hydro)
    relief.register_relief_pass("finish", "viewshed", wash, enabled=lambda f: "seen" in f.extras)
    try:
        spec = _spec([_mark(150, 300)])
        render.rasterize(spec, dpi=96, region_dir=region_dir, cfg=cfg, hydro=NO_WATER)
    finally:
        looks.register()
    assert order == ["wash", "hydro"]


def test_a_terrain_override_never_reads_the_mask(tmp_path, sweeps):
    region_dir, cfg = _plate(tmp_path, _tower())
    spec = _spec([_mark(150, 300)])
    _elev, _res, shape = render.terrain_window(spec, 96, region_dir, cfg)
    override = np.full(shape + (3,), 128, dtype=np.uint8)
    render.rasterize(spec, dpi=96, region_dir=region_dir, cfg=cfg, hydro=NO_WATER,
                     terrain_override=override)
    assert not sweeps


def test_the_wash_paints_under_high_relief_and_a_bleed(tmp_path):
    """The window the pass samples is the padded one, whatever pads it: the south band of
    the plan-oblique shear, and the sheet a bleed grows."""
    plate = _plate(tmp_path, _wall(_tower(), 280))
    marks = [_mark(150, 300)]
    for kw in (dict(oblique=0.5), dict(bleed_in=0.125)):
        off = _paint(_spec(marks, 0.0, **kw), *plate)
        on = _paint(_spec(marks, 1.0, **kw), *plate)
        assert _quiet(off, on) > 0.05, kw


def test_the_same_spec_paints_the_same_bytes(tmp_path):
    plate = _plate(tmp_path, _wall(_tower(), 280, cols=(0, 300)))
    spec = _spec([_mark(150, 300)])
    first = _paint(spec, *plate)
    render._SEEN_MASKS.clear()
    assert np.array_equal(first, _paint(spec, *plate))


def test_the_wash_paints_on_a_plate_with_no_cfg_handed_in():
    """The harness's own plate, through region_dir alone: the path a studio proof takes."""
    region_dir = synthetic_region("lassen_ca")
    with open(os.path.join(region_dir, "region.json")) as f:
        cfg = json.load(f)
    b = cfg["bounds"]
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    crop = (cx - 13_500, cy - 18_000, cx + 13_500, cy + 18_000)
    spec = CompositionSpec(region_id=cfg["id"], crs=cfg["crs"], crop=crop, print_w_in=3,
                           print_h_in=4, native_resolution_m=10, tracks=[],
                           hotspots=[{"x": cx, "y": cy, "weight": 1, "label": "Here"}],
                           seed=7, viewshed=1.0)
    on = render.rasterize(spec, dpi=96, region_dir=region_dir, hydro=NO_WATER)
    off = render.rasterize(CompositionSpec(**{**spec.__dict__, "viewshed": 0.0}), dpi=96,
                           region_dir=region_dir, hydro=NO_WATER)
    assert not np.array_equal(np.asarray(on), np.asarray(off))
