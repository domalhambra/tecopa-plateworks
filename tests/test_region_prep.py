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
    plan = rp.plan_build(CORRIDOR, "EPSG:32611", resolution_m=45.6)
    assert plan["landcover_resolution_m"] == 46


def test_explicit_30m_resolution_bakes_30m_landcover():
    plan = rp.plan_build(CORRIDOR, "EPSG:32611", resolution_m=30)
    assert plan["landcover_resolution_m"] == 30


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
