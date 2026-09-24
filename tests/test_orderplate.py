# tests/test_orderplate.py
# Plate planning for one order: the spec's sections 2 and 3 as pure functions.
import pytest

from app import orderplate as op

TECOPA = (-116.3, 35.8, -116.1, 36.0)
# The static 60 m 3DEP tiles cover Alaska only: the index reads 0.0 for 60 m
# everywhere in the lower 48, even on ground with full 1 m lidar.
LIDAR = {1: 1.0, 3: 0.0, 10: 1.0, 30: 1.0, 60: 0.0}
NO_LIDAR = {1: 0.0, 3: 0.0, 10: 1.0, 30: 1.0, 60: 0.0}
PORTRAIT = 12 / 18
LANDSCAPE = 18 / 12


def test_conus_only():
    assert op.conus_covered(TECOPA)
    assert not op.conus_covered((-150.1, 61.1, -149.7, 61.3))     # Anchorage
    assert not op.conus_covered((-123.5, 48.8, -122.5, 49.8))     # over the border


def test_order_epsg_utm_then_albers():
    assert op.order_epsg(TECOPA, PORTRAIT) == 32611
    assert op.order_epsg((-120.0, 39.3, -111.9, 40.7), PORTRAIT) == 5070   # Reno to SLC


def test_order_epsg_uses_the_nestled_frame_not_a_straight_line():
    # ~93 km wide, ~1000 km tall: the straight-line width stays under 600 km, but
    # the portrait frame nestled round it opens out past 600 km
    tall = (-119.0, 34.0, -118.0, 43.0)
    assert op.order_epsg(tall, PORTRAIT) == 5070


def test_order_epsg_depends_on_the_print_aspect():
    # ~46 km wide, ~400 km tall: the portrait frame stays under 600 km (UTM), but a
    # landscape print asks for a wider frame that opens past it (Albers)
    narrow = (-117.0, 34.0, -116.5, 37.6)
    assert op.order_epsg(narrow, PORTRAIT) == 32611
    assert op.order_epsg(narrow, LANDSCAPE) == 5070


def test_nestled_frame_wide_tracks():
    f = op.nestled_frame((0.0, 0.0, 10000.0, 5000.0), PORTRAIT)
    assert (f[2] - f[0]) / (f[3] - f[1]) == pytest.approx(PORTRAIT)
    assert op.track_fill((0.0, 0.0, 10000.0, 5000.0), f) == pytest.approx(op.NESTLE_FILL)
    assert ((f[0] + f[2]) / 2, (f[1] + f[3]) / 2) == pytest.approx((5000.0, 2500.0))


def test_nestled_frame_tall_tracks():
    t = (0.0, 0.0, 4000.0, 30000.0)
    f = op.nestled_frame(t, PORTRAIT)
    assert (f[3] - f[1]) == pytest.approx(30000.0 / op.NESTLE_FILL)
    assert op.track_fill(t, f) == pytest.approx(op.NESTLE_FILL)


def test_nestled_frame_minimum():
    f = op.nestled_frame((0.0, 0.0, 100.0, 100.0), PORTRAIT)
    assert f[2] - f[0] == pytest.approx(op.MIN_FRAME_M)


def test_widen_frame_never_shrinks():
    frame = (0.0, 0.0, 1000.0, 500.0)
    assert op.widen_frame(frame, 500.0) == frame
    assert op.widen_frame(frame, 1000.0) == frame


def test_plate_bounds_and_needed_resolution():
    assert op.plate_bounds((0.0, 0.0, 10000.0, 15000.0)) == pytest.approx(
        (-1000.0, -1500.0, 11000.0, 16500.0))
    assert op.needed_resolution((0.0, 0.0, 18000.0, 27000.0), 12) == pytest.approx(5.0)


def test_lonlat_round_trip_contains_the_input():
    ll = op.to_lonlat_bbox(op.project_bbox(TECOPA, 32611), 32611)
    assert ll[0] <= TECOPA[0] and ll[1] <= TECOPA[1]
    assert ll[2] >= TECOPA[2] and ll[3] >= TECOPA[3]


def test_grid_under_10m_with_lidar():
    g = op.choose_grid(4.63, LIDAR)       # quarter-metre steps below 10 m
    assert g == {"grid_m": 4.5, "layer_m": 1, "upsample": 1.0, "widen": False,
                 "us_share": 1.0}


