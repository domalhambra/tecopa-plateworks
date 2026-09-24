# tests/test_region_prep.py
# The build planner: resolution auto-selection, memory-bounding slice counts, and
# grid geometry -- all pure logic (pyproj + numpy, no fetch stack), so the guard
# against another 15.8 GB accidental build runs in the core CI env.
import os

import numpy as np
import pytest
rp = pytest.importorskip("region_prep")

LASSEN = (-120.90, 40.33, -120.50, 40.78)          # county-scale (~34 x 50 km)
CORRIDOR = (-116.95, 39.20, -111.35, 42.05)        # elko_bonneville (~483 x 331 km)
# a worst-case 16x20 order's widened frame: ~200 x 300 km, EPSG:32611
ORDER_16X20 = (-117.5, 36.5, -115.2, 39.2)


def test_auto_picks_fine_grid_for_county_scale():
    plan = rp.plan_build(LASSEN, "EPSG:32610")
    assert plan["auto"] and plan["resolution_m"] == 10
    assert plan["n_slices"] == 1                    # small builds stay one-shot
    assert not plan["over_budget"]
    assert plan["landcover_resolution_m"] == 30


def test_auto_coarsens_corridor_scale_and_slices_it():
    plan = rp.plan_build(CORRIDOR, "EPSG:32611")
    assert plan["auto"] and plan["resolution_m"] == 30   # 10 m would be ~1.6 Gpx
    assert plan["grid_mpx"] <= rp.GRID_BUDGET_MPX
    assert plan["n_slices"] > 1                     # the memory cap engages
    assert plan["grid_mpx"] / plan["n_slices"] <= rp.SLICE_BUDGET_MPX
    assert plan["landcover_resolution_m"] == 60     # 30 m NLCD merge is the OOM


def test_explicit_resolution_is_honored_but_flagged():
    plan = rp.plan_build(CORRIDOR, "EPSG:32611", resolution_m=10)
    assert not plan["auto"] and plan["resolution_m"] == 10
    assert plan["over_budget"], "a ~1.6 Gpx build must be loudly flagged"
    # even forced-fine, slicing keeps the per-slice cost bounded
    assert plan["grid_mpx"] / plan["n_slices"] <= rp.SLICE_BUDGET_MPX


# ---- explicit-resolution land cover: bakes at the DEM's own grid, floored at 30 m
# (order plates, acceptance 2026-09-24: an 874 s east-west build whose land cover
# failed because it stayed at a fixed 60 m WMS mosaic over a ~350 Mpx area) ----

def test_explicit_coarse_resolution_bakes_landcover_at_its_own_grid():
    # a 210 m east-west order plate: land cover should match, not sit at 60 m
    plan = rp.plan_build(CORRIDOR, "EPSG:32611", resolution_m=210)
    assert plan["landcover_resolution_m"] == 210


def test_explicit_resolution_below_30m_still_bakes_30m_landcover():
    # NLCD's own native resolution is 30 m; nothing finer is worth fetching
    plan = rp.plan_build(LASSEN, "EPSG:32610", resolution_m=10)
    assert plan["landcover_resolution_m"] == 30
    plan = rp.plan_build(LASSEN, "EPSG:32610", resolution_m=4.5)
    assert plan["landcover_resolution_m"] == 30


def test_explicit_resolution_landcover_rounds_to_the_nearest_metre():
    # LASSEN is small enough that 46 m land cover stays under budget: no coarsening
    plan = rp.plan_build(LASSEN, "EPSG:32610", resolution_m=45.6)
    assert plan["landcover_resolution_m"] == 46


def test_explicit_resolution_landcover_rounds_then_coarsens_when_over_budget():
    # CORRIDOR at 45.6 m rounds to 46 m first (~75 Mpx, over budget), then doubles
    plan = rp.plan_build(CORRIDOR, "EPSG:32611", resolution_m=45.6)
    assert plan["landcover_resolution_m"] == 92
    w, h, _ = rp.projected_grid(CORRIDOR, "EPSG:32611", plan["landcover_resolution_m"])
    assert w * h <= rp.LANDCOVER_BUDGET_MPX * 1e6


def test_explicit_30m_resolution_bakes_30m_landcover_when_under_budget():
    # LASSEN's own grid at 30 m is small; nothing to coarsen
    plan = rp.plan_build(LASSEN, "EPSG:32610", resolution_m=30)
    assert plan["landcover_resolution_m"] == 30


