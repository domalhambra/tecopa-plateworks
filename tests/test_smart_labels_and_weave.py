# tests/test_smart_labels_and_weave.py
"""Smart label placement (spec.label_place) + chronological track weave (spec.track_weave).

Both are gated so a pre-feature poster reprints byte-identically: the spec defaults are a
render no-op, the keys are omitted from the manifest at that default, and the flags only
change the picture when explicitly set. The weave cases run on flat canvases (no DEM); the
label cases render against the region's (synthetic-in-CI) DEM like test_labels.py."""
import json
import os
import numpy as np
import pytest
from PIL import Image

from app import render, serialize
from app.spec import CompositionSpec, SpecError

REGION_DIR = "regions/lassen_ca"


# ---------------------------------------------------------------- track weave (flat canvas)
def _spec(tracks, **kw):
    return CompositionSpec(
        region_id="t", crs="EPSG:32610", crop=(0, 0, 1000, 1000),
        print_w_in=10, print_h_in=10, native_resolution_m=10,
        tracks=tracks, hotspots=[], seed=7, **kw)


def _ink(tracks, dpi=300, w=400, h=400, **kw):
    flat = np.full((h, w, 3), 128, np.uint8)
    return render._ink_tracks(flat, _spec(tracks, **kw), w, h, dpi)


H = np.array([[100.0, 500.0], [900.0, 500.0]])     # horizontal, through canvas mid (px y=200)
V = np.array([[500.0, 100.0], [500.0, 900.0]])     # vertical,   through canvas mid (px x=200)
DAYS = ["2024-06-01", "2024-06-02"]                # H is older, V is newer


def _is_gold(px, tol=60):
    return np.linalg.norm(px.astype(float) - np.array(render.TRACK_INK, float)) < tol


def test_weave_default_is_the_summed_path():
    # track_weave defaults to False -> the pre-feature summed composite, byte-identical.
    assert np.array_equal(_ink([H, V], track_days=DAYS),
                          _ink([H, V], track_days=DAYS, track_weave=False))


def test_weave_single_journey_is_a_strict_noop():
    # < 2 journeys: weave has nothing to stack, so it falls back to the summed path.
    assert np.array_equal(_ink([H], track_weave=True), _ink([H], track_weave=False))


def test_weave_changes_the_crossing_render():
    summed = _ink([H, V], track_days=DAYS, track_weave=False)
    weave = _ink([H, V], track_days=DAYS, track_weave=True)
    assert not np.array_equal(summed, weave), "weave did nothing where journeys cross"


def test_weave_newer_journey_breaks_the_older_gold():
    # newest on top: at the crossing, the newer (day-2) vertical strand's paper casing
    # knocks the older (day-1) horizontal gold out just beside the vertical ink core.
    summed = _ink([H, V], track_days=DAYS, track_weave=False)
    weave = _ink([H, V], track_days=DAYS, track_weave=True)
    s, w = summed[200, 208], weave[200, 208]           # on H, inside V's casing, outside V's core
    assert _is_gold(s), f"summed keeps the older gold under the (underneath) casing: {s}"
    assert not _is_gold(w), f"weave should break the older gold at the crossing: {w}"
    assert int(w.sum()) > int(s.sum()), "the break should be lighter (paper casing)"


def test_weave_oldest_on_top_is_the_other_break():
    # swapping the days reverses the z-order: now H is newer, so the break lands on V.
    swapped = ["2024-06-02", "2024-06-01"]             # H newer, V older
    weave = _ink([H, V], track_days=swapped, track_weave=True)
    # a point ON the vertical line, inside H's casing but outside H's core (px x=200, y~192)
    assert not _is_gold(weave[192, 200]), "the older vertical gold should be broken by H"


# ---------------------------------------------------------- smart placement helper (no DEM)
def test_place_point_label_is_centered_when_clear():
    # nothing placed, no route -> the first (centered) slot wins, no leader (as anchor mode).
    res = render._place_point_label(200, 200, 60, 20, 3, 300,
                                    lambda b: True, lambda b: False, None, 400, 400)
    x0, y0, hl, leader_box = res
    assert (x0, y0) == (round(200 - 30), round(200 - 10)) and leader_box is None


def test_place_point_label_avoids_the_route():
    # a horizontal route corridor over the centered slot forces the ring to a clear slot.
    route = np.zeros((400, 400), bool)
    route[190:210, :] = True
    res = render._place_point_label(200, 200, 60, 20, 3, 300,
                                    lambda b: True, lambda b: False, route, 400, 400)
    assert res is not None, "a name should relocate off the route, not drop"
    x0, y0, hl, leader_box = res
    assert y0 + 20 <= 190 or y0 >= 210, f"label stayed on the route: y0={y0}"
    assert leader_box is not None, "a pushed-out slot should carry a leader"