def test_grid_without_lidar_upsamples_within_2x():
    g = op.choose_grid(6.0, NO_LIDAR)
    assert (g["grid_m"], g["layer_m"]) == (10.0, 10)
    assert g["upsample"] == pytest.approx(10 / 6)
    assert not g["widen"]


def test_grid_past_2x_asks_to_widen():
    g = op.choose_grid(4.0, NO_LIDAR)
    assert g["widen"] and g["layer_m"] == 10


def test_grid_at_exactly_2x_is_not_widened():
    g = op.choose_grid(5.0, NO_LIDAR)     # finest covered is 10 m: exactly 2x
    assert g["upsample"] == pytest.approx(2.0)
    assert not g["widen"]


def test_large_frames_get_a_grid_at_the_need():
    # 25 m and 160 m are not static tiles: the dynamic service serves them from the
    # finest covered layer, which layer_m records
    g = op.choose_grid(25.0, LIDAR)
    assert (g["grid_m"], g["layer_m"]) == (25.0, 1)
    g = op.choose_grid(163.0, NO_LIDAR)
    assert (g["grid_m"], g["layer_m"]) == (160.0, 10)


def test_static_grids_record_their_own_layer():
    g = op.choose_grid(12.0, LIDAR)       # 5 m steps from 10 m: 10 m, the static tiles
    assert (g["grid_m"], g["layer_m"]) == (10.0, 10)
    g = op.choose_grid(31.0, NO_LIDAR)
    assert (g["grid_m"], g["layer_m"]) == (30.0, 30)


def test_grid_at_the_static_boundary_is_still_static():
    g = op.choose_grid(10.0, NO_LIDAR)    # 10 m is covered outright at need == 10
    assert (g["grid_m"], g["layer_m"], g["upsample"]) == (10.0, 10, 1.0)


def test_grid_just_under_10m_with_and_without_lidar():
    g = op.choose_grid(9.99, LIDAR)
    assert (g["grid_m"], g["layer_m"]) == (9.75, 1)
    g = op.choose_grid(9.99, NO_LIDAR)
    assert (g["grid_m"], g["layer_m"]) == (10.0, 10)
    assert g["upsample"] == pytest.approx(10 / 9.99)


def test_partial_coverage_does_not_count():
    g = op.choose_grid(4.0, {1: 0.9, 3: 0.0, 10: 1.0, 30: 1.0, 60: 0.0})
    assert g["layer_m"] == 10


def test_no_coverage_is_a_plate_error():
    with pytest.raises(op.PlateError):
        op.choose_grid(10.0, {1: 0.0, 3: 0.0, 10: 0.0, 30: 0.0, 60: 0.0})


def test_plate_reaching_the_pacific_still_builds():
    # Reno to Salt Lake's west edge sits in the ocean: no layer reaches 0.995, but
    # 10 m covers everything 30 m does (60 m genuinely has no lower-48 tile, see
    # choose_grid's docstring), so 10 m is still the right layer to use.
    g = op.choose_grid(210.7, {10: 0.9442, 30: 0.9441, 60: 0.0})
    assert (g["grid_m"], g["layer_m"]) == (210.0, 10)
    assert g["us_share"] == pytest.approx(0.9442)
    assert not g["widen"]


def test_plate_mostly_at_sea_is_a_plate_error():
    with pytest.raises(op.PlateError, match="no US elevation data"):
        op.choose_grid(30.0, {10: 0.3, 30: 0.3})


def test_border_plate_keeps_10m_even_though_30m_reads_fuller():
    # A Montana/Alberta border box: 30 m covers Canada too, so it reads fuller than
    # 10 m (the honest US-only reference). Taking 30 m's share as the reference
    # would call the plate fully covered and silently drop 10 m detail from the US
    # two-thirds of it, so the reference is 10 m's own share, not the best of all.
    g = op.choose_grid(12.0, {1: 0.0, 3: 0.0, 10: 0.5253, 30: 1.0})
    assert g["layer_m"] == 10
    assert g["us_share"] == pytest.approx(0.5253)


def test_partial_lidar_inland_still_rejects_the_fine_layer():
    # 1 m only reaches 90% where 10 m reaches 100%: short of 10 m's coverage even
    # within COVERAGE_TOLERANCE, so 1 m is skipped for 10 m.
    g = op.choose_grid(5.0, {1: 0.9, 10: 1.0})
    assert g["layer_m"] == 10 and g["us_share"] == pytest.approx(1.0)