def test_explicit_resolution_landcover_coarsens_when_over_budget():
    # CORRIDOR at its own 30 m grid is ~177 Mpx of land cover -- almost 3x
    # LANDCOVER_BUDGET_MPX -- so it coarsens, exactly like the auto path would for
    # this same box (test_auto_coarsens_corridor_scale_and_slices_it: 60 m)
    plan = rp.plan_build(CORRIDOR, "EPSG:32611", resolution_m=30)
    assert plan["landcover_resolution_m"] == 60
    w, h, _ = rp.projected_grid(CORRIDOR, "EPSG:32611", plan["landcover_resolution_m"])
    assert w * h <= rp.LANDCOVER_BUDGET_MPX * 1e6


def test_explicit_resolution_landcover_coarsens_over_a_worst_case_order_box():
    # a ~200 x 300 km widened frame (a 16x20 order pushed past 2x upsample): the
    # DEM's own 30 m grid would bake a ~68 Mpx land cover fetch, over budget
    plan = rp.plan_build(ORDER_16X20, "EPSG:32611", resolution_m=30)
    assert plan["landcover_resolution_m"] >= 60
    w, h, _ = rp.projected_grid(ORDER_16X20, "EPSG:32611", plan["landcover_resolution_m"])
    assert w * h <= rp.LANDCOVER_BUDGET_MPX * 1e6


def test_explicit_210m_grid_over_a_worst_case_order_box_stays_210():
    # already well under budget at the DEM's own grid: no coarsening needed
    plan = rp.plan_build(ORDER_16X20, "EPSG:32611", resolution_m=210)
    assert plan["landcover_resolution_m"] == 210


def test_auto_landcover_choice_is_unchanged_by_the_explicit_path():
    # pin against the numbers from before this change: the auto path must stay
    # exactly as today regardless of the new explicit-resolution branch
    assert rp.plan_build(LASSEN, "EPSG:32610")["landcover_resolution_m"] == 30
    assert rp.plan_build(CORRIDOR, "EPSG:32611")["landcover_resolution_m"] == 60


def test_projected_grid_matches_bbox_ground_size():
    w, h, transform = rp.projected_grid(CORRIDOR, "EPSG:32611", 30)
    # the elko_bonneville region was built on exactly this logic: ~483 x 331 km
    assert abs(w * 30 - 483_000) < 5_000
    assert abs(h * 30 - 331_000) < 5_000
    assert transform.a == 30 and transform.e == -30  # square pixels, north-up
    # grid-snapped origin (registration correctness downstream)
    assert transform.c % 30 == 0 and transform.f % 30 == 0


import argparse
import math


# ---- order plates: every grid is fetched at its own cell size ----

def test_auto_plans_are_unchanged_from_the_original_planner():
    # values computed by region_prep at 47b0719, before any order-plate change
    lassen = rp.plan_build(LASSEN, "EPSG:32610")
    assert lassen["resolution_m"] == 10 and lassen["n_slices"] == 1
    assert lassen["grid"] == (3416, 4984)
    assert lassen["dynamic"] is False
    corridor = rp.plan_build(CORRIDOR, "EPSG:32611")
    assert corridor["resolution_m"] == 30 and corridor["n_slices"] == 5
    assert corridor["grid"] == (16096, 11027)
    assert corridor["dynamic"] is False


def test_dynamic_plan_sizes_slices_for_the_oversampled_fetch():
    # 4 m is off DEM_RES_CHOICES: the dynamic service returns more cells than asked
    plan = rp.plan_build(LASSEN, "EPSG:32610", resolution_m=4.0)
    assert plan["dynamic"] is True
    assert plan["n_slices"] == math.ceil(
        plan["grid_mpx"] * rp.DYNAMIC_OVERSAMPLE / rp.SLICE_BUDGET_MPX)


def test_slice_overlap_deg_keeps_0_03_for_static_and_scales_below_10_m():
    assert rp.slice_overlap_deg(10) == 0.03
    assert rp.slice_overlap_deg(60) == 0.03
    assert rp.slice_overlap_deg(0.5) == 0.002                  # floor
    assert rp.slice_overlap_deg(4) == pytest.approx(300 * 4 / 111_320)   # ~0.0108


