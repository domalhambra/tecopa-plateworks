"""A photo's spot on the plate: GPS first, then its time on the track (order-photos Task 2)."""
from __future__ import annotations

import numpy as np
import pytest

from app.geo import RegionGeo, lonlat_to_crs
from app.ingest import Track
from app.photos import PhotoMeta
from app import photospot

REGION = RegionGeo(crs="EPSG:32611", bounds=(400000.0, 4000000.0, 500000.0, 4100000.0),
                   overview_size=(1000, 1000))
T0 = 1_700_000_000.0


def _track(coords, times, track_id="t"):
    return Track(track_id=track_id, coords=np.array(coords, dtype=float), day=None,
                 coords_t=None if times is None else np.array(times, dtype=float))


def _meta(lonlat=None, taken=None):
    return PhotoMeta("p.jpg", lonlat, taken, (60, 40))


def _line():
    return _track([(410000, 4010000), (410000, 4020000), (430000, 4020000)],
                  [T0, T0 + 1000, T0 + 3000])


def test_gps_wins_over_time():
    lonlat = (-117.0, 36.0)
    spot = photospot.spot_for(_meta(lonlat, T0 + 500), [_line()], REGION)
    x, y = lonlat_to_crs(REGION, *lonlat)
    assert spot.source == "gps"
    assert (spot.x, spot.y) == pytest.approx((x, y))


def test_gps_is_kept_outside_the_plate():
    spot = photospot.spot_for(_meta((-100.0, 36.0)), [], REGION)
    assert spot is not None and spot.source == "gps"
    assert not photospot.in_frame(spot, REGION.bounds)


def test_time_interpolates_between_track_points():
    spot = photospot.spot_for(_meta(None, T0 + 500), [_line()], REGION)
    assert spot.source == "time"
    assert (spot.x, spot.y) == pytest.approx((410000, 4015000))
    spot = photospot.spot_for(_meta(None, T0 + 2000), [_line()], REGION)
    assert (spot.x, spot.y) == pytest.approx((420000, 4020000))


def test_time_on_a_point_lands_on_it():
    spot = photospot.spot_for(_meta(None, T0 + 1000), [_line()], REGION)
    assert (spot.x, spot.y) == pytest.approx((410000, 4020000))


def test_time_searches_all_tracks():
    other = _track([(450000, 4050000), (460000, 4050000)], [T0 + 9000, T0 + 9100], "o")
    spot = photospot.spot_for(_meta(None, T0 + 9050), [_line(), other], REGION)
    assert (spot.x, spot.y) == pytest.approx((455000, 4050000))


def test_just_past_a_track_end_within_tolerance_snaps_to_the_end():
    spot = photospot.spot_for(_meta(None, T0 + 3000 + 600), [_line()], REGION)
    assert (spot.x, spot.y) == pytest.approx((430000, 4020000))
    spot = photospot.spot_for(_meta(None, T0 - 600), [_line()], REGION)
    assert (spot.x, spot.y) == pytest.approx((410000, 4010000))


def test_a_time_outside_the_tolerance_has_no_spot():
    assert photospot.spot_for(_meta(None, T0 + 3000 + 601), [_line()], REGION) is None
    assert photospot.spot_for(_meta(None, T0 - 601), [_line()], REGION) is None


def test_a_naive_time_never_matches():
    # read_meta gives taken_utc=None for a photo with no stored UTC offset.
    assert photospot.spot_for(_meta(None, None), [_line()], REGION) is None


def test_a_non_finite_time_never_matches():
    assert photospot.spot_for(_meta(None, float("nan")), [_line()], REGION) is None


def test_a_track_with_no_times_gives_no_time_spot():
    allnan = _track([(410000, 4010000), (420000, 4010000)], [np.nan, np.nan])
    assert photospot.spot_for(_meta(None, T0), [allnan], REGION) is None
    assert photospot.spot_for(_meta(None, T0), [_track([(1, 1), (2, 2)], None)],
                              REGION) is None


def test_unknown_times_in_a_track_are_skipped():
    t = _track([(410000, 4010000), (415000, 4010000), (420000, 4010000)],
               [T0, np.nan, T0 + 1000])
    spot = photospot.spot_for(_meta(None, T0 + 500), [t], REGION)
    assert (spot.x, spot.y) == pytest.approx((415000, 4010000))


def test_no_tracks_and_no_gps_gives_no_spot():
    assert photospot.spot_for(_meta(None, T0), [], REGION) is None


def test_in_frame_uses_min_max_crop_order_and_includes_edges():
    frame = (100.0, 200.0, 300.0, 400.0)
    assert photospot.in_frame(photospot.Spot(100.0, 400.0, "gps"), frame)
    assert photospot.in_frame(photospot.Spot(200.0, 300.0, "time"), frame)
    assert not photospot.in_frame(photospot.Spot(99.9, 300.0, "gps"), frame)
    assert not photospot.in_frame(photospot.Spot(200.0, 400.1, "gps"), frame)


def test_the_tolerance_is_ten_minutes():
    assert photospot.PHOTO_TIME_TOLERANCE_S == 600
