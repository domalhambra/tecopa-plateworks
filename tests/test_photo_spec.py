"""The spec carries a photo's box, crop and source (order-photos Task 4).

A hotspot gains three optional keys: `box` {"dx_in","dy_in"}, `crop` {"cx","cy"} and
`source` ("gps"|"time"|"manual"). The spec gains `photo_layout` and `photo_band_side`.
The manifest door (`provenance.spec_from_manifest`) bounds the keys and drops a bad one
from its hotspot; the hotspot itself stays.
"""
from __future__ import annotations

import json

import pytest

from app import provenance, serialize
from app.spec import (CompositionSpec, PHOTO_BAND_SIDES, PHOTO_LAYOUTS, SpecError)
from tests.test_spec import base_kwargs

_OK_CROP = (430000.0, 4345000.0, 484000.0, 4417000.0)


def _spec(**over):
    return CompositionSpec(**base_kwargs(crop=_OK_CROP, **over))


def _manifest_with(hotspot):
    m = json.load(open("tests/fixtures/manifest_v1.json"))
    m["spec"]["hotspots"] = [dict({"x": 690000.0, "y": 4485000.0, "weight": 1}, **hotspot)]
    return m


def test_photo_layout_round_trips():
    assert PHOTO_LAYOUTS == ("open", "band")
    assert PHOTO_BAND_SIDES == ("top", "bottom")
    d = _spec()
    assert (d.photo_layout, d.photo_band_side) == ("open", "top")
    s = _spec(photo_layout="band", photo_band_side="bottom")
    back = serialize.spec_from_json(json.loads(json.dumps(serialize.spec_to_json(s))))
    assert (back.photo_layout, back.photo_band_side) == ("band", "bottom")
    assert back.validate(300) is back


def test_an_old_spec_without_the_fields_loads_with_the_defaults():
    j = serialize.spec_to_json(_spec())
    j.pop("photo_layout")
    j.pop("photo_band_side")
    back = serialize.spec_from_json(j)
    assert (back.photo_layout, back.photo_band_side) == ("open", "top")


def test_validate_refuses_an_unknown_layout():
    with pytest.raises(SpecError, match="photo_layout"):
        _spec(photo_layout="grid").validate(300)
    with pytest.raises(SpecError, match="photo_band_side"):
        _spec(photo_band_side="left").validate(300)


def test_box_and_crop_survive_a_manifest_round_trip():
    hs = {"box": {"dx_in": 1.25, "dy_in": -0.75}, "crop": {"cx": 0.25, "cy": 0.75},
          "source": "time", "label": "Camp"}
    spec = provenance.spec_from_manifest(_manifest_with(hs))
    assert spec.hotspots[0] == dict({"x": 690000.0, "y": 4485000.0, "weight": 1}, **hs)
    m2 = provenance.build_manifest(spec)
    again = provenance.spec_from_manifest(json.loads(json.dumps(m2)))
    assert again.hotspots == spec.hotspots


@pytest.mark.parametrize("key,bad", [
    ("box", {"dx_in": 1e9, "dy_in": 0.0}),              # far off the sheet
    ("box", {"dx_in": 0.0, "dy_in": -25.0}),            # past the larger side (24 in)
    ("box", {"dx_in": float("nan"), "dy_in": 0.0}),
    ("box", {"dx_in": float("inf"), "dy_in": 0.0}),
    ("box", {"dx_in": 10 ** 400, "dy_in": 0.0}),        # an int too big for a float
    ("box", {"dx_in": True, "dy_in": 0.0}),             # a bool is not a number here
    ("box", {"dx_in": "1", "dy_in": 0.0}),
    ("box", {"dx_in": 1.0}),                            # missing key
    ("box", [1.0, 2.0]),
    ("box", "evil"),
    ("crop", {"cx": float("nan"), "cy": 0.5}),
    ("crop", {"cx": 1.5, "cy": 0.5}),
    ("crop", {"cx": 0.5, "cy": -0.1}),
    ("crop", {"cx": 0.5}),
    ("crop", None),
    ("source", "evil"),
    ("source", ["gps"]),
    ("source", {"a": 1}),
    ("source", 3),
])
def test_a_crafted_box_or_crop_is_dropped_at_the_door(key, bad):
    m = _manifest_with({key: bad, "label": "Camp"})
    spec = provenance.spec_from_manifest(m)       # no exception
    assert key not in spec.hotspots[0]            # the bad key is gone
    assert spec.hotspots[0]["label"] == "Camp"    # the hotspot and its other keys stay


def test_one_bad_key_does_not_cost_the_good_ones():
    m = _manifest_with({"box": {"dx_in": 1e9, "dy_in": 0.0},
                        "crop": {"cx": 0.4, "cy": 0.6}, "source": "gps"})
    h = provenance.spec_from_manifest(m).hotspots[0]
    assert "box" not in h
    assert h["crop"] == {"cx": 0.4, "cy": 0.6} and h["source"] == "gps"


def test_a_box_at_the_sheet_edge_is_kept():
    # the bound is the larger sheet side in inches (fixture sheet: see print_h_in)
    m = _manifest_with({})
    big = max(m["spec"]["print_w_in"], m["spec"]["print_h_in"])
    m["spec"]["hotspots"][0]["box"] = {"dx_in": big, "dy_in": -big}
    h = provenance.spec_from_manifest(m).hotspots[0]
    assert h["box"] == {"dx_in": big, "dy_in": -big}


def test_non_dict_hotspots_do_not_break_the_bound():
    m = _manifest_with({})
    m["spec"]["hotspots"].append("not a dict")
    spec = provenance.spec_from_manifest(m)
    assert spec.hotspots[1] == "not a dict"


def test_the_layout_fields_leave_the_terrain_and_route_keys_alone():
    # photo_layout / photo_band_side change the overlay only (docs/changing-things.md)
    from app import render
    assert "photo_layout" in render.BASE_KEY_MASK_ALWAYS
    assert "photo_band_side" in render.BASE_KEY_MASK_ALWAYS
    assert "photo_layout" in render.INK_KEY_MASK_ALWAYS
    assert "photo_band_side" in render.INK_KEY_MASK_ALWAYS