def test_resolution_arg():
    assert rp._resolution_arg("auto") is None
    assert rp._resolution_arg("2.5") == 2.5
    # a static layer stays the int it always was, so manifests don't change
    assert rp._resolution_arg("10") == 10 and isinstance(rp._resolution_arg("10"), int)


def test_resolution_arg_rejects_bad_values():
    for bad in ("0", "-5", "not-a-number", "inf", "nan"):
        with pytest.raises(argparse.ArgumentTypeError):
            rp._resolution_arg(bad)


def test_sources_manifest_names_a_static_layer(tmp_path):
    m = rp.write_sources_manifest(str(tmp_path), "r", (-116.3, 35.8, -116.2, 35.9),
                                  "EPSG:32611", built="2026-09-24", resolution_m=10)
    assert m["sources"][0]["dataset"] == "USGS 3DEP 10 m DEM"
    assert m["rebuild"].endswith("--resolution 10")
    assert "--source-resolution" not in m["rebuild"]


def test_sources_manifest_names_the_dynamic_service(tmp_path):
    m = rp.write_sources_manifest(str(tmp_path), "order_y", (-116.3, 35.8, -116.2, 35.9),
                                  "EPSG:32611", built="2026-09-24", resolution_m=25.0)
    assert m["sources"][0]["dataset"] == "USGS 3DEP dynamic service, 25 m"
    assert "--resolution 25.0" in m["rebuild"]
    assert "--source-resolution" not in m["rebuild"]


# ---- slice windows: together they must cover the whole grid ----

@pytest.mark.parametrize("bbox,crs,res", [
    (LASSEN, "EPSG:32610", None),          # auto, one slice
    (CORRIDOR, "EPSG:32611", None),        # auto, 5 slices at 30 m
    (LASSEN, "EPSG:32610", 4.0),           # a 4-slice fine (dynamic) grid
    (LASSEN, "EPSG:32610", 2.0),           # 16 slices
    (CORRIDOR, "EPSG:32611", 10),          # the corridor at 10 m, 40 slices
])
def test_slice_windows_cover_every_column_and_row(bbox, crs, res):
    plan = rp.plan_build(bbox, crs, res)
    w_px, h_px = plan["grid"]
    T = plan["transform"]
    cols = np.zeros(w_px, bool)
    rows = np.zeros(h_px, bool)
    extents = rp._slice_extents(bbox, crs, plan)
    assert len(extents) == plan["n_slices"]
    for _, ext in extents:
        win = rp._slice_window(*ext, T, w_px, h_px)
        c0, r0 = int(win.col_off), int(win.row_off)
        c1, r1 = c0 + int(win.width), r0 + int(win.height)
        assert 0 <= c0 < c1 <= w_px and 0 <= r0 < r1 <= h_px
        cols[c0:c1] = True
        rows[r0:r1] = True
    assert cols.all(), f"columns never written: {np.flatnonzero(~cols)[:10]}"
    assert rows.all(), f"rows never written: {np.flatnonzero(~rows)[:10]}"


def test_slice_window_reaches_the_east_edge_from_a_fractional_start():
    # grid 3000 x 100 at 10 m; a slice starting 1234.7 cells in and running to the
    # east edge. Rounding offset and length apart ended it one column short.
    from rasterio.transform import from_origin
    T = from_origin(0.0, 1000.0, 10.0, 10.0)
    win = rp._slice_window(12347.0, 0.0, 30000.0, 1000.0, T, 3000, 100)
    assert int(win.col_off) == 1234
    assert int(win.col_off) + int(win.width) == 3000
    assert (int(win.row_off), int(win.height)) == (0, 100)


def test_slice_window_adds_no_column_for_float_noise_on_an_exact_edge():
    from rasterio.transform import from_origin
    T = from_origin(0.0, 1000.0, 10.0, 10.0)
    win = rp._slice_window(12340.0 - 1e-9, 0.0, 20000.0 + 1e-9, 1000.0, T, 3000, 100)
    assert (int(win.col_off), int(win.width)) == (1234, 766)


# ---- one test for a static cell size, the one py3dep itself applies ----

NEAR = (10, 10.000001, 10.00005, 9.99995, 10.0002, 30.0001, 30.001, 59.9999,
        60.0007, 25.0, 4.0, 1.0)


