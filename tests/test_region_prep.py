# tests/test_region_prep.py
# The build planner: resolution auto-selection, memory-bounding slice counts, and
# grid geometry -- all pure logic (pyproj + numpy, no fetch stack), so the guard
# against another 15.8 GB accidental build runs in the core CI env.
import os

import numpy as np
import pytest
rp = pytest.importorskip("region_prep")
from scipy.ndimage import gaussian_filter  # noqa: E402

from scripts import stripe_check  # noqa: E402

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


# ---- the auto planner's coarsest choice: the static 60 m tiles
# (USGS_Seamless_DEM_2.vrt) cover Alaska only, so a 60 m auto pick anywhere else
# would fetch an empty DEM ----

# ~470 x 445 km of the Great Basin, inside CONUS: 30 m is ~246 Mpx, over
# GRID_BUDGET_MPX, so the auto planner reaches its coarsest choice
GREAT_BASIN = (-120.0, 36.0, -114.5, 40.0)
# ~490 x 445 km of interior Alaska, inside the 60 m tiles: 30 m is ~271 Mpx
INTERIOR_ALASKA = (-155.0, 62.0, -145.0, 66.0)


def test_auto_steps_60m_down_to_55m_outside_the_alaska_tiles():
    plan = rp.plan_build(GREAT_BASIN, "EPSG:32611")
    assert plan["auto"] and plan["resolution_m"] == 55
    assert plan["dynamic"] is True      # served by the dynamic service, holes filled
    assert not plan["over_budget"]


def test_auto_still_picks_60m_inside_the_alaska_tiles():
    # control: where the 60 m tiles exist, the planner keeps them
    plan = rp.plan_build(INTERIOR_ALASKA, "EPSG:32606")
    assert plan["auto"] and plan["resolution_m"] == 60
    assert plan["dynamic"] is False


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


# ---- a tile that comes back unreadable is retried like a busy service ----

class RasterioIOError(OSError):
    """Stands in for rasterio.errors.RasterioIOError (an OSError subclass)."""


class CPLE_OpenFailedError(Exception):
    """Stands in for rasterio._err.CPLE_OpenFailedError (not an OSError)."""


_BAD_TILE = "'/vsimem/abc123.tif' not recognized as being in a supported file format."


def _wrapped_in_service_error(mod, cause):
    """What py3dep raises: ServiceUnavailableError, with the rasterio error as cause."""
    try:
        try:
            raise cause
        except Exception as inner:
            raise mod.exceptions.ServiceUnavailableError("Service is currently not "
                                                         "available") from inner
    except Exception as outer:
        return outer


@pytest.mark.parametrize("make_err", [
    lambda mod: CPLE_OpenFailedError(_BAD_TILE),
    lambda mod: RasterioIOError(_BAD_TILE),
    lambda mod: _wrapped_in_service_error(mod, CPLE_OpenFailedError(_BAD_TILE)),
    lambda mod: _wrapped_in_service_error(mod, RasterioIOError(_BAD_TILE)),
    # the rasterio error only in __context__ (raised while handling it, no "from")
    lambda mod: _context_only(CPLE_OpenFailedError(_BAD_TILE)),
    # unknown class, but GDAL's own words, wrapped
    lambda mod: _wrapped_in_service_error(mod, RuntimeError(_BAD_TILE)),
], ids=["cple", "rasterio", "wrapped-cple", "wrapped-rasterio", "context", "text-only"])
def test_fetch_dem_retries_an_unreadable_tile(monkeypatch, waits, capsys, make_err):
    outcomes = []
    mod, calls = _fake_py3dep(monkeypatch, outcomes)
    outcomes += [make_err(mod), "dem"]
    assert rp.fetch_dem((0, 0, 1, 1), 10) == "dem"
    assert len(calls) == 2 and waits == [60]
    assert "retrying in 60 s" in capsys.readouterr().out