def test_coastal_lidar_is_accepted_within_tolerance():
    # 1 m falls a hair short of 10 m's own coverage, well within the 0.5% tolerance
    # a coastline's rounding error accounts for.
    g = op.choose_grid(5.0, {1: 0.94, 10: 0.9442})
    assert g["layer_m"] == 1 and g["us_share"] == pytest.approx(0.9442)


def test_dynamic_fine_off_ignores_lidar(monkeypatch):
    monkeypatch.setattr(op, "USE_DYNAMIC_FINE", False)
    g = op.choose_grid(6.0, LIDAR)
    assert g["layer_m"] == 10 and g["grid_m"] == 10.0


def test_choose_grid_normalises_string_keys():
    g = op.choose_grid(6.0, {"1": 1.0, "3": 0.0, "10": 1.0, "30": 1.0, "60": 0.0})
    assert g == op.choose_grid(6.0, LIDAR)


def test_static_grid_steps_down_when_its_own_layer_is_not_covered():
    # need 12 rounds to the 10 m static tile, but only 50% of the plate has 10 m
    # data, so it must fall back to the dynamic service on the finest layer that
    # really is covered (1 m), one quarter-metre step below the static boundary
    g = op.choose_grid(12.0, {1: 1.0, 3: 0.0, 10: 0.5, 30: 1.0, 60: 0.0})
    assert g == {"grid_m": 9.75, "layer_m": 1, "upsample": 1.0, "widen": False,
                 "us_share": 1.0}


def test_static_grid_steps_down_to_the_next_static_boundary_below():
    # need 31 rounds to the 30 m static tile, but it's only 20% covered; 10 m is
    # fully covered, so the grid steps down to 25 m, served dynamically from 10 m
    g = op.choose_grid(31.0, {10: 1.0, 30: 0.2, 60: 0.0})
    assert g == {"grid_m": 25.0, "layer_m": 10, "upsample": 1.0, "widen": False,
                 "us_share": 1.0}


def test_widen_for_upsample_lands_just_under_2x():
    f = op.widen_for_upsample((0.0, 0.0, 6000.0, 9000.0), 10, 12)
    need = op.needed_resolution(f, 12)
    assert 10 / need < op.MAX_UPSAMPLE
    assert 10 / need == pytest.approx(op.MAX_UPSAMPLE)
    assert (f[2] - f[0]) / (f[3] - f[1]) == pytest.approx(PORTRAIT)


def _curated(native=10, bounds=(400000.0, 3800000.0, 700000.0, 4200000.0)):
    return [{"id": "big", "crs": "EPSG:32611", "bounds": list(bounds),
             "native_resolution_m": native}]


def test_curated_fit_reuses_a_plate_that_holds_the_print():
    tracks = (-116.4, 35.7, -116.0, 36.1)          # ~36 x 44 km: needs ~16.7 m/px at 12x18
    regions = _curated()
    fit = op.curated_fit(tracks, PORTRAIT, 12, regions)
    assert fit["region"]["id"] == "big" and fit["epsg"] == 32611
    assert fit["need_m"] >= 10
    b = regions[0]["bounds"]
    plate = op.plate_bounds(fit["frame"])
    assert plate[0] >= b[0] and plate[1] >= b[1] and plate[2] <= b[2] and plate[3] <= b[3]


def test_curated_fit_refuses_coarse_or_small_plates():
    tracks = (-116.4, 35.7, -116.0, 36.1)
    assert op.curated_fit(tracks, PORTRAIT, 12, _curated(native=30)) is None
    assert op.curated_fit(tracks, PORTRAIT, 12,
                          _curated(bounds=(570000.0, 3960000.0, 580000.0, 3970000.0))) is None


def test_curated_fit_requires_the_margin_not_just_the_frame():
    # bounds that hold the bare frame exactly (with 100 m of slack) but not the
    # PLATE_MARGIN border a reused plate must also carry
    tracks = (-116.4, 35.7, -116.0, 36.1)
    frame = op.nestled_frame(op.project_bbox(tracks, 32611), PORTRAIT)
    bounds = (frame[0] - 100.0, frame[1] - 100.0, frame[2] + 100.0, frame[3] + 100.0)
    assert op.curated_fit(tracks, PORTRAIT, 12, _curated(bounds=bounds)) is None