@pytest.mark.parametrize("res", NEAR)
def test_is_static_agrees_with_py3dep(res):
    # py3dep.get_dem: `if np.isclose(resolution, (10, 30, 60)).any():` static tiles
    assert rp._is_static(res) == bool(np.isclose(res, (10, 30, 60)).any())


@pytest.mark.parametrize("res,static", [(10.000001, True), (10.00005, True),
                                        (10.0002, False), (25.0, False)])
def test_plan_and_manifest_use_the_same_static_test(tmp_path, res, static):
    plan = rp.plan_build(LASSEN, "EPSG:32610", resolution_m=res)
    assert plan["dynamic"] is (not static)
    m = rp.write_sources_manifest(str(tmp_path), "r", LASSEN, "EPSG:32610",
                                  built="2026-09-24", resolution_m=res)
    assert ("dynamic service" in m["sources"][0]["dataset"]) is (not static)


def test_resolution_arg_refuses_grids_finer_than_half_a_metre():
    assert rp._resolution_arg("0.5") == 0.5
    assert rp._resolution_arg("1") == 1.0
    for bad in ("0.49", "0.1", "1e-3"):
        with pytest.raises(argparse.ArgumentTypeError, match="0.5"):
            rp._resolution_arg(bad)


# ---- a 3DEP fetch is retried through a brief outage (acceptance: WMS 503) ----
import sys
import types


def _fake_py3dep(monkeypatch, outcomes):
    """py3dep stand-in whose get_dem answers each call with the next outcome; an
    Exception is raised instead. Returns the call log."""
    exc = types.ModuleType("py3dep.exceptions")

    class ServiceUnavailableError(Exception):
        pass

    class InputValueError(Exception):
        pass
    exc.ServiceUnavailableError = ServiceUnavailableError
    exc.InputValueError = InputValueError
    mod = types.ModuleType("py3dep")
    mod.exceptions = exc
    calls = []

    def get_dem(bbox, resolution):
        calls.append((bbox, resolution))
        out = outcomes[len(calls) - 1]
        if isinstance(out, BaseException):
            raise out
        return out
    mod.get_dem = get_dem
    monkeypatch.setitem(sys.modules, "py3dep", mod)
    monkeypatch.setitem(sys.modules, "py3dep.exceptions", exc)
    return mod, calls


@pytest.fixture
def waits(monkeypatch):
    seen = []
    monkeypatch.setattr(rp, "_sleep", seen.append)
    return seen


def test_fetch_dem_retries_a_service_outage(monkeypatch, waits, capsys):
    outcomes = []
    mod, calls = _fake_py3dep(monkeypatch, outcomes)
    busy = mod.exceptions.ServiceUnavailableError("Service is currently not available")
    outcomes += [busy, busy, "dem"]
    assert rp.fetch_dem((0, 0, 1, 1), 35) == "dem"
    assert len(calls) == 2 + 1 and waits == list(rp._RETRY_WAITS) == [60, 180]
    out = capsys.readouterr().out
    assert "3DEP busy, retrying in 60 s" in out and "3DEP busy, retrying in 180 s" in out


def test_fetch_dem_gives_up_after_two_retries(monkeypatch, waits):
    errs = [TimeoutError("timed out")] * 3
    _, calls = _fake_py3dep(monkeypatch, errs)
    with pytest.raises(TimeoutError):
        rp.fetch_dem((0, 0, 1, 1), 35)
    assert len(calls) == 3 and waits == [60, 180]


@pytest.mark.parametrize("make_err", [
    lambda: ConnectionResetError(54, "Connection reset by peer"),
    lambda: TimeoutError("The read operation timed out"),
    lambda: OSError("network is unreachable"),
])
def test_fetch_dem_retries_network_errors(monkeypatch, waits, make_err):
    _, calls = _fake_py3dep(monkeypatch, [make_err(), "dem"])
    assert rp.fetch_dem((0, 0, 1, 1), 10) == "dem"
    assert waits == [60]


def test_fetch_dem_retries_an_aiohttp_disconnect(monkeypatch, waits):
    aio = types.ModuleType("aiohttp")

    class ClientError(Exception):
        pass

    class ServerDisconnectedError(ClientError):
        pass
    aio.ClientError = ClientError
    monkeypatch.setitem(sys.modules, "aiohttp", aio)
    _, calls = _fake_py3dep(monkeypatch, [ServerDisconnectedError("Server disconnected"),
                                          "dem"])
    assert rp.fetch_dem((0, 0, 1, 1), 10) == "dem"
    assert waits == [60]