def _context_only(cause):
    try:
        try:
            raise cause
        except Exception:
            raise ValueError("could not open the tile")      # no "from": __context__ only
    except ValueError as e:
        return e


def test_fetch_dem_gives_up_on_an_unreadable_tile_after_the_cap(monkeypatch, waits):
    outcomes = []
    mod, calls = _fake_py3dep(monkeypatch, outcomes)
    errs = [_wrapped_in_service_error(mod, CPLE_OpenFailedError(_BAD_TILE))
            for _ in range(3)]
    outcomes += errs
    with pytest.raises(mod.exceptions.ServiceUnavailableError) as e:
        rp.fetch_dem((0, 0, 1, 1), 10)
    assert e.value is errs[-1]                       # the original error, not a wrapper
    assert isinstance(e.value.__cause__, CPLE_OpenFailedError)
    assert len(calls) == 3 and waits == list(rp._RETRY_WAITS) == [60, 180]


def test_an_unreadable_tile_retry_reads_the_service_fresh(monkeypatch, waits):
    seen = []

    def fetch():
        seen.append(os.environ.get("HYRIVER_CACHE_DISABLE"))
        if len(seen) < 2:
            raise CPLE_OpenFailedError(_BAD_TILE)
        return "ok"
    assert rp.with_retries(fetch, "3DEP") == "ok"
    assert seen == [None, "true"] and os.environ.get("HYRIVER_CACHE_DISABLE") is None


@pytest.mark.parametrize("make_err", [
    lambda: ValueError("bad bbox"),
    lambda: KeyError("band"),
    lambda: FileNotFoundError("no such cache file"),
    lambda: RuntimeError("not a tile problem"),
    lambda: _context_only(KeyError("band")),
])
def test_an_unrelated_error_is_not_retried(waits, make_err):
    calls = []

    def fetch():
        calls.append(1)
        raise make_err()
    with pytest.raises(Exception):
        rp.with_retries(fetch, "3DEP")
    assert len(calls) == 1 and waits == []


@pytest.mark.parametrize("make_err", [
    # real error shapes from rasterio/GDAL that are not an unreadable tile
    lambda mod: RasterioIOError("/data/x.tif: No such file or directory"),
    lambda mod: CPLE_OpenFailedError("'/data/x.tif' does not exist in the file system, "
                                     "and is not recognised as a supported dataset name."),
    lambda mod: CPLE_OpenFailedError("/data/x.tif: Permission denied"),
    lambda mod: RasterioIOError("HTTP response code: 404"),
    lambda mod: _wrapped_in_service_error(mod, CPLE_OpenFailedError("x.tif: Permission denied")),
], ids=["no-such-file", "not-recognised-name", "permission", "http-404", "wrapped-permission"])
def test_a_rasterio_open_error_that_is_not_a_bad_tile_is_not_retried(monkeypatch, waits,
                                                                     make_err):
    outcomes = []
    mod, calls = _fake_py3dep(monkeypatch, outcomes)
    err = make_err(mod)
    if isinstance(err, mod.exceptions.ServiceUnavailableError):
        # a busy service is retried whatever caused it; only the bare errors are lasting
        outcomes += [err, "dem"]
        assert rp.fetch_dem((0, 0, 1, 1), 10) == "dem"
        return
    outcomes += [err, "dem"]
    with pytest.raises(type(err)):
        rp.fetch_dem((0, 0, 1, 1), 10)
    assert len(calls) == 1 and waits == []


def test_a_rasterio_network_error_is_still_retried(waits):
    seen = []

    def fetch():
        seen.append(1)
        if len(seen) < 2:
            raise RasterioIOError("CURL error: Connection reset by peer")
        return "ok"
    assert rp.with_retries(fetch, "3DEP") == "ok" and waits == [60]