def test_mid_grid_prefers_static_10m():
    # need 12 and need 19.9 both fall in static 10 m's span [10, 20]: the static
    # tile is preferred over the dynamic service, whether or not finer lidar is
    # covered too (lidar cannot beat a covered static pick for need >= 10).
    for coverage in (LIDAR, NO_LIDAR):
        g = op.choose_grid(12.0, coverage)
        assert (g["grid_m"], g["layer_m"], g["upsample"], g["widen"]) == (
            10.0, 10, 1.0, False)
        g = op.choose_grid(19.9, coverage)
        assert (g["grid_m"], g["layer_m"], g["upsample"], g["widen"]) == (
            10.0, 10, 1.0, False)


def test_mid_grid_prefers_static_30m():
    # need 31, 37 and 59 all fall in static 30 m's span [30, 60].
    for coverage in (LIDAR, NO_LIDAR):
        for need in (31.0, 37.0, 59.0):
            g = op.choose_grid(need, coverage)
            assert (g["grid_m"], g["layer_m"], g["upsample"], g["widen"]) == (
                30.0, 30, 1.0, False)


def test_mid_grid_gap_between_static_bands_stays_dynamic():
    # need 20.5 and 29 fall between 10 m's span (up to 20) and 30 m's span (from
    # 30): no static layer's span holds them, so the old nice-floor path on the
    # dynamic service still applies, unchanged by the static preference.
    g = op.choose_grid(20.5, NO_LIDAR)
    assert (g["grid_m"], g["layer_m"]) == (20.0, 10)
    g = op.choose_grid(29.0, NO_LIDAR)
    assert (g["grid_m"], g["layer_m"]) == (25.0, 10)


def test_mid_grid_past_static_30_span_steps_down_as_before():
    # need 61 is just past 30 m's span (up to 60): nice-floor would land exactly on
    # the 60 m static size, but the 60 m tiles are Alaska-only (uncovered here), so
    # the existing step-down still serves it dynamically at 55 m from 10 m.
    g = op.choose_grid(61.0, NO_LIDAR)
    assert (g["grid_m"], g["layer_m"]) == (55.0, 10)


def test_large_grid_stays_dynamic_past_both_static_spans():
    g = op.choose_grid(210.0, NO_LIDAR)
    assert (g["grid_m"], g["layer_m"]) == (210.0, 10)


def test_static_preference_never_picks_60m_in_the_lower_48():
    # 60 m reads 0.0 everywhere south of Alaska, so even a need whose nice-floor
    # value would land on 60 m never gets a static 60 m pick -- STATIC_SPAN's
    # candidate layers are only 10 and 30.
    g = op.choose_grid(55.0, NO_LIDAR)      # squarely inside 30 m's span [30, 60]
    assert (g["grid_m"], g["layer_m"]) == (30.0, 30)


def test_static_preference_falls_through_when_its_own_layer_is_uncovered():
    # need 12 rounds into static 10 m's span, but here only 1 m and 30 m are
    # covered (10 m itself reads short of the reference), so the static
    # preference cannot pick 10 m and falls back to the existing step-down path,
    # same as test_static_grid_steps_down_when_its_own_layer_is_not_covered.
    g = op.choose_grid(12.0, {1: 1.0, 3: 0.0, 10: 0.5, 30: 1.0, 60: 0.0})
    assert (g["grid_m"], g["layer_m"]) == (9.75, 1)


def test_choose_grid_reads_absent_layers_as_uncovered():
    # Prepare asks only for 10 and 30 m once the need is 20 m or more (60 m is
    # never worth asking: it has no lower-48 tile at all)
    g = op.choose_grid(25.0, {"10": 1.0, "30": 1.0})
    assert (g["grid_m"], g["layer_m"], g["widen"]) == (25.0, 10, False)
    g = op.choose_grid(25.0, {"30": 1.0})
    assert (g["grid_m"], g["layer_m"]) == (30.0, 30)
    assert g["upsample"] == pytest.approx(1.2)


# ---- contract: STATIC_LAYERS_M is region_prep's own static-tile list, not a copy ----

def test_static_layers_m_matches_region_preps_static_tiles():
    rp = pytest.importorskip("region_prep")
    assert op.STATIC_LAYERS_M == rp.DEM_RES_CHOICES