def test_fetch_dem_collapses_a_multiline_error_into_one_retry_line(monkeypatch, waits,
                                                                   capsys):
    # an XML/HTML error body wrapped in an exception message must not break the
    # single-line retry log into several ragged lines
    err = TimeoutError("Service is\n  currently\tnot available\n\nplease retry")
    _, calls = _fake_py3dep(monkeypatch, [err, "dem"])
    assert rp.fetch_dem((0, 0, 1, 1), 10) == "dem"
    out = capsys.readouterr().out
    lines = [l for l in out.splitlines() if "retrying" in l]
    assert len(lines) == 1
    assert "\n" not in lines[0] and "\t" not in lines[0]
    assert "Service is currently not available please retry" in lines[0]


def test_with_retries_disables_the_hyriver_cache_only_on_a_retry(monkeypatch, waits):
    seen = []

    def fetch():
        seen.append(os.environ.get("HYRIVER_CACHE_DISABLE"))
        if len(seen) < 2:
            raise TimeoutError("busy")
        return "ok"
    assert rp.with_retries(fetch, "3DEP") == "ok"
    assert seen == [None, "true"]
    assert os.environ.get("HYRIVER_CACHE_DISABLE") is None


def test_with_retries_restores_a_prior_cache_disable_value(monkeypatch, waits):
    monkeypatch.setenv("HYRIVER_CACHE_DISABLE", "false")
    seen = []

    def fetch():
        seen.append(os.environ.get("HYRIVER_CACHE_DISABLE"))
        if len(seen) < 3:
            raise TimeoutError("busy")
        return "ok"
    assert rp.with_retries(fetch, "3DEP") == "ok"
    assert seen == ["false", "true", "true"]
    assert os.environ.get("HYRIVER_CACHE_DISABLE") == "false"


def test_with_retries_restores_the_cache_flag_even_when_every_attempt_fails(monkeypatch,
                                                                            waits):
    def fetch():
        raise TimeoutError("still busy")
    with pytest.raises(TimeoutError):
        rp.with_retries(fetch, "3DEP")
    assert os.environ.get("HYRIVER_CACHE_DISABLE") is None


@pytest.mark.parametrize("make_err", [
    lambda: ValueError("bad bbox"),
    lambda: FileNotFoundError("no such cache file"),
    lambda: sys.modules["py3dep"].exceptions.InputValueError("resolution"),
])
def test_fetch_dem_raises_a_lasting_error_at_once(monkeypatch, waits, make_err):
    outcomes = []
    _, calls = _fake_py3dep(monkeypatch, outcomes)
    err = make_err()
    outcomes += [err, "dem"]
    with pytest.raises(type(err)):
        rp.fetch_dem((0, 0, 1, 1), 10)
    assert len(calls) == 1 and waits == []


# ---- NLCD goes through the same retry (acceptance: "Server disconnected") ----
def _fake_nlcd(monkeypatch, outcomes):
    gpd = types.ModuleType("geopandas")
    gpd.GeoSeries = lambda geoms, crs: ("series", crs)
    ph = types.ModuleType("pygeohydro")
    calls = []

    def nlcd_bygeom(geom, resolution, years):
        calls.append((geom, resolution, years))
        out = outcomes[len(calls) - 1]
        if isinstance(out, BaseException):
            raise out
        return out
    ph.nlcd_bygeom = nlcd_bygeom
    monkeypatch.setitem(sys.modules, "geopandas", gpd)
    monkeypatch.setitem(sys.modules, "pygeohydro", ph)
    return calls


def test_nlcd_fetch_retries_a_disconnect(monkeypatch, waits, capsys):
    calls = _fake_nlcd(monkeypatch, [ConnectionResetError("Server disconnected"),
                                     TimeoutError("timed out"), {"cover": "ds"}])
    assert rp._fetch_nlcd((0, 0, 1, 1), 30, 2021) == {"cover": "ds"}
    assert len(calls) == 3 and waits == [60, 180]
    assert calls[0][1:] == (30, {"cover": [2021]})
    assert "NLCD busy, retrying in 60 s" in capsys.readouterr().out