@pytest.mark.parametrize("lasting", [PermissionError, FileNotFoundError])
def test_a_lasting_os_error_is_never_retried_even_with_a_bad_tile_cause(waits, lasting):
    calls = []

    def fetch():
        calls.append(1)
        try:
            raise CPLE_OpenFailedError(_BAD_TILE)
        except CPLE_OpenFailedError as cause:
            raise lasting("cannot read the tile") from cause
    with pytest.raises(lasting):
        rp.with_retries(fetch, "3DEP")
    assert len(calls) == 1 and waits == []


def test_a_cyclic_exception_chain_does_not_hang_the_check():
    a, b = ValueError("a"), ValueError("b")
    a.__context__, b.__context__ = b, a
    assert rp._is_unreadable_tile(a) is False


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
                                    30: f"{base}/1/TIFF/USGS_Seamless_DEM_1.vrt",
                                    60: f"{base}/2/TIFF/USGS_Seamless_DEM_2.vrt"}


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


# The static layers are read natively and warped with Lanczos: going through py3dep's
# nearest-neighbour Albers grid, or warping with bilinear, leaves stripes
# (docs/superpowers/plans/2026-11-01-dem-lanczos-resampling.md).
NAT_BBOX = (-106.85, 39.10, -106.79, 39.15)
NAT_CRS = "EPSG:32613"
NAT_RES = 1 / 10800                                  # 1/3 arc-second
NAT_MARGIN = 0.04
NAT_HOLE = (slice(800, 1000), slice(800, 1000))      # rows, cols of the source


def _native_terrain(rows, cols):
    """Steep, smooth ground with a noise floor like real 3DEP (a median slope near the
    plates', fine detail of about 3 m, sensor noise of about 0.2 m). A resampling
    pattern scales with the slope, so white noise alone would hide it, and the score
    reads against the floor, so ground with no noise would flag any faint residual."""
    r = np.random.default_rng(3)
    y, x = np.indices((rows, cols), dtype="float32")
    a = 0.35 * 8 * x + 0.35 * 10 * y
    for s, amp in ((12, 600.0), (24, 1800.0), (48, 6000.0), (2, 3.0)):
        a += gaussian_filter(r.standard_normal((rows, cols)), s) * amp
    return (2800.0 + a + r.standard_normal((rows, cols)) * 0.2).astype("float32")


def _native_source(path, hole=False):
    w, s, e, n = NAT_BBOX
    w, s, e, n = w - NAT_MARGIN, s - NAT_MARGIN, e + NAT_MARGIN, n + NAT_MARGIN
    cols, rows = int((e - w) / NAT_RES), int((n - s) / NAT_RES)
    arr = _native_terrain(rows, cols)
    if hole:
        arr[NAT_HOLE] = -999999.0
    with rasterio.open(path, "w", driver="GTiff", dtype="float32", count=1, width=cols,
                       height=rows, crs="EPSG:4269",
                       transform=from_origin(w, n, NAT_RES, NAT_RES),
                       nodata=-999999.0) as ds:
        ds.write(arr, 1)
    return path


@pytest.fixture(scope="module")
def native_tif(tmp_path_factory):
    return _native_source(str(tmp_path_factory.mktemp("native") / "src.tif"))


@pytest.fixture(scope="module")
def holed_tif(tmp_path_factory):
    return _native_source(str(tmp_path_factory.mktemp("holed") / "src.tif"), hole=True)


def _opener(path):
    return lambda layer_m: rasterio.open(path)


def _build(tmp_path, tif, res=10, n_slices=None, name="dem.tif"):
    plan = dict(rp.plan_build(NAT_BBOX, NAT_CRS, res))
    if n_slices:
        plan["n_slices"] = n_slices
    out = str(tmp_path / name)
    return (*rp.build_dem_cog(NAT_BBOX, NAT_CRS, out, plan, open_static=_opener(tif)), plan)