# ------------------------------------------------------------------ smart placement (render)
def _cfg():
    return json.load(open(os.path.join(REGION_DIR, "region.json")))


def _label_spec(label_place="anchor", print_w=9, print_h=12):
    cfg = _cfg(); bx = cfg["bounds"]
    cx = (bx[0] + bx[2]) / 2; cy = (bx[1] + bx[3]) / 2
    half = 18000.0
    crop = (cx - half, cy - half * print_h / print_w, cx + half, cy + half * print_h / print_w)
    return CompositionSpec(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                           print_w_in=print_w, print_h_in=print_h, native_resolution_m=10,
                           tracks=[], hotspots=[], seed=7, title_text="-", compass=False,
                           labels=True, label_place=label_place)


def _two_colliding_summits(spec):
    cx = (spec.crop[0] + spec.crop[2]) / 2; cy = (spec.crop[1] + spec.crop[3]) / 2
    return {"crs": _cfg()["crs"], "features": [
        {"name": "Alpha Peak", "kind": "summit", "rank": 85, "coords": [[cx, cy]]},
        {"name": "Beta Peak", "kind": "summit", "rank": 84, "coords": [[cx, cy]]}]}


def test_anchor_mode_still_drops_a_colliding_label():
    # the pre-feature contract: two identical-anchor summits -> the lower-rank one drops,
    # so the both-features render equals the one-feature render (unchanged behavior).
    spec = _label_spec("anchor")
    labels = _two_colliding_summits(spec)
    nw = {"lakes": [], "rivers": []}
    both = np.asarray(render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=nw, labels=labels))
    one = {"crs": labels["crs"], "features": labels["features"][:1]}
    solo = np.asarray(render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=nw, labels=one))
    assert np.array_equal(both, solo)


def test_smart_mode_places_a_colliding_label():
    # smart mode finds an alternative slot for the second summit instead of dropping it,
    # so the both-features render now DIFFERS from the one-feature render.
    spec = _label_spec("smart")
    labels = _two_colliding_summits(spec)
    nw = {"lakes": [], "rivers": []}
    both = np.asarray(render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=nw, labels=labels))
    one = {"crs": labels["crs"], "features": labels["features"][:1]}
    solo = np.asarray(render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=nw, labels=one))
    assert not np.array_equal(both, solo), "smart mode should have placed the second label"


def test_smart_labels_are_dpi_stable():
    # invariant 1: physical sizing -> the 96-dpi proof downscaled from the 300-dpi final is
    # near-identical, even with the ring / route / leader logic active.
    spec = _label_spec("smart")
    cx = (spec.crop[0] + spec.crop[2]) / 2; cy = (spec.crop[1] + spec.crop[3]) / 2
    labels = {"crs": _cfg()["crs"], "features": [
        {"name": "Test Range", "kind": "range", "rank": 100,
         "coords": [[cx - 4000, cy], [cx, cy], [cx + 4000, cy]]},
        {"name": "Test Peak", "kind": "summit", "rank": 85, "coords": [[cx + 3000, cy - 4000]]}]}
    nw = {"lakes": [], "rivers": []}
    proof = render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=nw, labels=labels)
    final = render.rasterize(spec, dpi=300, region_dir=REGION_DIR, hydro=nw, labels=labels)
    final_ds = final.resize(proof.size, Image.LANCZOS)
    mad = np.abs(np.asarray(proof, np.float32) - np.asarray(final_ds, np.float32)).mean()
    assert mad < 3.0, f"smart labels shift with DPI: MAD {mad:.2f}/255"


# --------------------------------------------------------------- serialize + validate + forever
def test_spec_to_json_omits_the_defaults():
    d = serialize.spec_to_json(_spec([H]))
    assert "label_place" not in d and "track_weave" not in d
    d2 = serialize.spec_to_json(_spec([H], label_place="smart", track_weave=True))
    assert d2["label_place"] == "smart" and d2["track_weave"] is True


def test_fields_round_trip():
    s = serialize.spec_from_json(serialize.spec_to_json(
        _spec([H], label_place="smart", track_weave=True)))
    assert s.label_place == "smart" and s.track_weave is True


def test_validate_rejects_a_bad_label_place():
    with pytest.raises(SpecError):
        _spec([H], label_place="bogus").validate(96)


def test_pre_feature_manifest_loads_with_the_defaults():
    m = json.load(open("tests/fixtures/manifest_v1.json"))
    assert "label_place" not in m["spec"] and "track_weave" not in m["spec"]
    s = serialize.spec_from_json(m["spec"])
    assert s.label_place == "anchor" and s.track_weave is False