def test_nlcd_fetch_raises_after_the_retries(monkeypatch, waits):
    calls = _fake_nlcd(monkeypatch, [TimeoutError("timed out")] * 3)
    with pytest.raises(TimeoutError):
        rp._fetch_nlcd((0, 0, 1, 1), 30, 2021)
    assert len(calls) == 3


# ---- hole fill: the dynamic service can return empty tiles and say nothing
# (acceptance, 2026-09-24: 12.1% of the east-west plate was NaN where ~5.6% is ocean
# or Canada). build_dem_cog fills them from the static 3DEP tiles, window by window.
# The static source here is a local EPSG:4269 raster, never the network. ----
import json

import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

FIX_W, FIX_N, FIX_RES = -116.6, 36.25, 0.001        # ~100 m source cells
FIX_COLS, FIX_ROWS = 1200, 700                       # lon -116.6..-115.4, lat 35.55..36.25
OCEAN_LON = -116.3                                   # the source holds nothing west of it
GRID_CRS = "EPSG:32611"
GRID_T = from_origin(550000.0, 4000000.0, 250.0, 250.0)
GRID_W, GRID_H, GRID_BLOCK = 300, 200, 128           # 3 x 2 blocks
OCEAN_COLS = 20                                      # x < 555 km: lon < -116.39
HOLE = (slice(40, 160), slice(150, 240))             # rows, cols: land, 2 blocks


def _elev(lon, lat):
    """A plane: average and bilinear both reproduce it, so a fill is checkable."""
    return 1000.0 + 200.0 * (lon + 117.0) + 100.0 * (lat - 35.0)


def _static_fixture(path):
    lon = FIX_W + FIX_RES * (np.arange(FIX_COLS) + 0.5)
    lat = FIX_N - FIX_RES * (np.arange(FIX_ROWS) + 0.5)
    arr = _elev(lon[None, :], lat[:, None]).astype("float32")
    arr[:, lon < OCEAN_LON] = -999999.0
    with rasterio.open(path, "w", driver="GTiff", dtype="float32", count=1,
                       width=FIX_COLS, height=FIX_ROWS, crs="EPSG:4269",
                       transform=from_origin(FIX_W, FIX_N, FIX_RES, FIX_RES),
                       nodata=-999999.0) as ds:
        ds.write(arr, 1)
    return path


def _grid_truth():
    cols, rows = np.meshgrid(np.arange(GRID_W) + 0.5, np.arange(GRID_H) + 0.5)
    xs, ys = GRID_T * (cols, rows)
    lon, lat = Transformer.from_crs(GRID_CRS, "EPSG:4269", always_xy=True).transform(xs, ys)
    return _elev(lon, lat).astype("float32")


def _holed_grid(path):
    truth = _grid_truth()
    arr = truth.copy()
    arr[:, :OCEAN_COLS] = np.nan
    arr[HOLE] = np.nan
    with rasterio.open(path, "w", driver="GTiff", dtype="float32", count=1,
                       width=GRID_W, height=GRID_H, crs=GRID_CRS, transform=GRID_T,
                       nodata=np.nan, tiled=True, blockxsize=GRID_BLOCK,
                       blockysize=GRID_BLOCK) as ds:
        ds.write(arr, 1)
    return truth, arr