def test_the_static_chain_control_goes_red(native_tif):
    # py3dep's chain, by hand: this is the proof the fixture can catch the bug.
    from rasterio.warp import reproject
    plan = rp.plan_build(NAT_BBOX, NAT_CRS, 10)
    with rasterio.open(native_tif) as src:
        arr = src.read(1)
        from rasterio.warp import transform_bounds
        l, b, r, t = transform_bounds(src.crs, "EPSG:5070", *src.bounds)
        albers_t = from_origin(l, t, 8.84, 8.84)
        albers = np.full((int((t - b) / 8.84), int((r - l) / 8.84)), np.nan, "float32")
        reproject(arr, albers, src_transform=src.transform, src_crs=src.crs,
                  dst_transform=albers_t, dst_crs="EPSG:5070", dst_nodata=np.nan,
                  resampling=rp.Resampling.nearest)
    w, h = plan["grid"]
    out = np.full((h, w), np.nan, "float32")
    reproject(albers, out, src_transform=albers_t, src_crs="EPSG:5070", src_nodata=np.nan,
              dst_transform=plan["transform"], dst_crs=NAT_CRS, dst_nodata=np.nan,
              resampling=rp.Resampling.bilinear)
    assert stripe_check.peaks(out, 10, 10)[0]["score"] >= stripe_check.STRIPE_RED_SCORE


def test_build_dem_cog_static_grid_has_no_stripes(tmp_path, native_tif):
    path, _, _ = _build(tmp_path, native_tif)
    with rasterio.open(path) as ds:
        top = stripe_check.peaks(ds.read(1), 10, 10)[0]
    assert top["score"] < stripe_check.STRIPE_RED_SCORE


def test_build_dem_cog_static_never_calls_py3dep(tmp_path, monkeypatch, native_tif):
    def boom(*a):
        raise AssertionError("a static grid does not go through py3dep")
    monkeypatch.setattr(rp, "fetch_dem", boom)
    assert _build(tmp_path, native_tif)[1] is None


def test_slices_match_one_slice_at_their_seams(tmp_path, native_tif):
    # Three slices: with two on a bbox this narrow, the second one's overlap spans the
    # whole grid and there is no seam. A slice's window is the projected bounding box of
    # a curved lon/lat box, so a read that follows the lon/lat box stops short of it, and
    # the later slice writes values with a cut-off kernel over good ones. The tolerance
    # is GDAL's approximate transformer, about 0.07 m between chunkings.
    one, _, _ = _build(tmp_path, native_tif, n_slices=1, name="one.tif")
    three, _, _ = _build(tmp_path, native_tif, n_slices=3, name="three.tif")
    with rasterio.open(one) as a, rasterio.open(three) as b:
        assert np.nanmax(np.abs(a.read(1) - b.read(1))) <= 0.1


def test_native_read_runs_with_the_gdal_http_settings(waits, native_tif):
    seen = []

    def spy(layer_m):
        seen.append(rasterio.env.getenv())
        return rasterio.open(native_tif)
    rp.read_static_native(NAT_BBOX, "EPSG:4326", 10, open_static=spy)
    for key, value in rp.STATIC_GDAL_ENV.items():
        assert str(seen[0][key]) == str(value)


def test_native_read_keeps_nodata_as_nan_without_a_spike(tmp_path, holed_tif):
    path, _, _ = _build(tmp_path, holed_tif)
    with rasterio.open(holed_tif) as src:
        arr = src.read(1)
        lo, hi = arr[arr > -1000].min(), arr[arr > -1000].max()
        # the middle of the source hole, in the grid's coordinates
        lon, lat = src.xy(900, 900)
    from pyproj import Transformer
    x, y = Transformer.from_crs("EPSG:4269", NAT_CRS, always_xy=True).transform(lon, lat)
    with rasterio.open(path) as ds:
        out = ds.read(1)
        row, col = ds.index(x, y)
    assert np.isnan(out[row - 20:row + 20, col - 20:col + 20]).all()
    assert np.nanmin(out) >= lo - 5 and np.nanmax(out) <= hi + 5


