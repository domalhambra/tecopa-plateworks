# tests/test_marks.py
# Which hotspots are real marks (viewshed wash, decision 16), and that adding a track
# or a waypoint never loses one (decision 17).
from app import marks
from app.main import ANNOTATION_CARRY_M, WAYPOINT_DEDUP_M, _carry_annotations, _merge_waypoints
from app.ingest import _waypoint_hotspot
from app.serialize import spec_from_json, spec_to_json
from app.spec import CompositionSpec


def _density(x=0.0, y=0.0, **kw):
    """A machine-made density spot, the shape app.density.hotspots emits."""
    return {"x": x, "y": y, "weight": 9, **kw}


def _waypoint(x=0.0, y=0.0, label="Camp"):
    return {"x": x, "y": y, "weight": 3, "label": label, "icon": "camp", "mark": True}


# ---- decision 16: what a mark is ----

def test_a_waypoint_is_a_mark():
    from types import SimpleNamespace
    region = SimpleNamespace(crs="EPSG:32610")
    hs = _waypoint_hotspot(region, -120.65, 40.42, "", None)   # unnamed, no symbol
    assert hs["mark"] is True
    assert marks.is_mark(hs)                                    # named or not

def test_an_unnamed_density_spot_is_not():
    assert not marks.is_mark(_density())
    assert not marks.is_mark(_density(label="", icon="", photo=""))
    assert not marks.is_mark(_density(label="   "))

def test_naming_a_density_spot_makes_it_a_mark():
    assert marks.is_mark(_density(label="Rock Lake"))

def test_an_old_manifests_named_spot_counts():
    # no `mark` key anywhere: a named spot and a photo spot from an old file count
    assert marks.is_mark({"x": 1, "y": 2, "weight": 3, "label": "Summit", "icon": "peak"})
    assert marks.is_mark({"x": 1, "y": 2, "weight": 3, "photo": "data:image/jpeg;base64,AAAA"})

def test_observers_are_the_finite_xy_of_each_mark_in_order():
    spots = [_density(5, 5), _waypoint(10, 20), _density(30, 40, label="A"),
             _waypoint(10, 20)]                                  # a duplicate stays
    assert marks.observers(spots) == [(10.0, 20.0), (30.0, 40.0), (10.0, 20.0)]

def test_observers_skip_a_mark_with_no_finite_position():
    spots = [_waypoint(float("nan"), 1), _waypoint(1, float("inf")),
             {"label": "no coords"}, {"x": "a", "y": 2, "label": "junk"}, _waypoint(2, 3)]
    assert marks.observers(spots) == [(2.0, 3.0)]


# ---- decision 17: merging waypoints ----

def test_a_waypoint_near_a_density_spot_replaces_it():
    out = _merge_waypoints([_density(0, 0)], [_waypoint(300, 0)])
    assert len(out) == 1
    assert out[0]["x"] == 300 and out[0]["mark"] is True

def test_two_waypoints_300_m_apart_both_stay():
    out = _merge_waypoints([], [_waypoint(0, 0, "A"), _waypoint(300, 0, "B")])
    assert [s["label"] for s in out] == ["A", "B"]

def test_the_same_waypoint_twice_is_one_mark():
    out = _merge_waypoints([], [_waypoint(0, 0), _waypoint(0.5, 0.5)])
    assert len(out) == 1

def test_the_same_waypoint_uploaded_in_a_second_file_is_still_one_mark():
    # the session already holds the first file's pin; a re-export carries it again
    first = _merge_waypoints([], [_waypoint(100, 100)])
    again = _merge_waypoints(first, [_waypoint(100.4, 100.2)])
    assert len(again) == 1

def test_a_density_spot_carrying_a_photo_is_not_replaced():
    photo = _density(0, 0, photo="data:image/jpeg;base64,AAAA")
    out = _merge_waypoints([photo], [_waypoint(300, 0)])
    assert len(out) == 2
    assert photo in out

def test_a_named_density_spot_is_not_replaced():
    named = _density(0, 0, label="Rock Lake")
    assert len(_merge_waypoints([named], [_waypoint(399, 0)])) == 2

def test_a_density_spot_past_400_m_stays_beside_the_waypoint():
    out = _merge_waypoints([_density(0, 0)], [_waypoint(WAYPOINT_DEDUP_M + 1, 0)])
    assert len(out) == 2