class _Spy:
    """A dataset stand-in that records every read() and forwards the rest."""
    def __init__(self, ds):
        self._ds, self.reads = ds, []

    def read(self, *a, **kw):
        self.reads.append(kw.get("window"))
        return self._ds.read(*a, **kw)

    def __getattr__(self, name):
        return getattr(self._ds, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._ds.close()


@pytest.fixture
def static_src(tmp_path):
    path = _static_fixture(str(tmp_path / "static.tif"))
    opened = []

    def open_static(layer_m):
        spy = _Spy(rasterio.open(path))
        opened.append((layer_m, spy))
        return spy
    open_static.opened = opened
    return open_static


def test_fill_fills_a_land_hole_and_leaves_the_ocean_nan(tmp_path, static_src, capsys):
    path = str(tmp_path / "dem.tif")
    truth, before = _holed_grid(path)
    with rasterio.open(path, "r+") as dst:
        fill = rp.fill_dem_holes(dst, 250.0, open_static=static_src)
    with rasterio.open(path) as ds:
        after = ds.read(1)
    assert not np.isnan(after[HOLE]).any(), "the land hole must be filled"
    assert np.abs(after[HOLE] - truth[HOLE]).max() < 2.0
    assert np.isnan(after[:, :OCEAN_COLS]).all(), "ocean stays NaN: the tiles hold none"
    kept = ~np.isnan(before)
    assert np.array_equal(after[kept], before[kept]), "finite cells are never touched"
    hole_px = truth[HOLE].size
    total = GRID_W * GRID_H
    assert fill["layer_m"] == 30
    assert fill["filled_px"] == hole_px
    assert fill["filled_share"] == pytest.approx(hole_px / total)
    assert fill["holes_share"] == pytest.approx((hole_px + OCEAN_COLS * GRID_H) / total)
    assert fill["left_share"] == pytest.approx(OCEAN_COLS * GRID_H / total)
    assert fill["stopped"] is None
    out = capsys.readouterr().out
    assert (f"Filled {hole_px / total:.1%} of the plate from the 3DEP 30 m tiles "
            "(the dynamic service left holes)") in out


def test_fill_works_block_by_block_and_reads_the_tiles_only_where_holed(
        tmp_path, static_src):
    path = str(tmp_path / "dem.tif")
    _holed_grid(path)
    with rasterio.open(path, "r+") as ds:
        spy = _Spy(ds)
        rp.fill_dem_holes(spy, 250.0, open_static=static_src)
    # never the whole grid at once: every read of the plate is one block or less
    assert spy.reads and all(w is not None for w in spy.reads)
    assert all(w.width <= GRID_BLOCK and w.height <= GRID_BLOCK for w in spy.reads)
    # 4 of the 6 blocks hold NaN (2 ocean, 2 hole); the other 2 cost no tile read
    assert len(static_src.opened) == 1, "the static layer is opened once"
    assert len(static_src.opened[0][1].reads) == 4


def test_fill_touches_nothing_and_opens_nothing_on_a_plate_without_holes(
        tmp_path, static_src, capsys):
    path = str(tmp_path / "dem.tif")
    truth = _grid_truth()
    with rasterio.open(path, "w", driver="GTiff", dtype="float32", count=1,
                       width=GRID_W, height=GRID_H, crs=GRID_CRS, transform=GRID_T,
                       nodata=np.nan, tiled=True, blockxsize=GRID_BLOCK,
                       blockysize=GRID_BLOCK) as ds:
        ds.write(truth, 1)
    with rasterio.open(path, "r+") as dst:
        fill = rp.fill_dem_holes(dst, 250.0, open_static=static_src)
    assert static_src.opened == []
    assert fill["filled_px"] == 0 and fill["holes_share"] == 0.0
    assert "Filled" not in capsys.readouterr().out


def test_a_failed_fill_keeps_the_plate_and_says_so(tmp_path, waits, capsys):
    path = str(tmp_path / "dem.tif")
    _, before = _holed_grid(path)

    def down(layer_m):
        raise rasterio.errors.RasterioIOError("HTTP response code: 503")
    with rasterio.open(path, "r+") as dst:
        fill = rp.fill_dem_holes(dst, 250.0, open_static=down)
    with rasterio.open(path) as ds:
        after = ds.read(1)
    assert np.array_equal(np.isnan(after), np.isnan(before))
    assert waits == [60, 180], "the tiles get the same retries as every fetch"
    assert fill["filled_px"] == 0 and "503" in fill["stopped"]
    assert "Hole fill stopped" in capsys.readouterr().out


@pytest.mark.parametrize("grid_m,layer_m", [(210.0, 30), (30.5, 30), (25.0, 10),
                                            (4.0, 10), (1.5, 10)])
def test_fill_layer_is_30_m_from_a_30_m_grid_up_else_10_m(grid_m, layer_m):
    assert rp.fill_layer_m(grid_m) == layer_m


@pytest.mark.parametrize("src_m,grid_m,decimate,resampling", [
    (30.9, 210.0, 4, "average"),     # 1 arc-second onto the east-west grid: overview 4
    (30.9, 1000.0, 16, "average"),
    (10.3, 25.0, 1, "average"),      # finer than the grid, too close to decimate
    (30.9, 45.0, 1, "average"),
    (10.3, 4.0, 1, "bilinear"),      # coarser than the grid
])
def test_fill_sampling_decimates_to_the_tiles_overviews_but_stays_finer(
        src_m, grid_m, decimate, resampling):
    d, r = rp.fill_sampling(src_m, grid_m)
    assert (d, r.name) == (decimate, resampling)
    assert src_m * d * rp.FILL_MIN_SAMPLES <= grid_m or d == 1


def test_static_layer_urls_are_the_ones_py3dep_reads():
    base = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation"
    assert rp.STATIC_LAYER_URLS == {10: f"{base}/13/TIFF/USGS_Seamless_DEM_13.vrt",
                                    30: f"{base}/1/TIFF/USGS_Seamless_DEM_1.vrt"}


# build_dem_cog end to end, with a fake dynamic fetch that leaves a hole
DYN_BBOX = (-116.25, 35.75, -115.8, 36.1)


class _FakeDA:
    def __init__(self, bbox, hole=True):
        w, s, e, n = bbox
        res = 0.002
        cols, rows = int(round((e - w) / res)), int(round((n - s) / res))
        lon = w + res * (np.arange(cols) + 0.5)
        lat = n - res * (np.arange(rows) + 0.5)
        self.values = _elev(lon[None, :], lat[:, None]).astype("float32")
        if hole:
            self.values[rows // 3: rows // 2, cols // 3: cols // 2] = np.nan
        t = from_origin(w, n, res, res)
        self.rio = types.SimpleNamespace(transform=lambda: t,
                                         crs=rasterio.crs.CRS.from_epsg(4326))


def test_build_dem_cog_fills_a_dynamic_grid(tmp_path, monkeypatch, static_src):
    monkeypatch.setattr(rp, "fetch_dem", lambda sb, res: _FakeDA(sb))
    plan = rp.plan_build(DYN_BBOX, GRID_CRS, 250.0)
    assert plan["dynamic"]
    out = str(tmp_path / "dem.tif")
    path, fill = rp.build_dem_cog(DYN_BBOX, GRID_CRS, out, plan, open_static=static_src)
    assert path == out
    assert fill["filled_px"] > 0 and fill["layer_m"] == 30
    with rasterio.open(out) as ds:
        assert not np.isnan(ds.read(1)).any()
        assert ds.overviews(1) == [2, 4, 8, 16, 32], "overviews see the filled grid"


def test_build_dem_cog_leaves_a_static_grid_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "fetch_dem", lambda sb, res: _FakeDA(sb))

    def never(layer_m):
        raise AssertionError("a static grid is never filled")
    plan = rp.plan_build(DYN_BBOX, GRID_CRS, 30)
    assert not plan["dynamic"]
    out = str(tmp_path / "dem.tif")
    path, fill = rp.build_dem_cog(DYN_BBOX, GRID_CRS, out, plan, open_static=never)
    assert fill is None
    with rasterio.open(out) as ds:
        assert np.isnan(ds.read(1)).any(), "the hole stays: static tiles are the source"


def test_sources_manifest_records_a_hole_fill(tmp_path):
    fill = {"layer_m": 30, "filled_px": 64, "filled_share": 0.06413, "stopped": None}
    m = rp.write_sources_manifest(str(tmp_path), "order_y", (-116.3, 35.8, -116.2, 35.9),
                                  "EPSG:5070", built="2026-09-24", resolution_m=210.0,
                                  fill=fill)
    assert m["sources"][0]["dataset"] == "USGS 3DEP dynamic service, 210 m"
    fills = [s for s in m["sources"] if s.get("role") == "hole fill"]
    assert len(fills) == 1
    f = fills[0]
    assert f["layer_m"] == 30 and f["filled_share"] == pytest.approx(0.0641, abs=1e-4)
    assert "USGS 3DEP 30 m" in f["dataset"] and "USGS_Seamless_DEM_1.vrt" in f["via"]
    assert f["license"] == "Public domain (USGS)"
    on_disk = json.load(open(tmp_path / "sources.json"))
    assert on_disk["sources"] == m["sources"]


@pytest.mark.parametrize("fill", [None, {"layer_m": 30, "filled_px": 0,
                                         "filled_share": 0.0, "stopped": None}])
def test_sources_manifest_records_no_fill_when_nothing_was_filled(tmp_path, fill):
    m = rp.write_sources_manifest(str(tmp_path), "order_y", (-116.3, 35.8, -116.2, 35.9),
                                  "EPSG:5070", built="2026-09-24", resolution_m=210.0,
                                  fill=fill)
    assert len(m["sources"]) == 3
    assert not any(s.get("role") == "hole fill" for s in m["sources"])