def test_a_static_grid_keeps_its_hole(tmp_path, monkeypatch, holed_tif):
    def never(*a, **k):
        raise AssertionError("a static grid is never filled")
    monkeypatch.setattr(rp, "fill_dem_holes", never)
    path, fill, _ = _build(tmp_path, holed_tif, res=30)
    assert fill is None
    with rasterio.open(path) as ds:
        assert np.isnan(ds.read(1)).any(), "the hole stays: static tiles are the source"


def test_native_read_retries_a_dropped_connection(waits, native_tif):
    calls = []

    def flaky(layer_m):
        calls.append(layer_m)
        if len(calls) == 1:
            raise TimeoutError("timed out")
        return rasterio.open(native_tif)
    arr, _, crs = rp.read_static_native(NAT_BBOX, "EPSG:4326", 10, open_static=flaky)
    assert waits == [60] and calls == [10, 10]
    assert arr.dtype == np.float32 and crs.to_epsg() == 4269


def test_native_read_raises_a_lasting_error_at_once(waits):
    def missing(layer_m):
        raise rasterio.errors.RasterioIOError("x.vrt: No such file or directory")
    with pytest.raises(rasterio.errors.RasterioIOError):
        rp.read_static_native(NAT_BBOX, "EPSG:4326", 10, open_static=missing)
    assert waits == []


def test_native_read_pads_past_the_lanczos_kernel(native_tif):
    arr, t, _ = rp.read_static_native(NAT_BBOX, "EPSG:4326", 10, open_static=_opener(native_tif))
    assert t.c <= NAT_BBOX[0] - 3 * NAT_RES and t.f >= NAT_BBOX[3] + 3 * NAT_RES


def test_native_read_covers_a_projected_window(native_tif):
    # The corners of a UTM window lie outside the lon/lat box of its edges' midlines.
    plan = rp.plan_build(NAT_BBOX, NAT_CRS, 10)
    w, h = plan["grid"]
    t = plan["transform"]
    bounds = (t.c, t.f - h * 10, t.c + w * 10, t.f)
    _, st, _ = rp.read_static_native(bounds, NAT_CRS, 10, open_static=_opener(native_tif))
    corners = Transformer.from_crs(NAT_CRS, "EPSG:4326", always_xy=True).transform(
        [bounds[0], bounds[0]], [bounds[1], bounds[3]])
    assert st.c <= min(corners[0]) - 3 * NAT_RES


@pytest.mark.parametrize("res,via", [
    (10, "rasterio, USGS_Seamless_DEM_13.vrt"),
    (30, "rasterio, USGS_Seamless_DEM_1.vrt"),
    (35, "py3dep.get_dem"),
])
def test_sources_manifest_names_the_read(tmp_path, res, via):
    rp.write_sources_manifest(str(tmp_path), "x", DYN_BBOX, GRID_CRS, built="2026-11-01",
                              resolution_m=res)
    with open(tmp_path / "sources.json") as f:
        assert json.load(f)["sources"][0]["via"] == via


def test_build_dem_cog_warps_every_path_with_the_same_resampling(tmp_path, monkeypatch,
                                                                 static_src):
    # On a 5 m dynamic grid py3dep is clean (7.1) and a bilinear warp scores 57.
    import rasterio.warp as warp
    seen, real = [], warp.reproject

    def spy(*a, **k):
        seen.append(k["resampling"])
        return real(*a, **k)
    monkeypatch.setattr(warp, "reproject", spy)
    monkeypatch.setattr(rp, "fetch_dem", lambda sb, res: _FakeDA(sb))
    plan = rp.plan_build(DYN_BBOX, GRID_CRS, 250.0)
    rp.build_dem_cog(DYN_BBOX, GRID_CRS, str(tmp_path / "dem.tif"), plan,
                     open_static=static_src)
    assert seen[0] == rp.DEM_WARP_RESAMPLING

