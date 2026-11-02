# tests/test_repeat_trips.py
# A customer's repeat trips wear in: a poster whose journeys share a stretch of route
# composites them in one layer (track_weave off), so the worn-width pass sees the
# repeats. A poster whose journeys only cross keeps the weave.
import numpy as np

from app import orderspec


def _line(x0, y0, x1, y1):
    return np.array([[x0, y0], [x1, y1]], dtype=float)


def test_one_journey_is_no_repeat():
    assert orderspec.repeats_a_route([_line(0, 0, 5000, 0)], ["2024-07-01"]) is False


def test_two_journeys_on_one_road_repeat():
    a, b = _line(0, 0, 5000, 0), _line(0, 8, 5000, 8)       # GPS noise, 8 m apart
    assert orderspec.repeats_a_route([a, b], ["2024-07-01", "2024-08-01"]) is True


def test_journeys_that_only_cross_do_not_repeat():
    a, b = _line(0, 2500, 5000, 2500), _line(2500, 0, 2500, 5000)
    assert orderspec.repeats_a_route([a, b], ["2024-07-01", "2024-08-01"]) is False


def test_a_short_shared_trailhead_does_not_repeat():
    a = np.array([[0, 0], [400, 0], [5000, 3000]], dtype=float)
    b = np.array([[0, 0], [400, 0], [5000, -3000]], dtype=float)
    assert orderspec.repeats_a_route([a, b], ["2024-07-01", "2024-08-01"]) is False


def test_two_segments_of_one_day_are_one_journey():
    # a device split one outing at auto-pause: not a repeat, even on the same ground
    a, b = _line(0, 0, 5000, 0), _line(5000, 0, 0, 0)
    assert orderspec.repeats_a_route([a, b], ["2024-07-01", "2024-07-01"]) is False


def test_a_sparse_track_is_walked_between_its_points():
    # two points 5 km apart still cover every cell between them
    a, b = _line(0, 0, 5000, 0), np.column_stack([np.arange(0, 5001, 50.0), np.zeros(101)])
    assert orderspec.repeats_a_route([a, b], ["2024-07-01", "2024-08-01"]) is True


def test_order_look_turns_the_weave_off_only_for_repeats():
    a, b = _line(0, 0, 5000, 0), _line(0, 8, 5000, 8)
    days = ["2024-07-01", "2024-08-01"]
    assert orderspec.order_look([a, b], days)["track_weave"] is False
    assert orderspec.order_look([a], days[:1])["track_weave"] is True
    # everything else is the plain look
    rest = {k: v for k, v in orderspec.order_look([a, b], days).items() if k != "track_weave"}
    assert rest == {k: v for k, v in orderspec.ORDER_LOOK.items() if k != "track_weave"}


def test_the_farm_applies_the_same_rule():
    from tests.test_asset_farm_look import _region
    from scripts.render_asset_farm import _base_spec
    from app.ingest import Track
    tracks = [Track(track_id="a", coords=_line(0, 0, 5000, 0), day="2024-07-01"),
              Track(track_id="b", coords=_line(0, 8, 5000, 8), day="2024-08-01")]
    assert _base_spec(_region(), tracks, []).track_weave is False
    assert _base_spec(_region(), tracks[:1], []).track_weave is True