def test_one_waypoint_replaces_every_unmarked_spot_in_reach():
    out = _merge_waypoints([_density(0, 0), _density(0, 200), _density(5000, 0)],
                           [_waypoint(100, 100)])
    assert sorted(s["x"] for s in out) == [100, 5000]


# ---- adding a track never moves a waypoint ----

def test_adding_a_track_does_not_move_a_waypoint():
    old = [_waypoint(1000, 1000, label="Camp")]
    new = [_density(1000 + 2000, 1000)]              # inside ANNOTATION_CARRY_M, past 400 m
    assert 2000 < ANNOTATION_CARRY_M
    out = _carry_annotations(old, new)
    camp = next(s for s in out if s.get("mark"))
    assert (camp["x"], camp["y"]) == (1000, 1000) and camp["label"] == "Camp"
    density = next(s for s in out if not s.get("mark"))
    assert density["x"] == 3000 and not density.get("label")

def test_an_unnamed_waypoint_survives_a_recompute():
    old = [_waypoint(1000, 1000, label="")]
    out = _carry_annotations(old, [])
    assert out == old

def test_a_recomputed_density_spot_on_a_kept_waypoint_does_not_double_it():
    # the density peak the waypoint replaced comes back on every recompute
    old = [_waypoint(1000, 1000)]
    out = _carry_annotations(old, [_density(1100, 1000)])
    assert len(out) == 1 and out[0]["mark"] is True

def test_a_recomputed_spot_with_its_own_photo_stays_beside_a_kept_waypoint():
    out = _carry_annotations([_waypoint(1000, 1000)],
                             [_density(1100, 1000, photo="data:image/jpeg;base64,AAAA")])
    assert len(out) == 2

def test_a_named_old_density_spot_still_moves_its_label_as_before():
    # the pre-existing rule for non-mark annotations is untouched
    out = _carry_annotations([_density(0, 0, label="Rock Lake")], [_density(500, 0)])
    assert len(out) == 1 and out[0]["label"] == "Rock Lake" and out[0]["x"] == 500


# ---- the key survives a manifest round trip ----

def test_mark_true_survives_a_manifest_round_trip():
    spec = CompositionSpec(
        region_id="t", crs="EPSG:32610", crop=(0, 0, 1000, 1000),
        print_w_in=10, print_h_in=10, native_resolution_m=10,
        tracks=[], hotspots=[_waypoint(10, 20, label="")], seed=7)
    back = spec_from_json(spec_to_json(spec))
    assert back.hotspots[0]["mark"] is True
    assert marks.observers(back.hotspots) == [(10.0, 20.0)]


# ---- the same waypoint arriving twice: one rule for an upload and for an order ----

def test_the_upload_path_uses_the_shared_same_waypoint_rule():
    import inspect
    from app import main
    assert "is_same_waypoint" in inspect.getsource(main._merge_waypoints)
    assert not hasattr(main, "WAYPOINT_SAME_M")          # the number lives in app.marks
    assert marks.WAYPOINT_SAME_M == 1.0


def test_is_same_waypoint_looks_only_at_waypoints_within_a_metre():
    here = _waypoint(100, 100)
    assert marks.is_same_waypoint(_waypoint(100.5, 100.5), [here])
    assert not marks.is_same_waypoint(_waypoint(101, 100), [here])        # exactly 1 m: two marks
    assert not marks.is_same_waypoint(_waypoint(100, 100), [_density(100, 100)])   # not a waypoint
    assert not marks.is_same_waypoint(_waypoint(100, 100), [])


def test_collapse_keeps_the_first_and_counts_the_rest():
    a, b, c = _waypoint(0, 0, "A"), _waypoint(0.4, 0.3, "A again"), _waypoint(300, 0, "B")
    kept, collapsed = marks.collapse_waypoints([a, b, c, _waypoint(300.2, 0.1, "B again")])
    assert kept == [a, c] and collapsed == 2
    assert marks.collapse_waypoints([]) == ([], 0)


def test_collapse_finds_a_neighbour_across_a_grid_line():
    kept, collapsed = marks.collapse_waypoints([_waypoint(0.9, 0.9), _waypoint(1.1, 1.1),
                                                _waypoint(0.05, 0.9)])
    assert len(kept) == 1 and collapsed == 2


def test_collapse_agrees_with_the_upload_merge():
    pts = [_waypoint(x * 0.37, (x * 7) % 3) for x in range(60)] + [_waypoint(5000, 5000)]
    kept, _ = marks.collapse_waypoints(pts)
    assert kept == _merge_waypoints([], pts)
