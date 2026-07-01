# tests/test_spec.py
import numpy as np
import pytest
from app.spec import (CompositionSpec, ZoomTooTightError, OutputTooLargeError,
                      SpecError, MAX_OUTPUT_PIXELS)

def base_kwargs(**over):
    kw = dict(
        region_id="r", crs="EPSG:32612",
        crop=(430000.0, 4345000.0, 460000.0, 4385000.0),  # 30 km x 40 km
        print_w_in=18.0, print_h_in=24.0,
        native_resolution_m=10.0,
        tracks=[np.array([[431000.0, 4346000.0], [459000.0, 4384000.0]])],
        hotspots=[{"x": 445000.0, "y": 4365000.0, "weight": 5}],
        seed=7,
    )
    kw.update(over)
    return kw

def test_aspect_matches_print():
    s = CompositionSpec(**base_kwargs())
    crop_ar = (s.crop[2] - s.crop[0]) / (s.crop[3] - s.crop[1])
    assert abs(crop_ar - 18/24) < 0.02

def test_zoom_cap_rejects_too_tight():
    # 1 km wide crop on an 18 inch print at 300 dpi demands sub-10m detail -> reject
    with pytest.raises(ZoomTooTightError):
        CompositionSpec(**base_kwargs(crop=(445000.0, 4364250.0, 446000.0, 4365583.0))).validate(dpi=300)

def test_pixel_dims_track_dpi():
    s = CompositionSpec(**base_kwargs())
    assert s.pixel_size(96) == (1728, 2304)
    assert s.pixel_size(300) == (5400, 7200)

def test_output_pixel_ceiling_rejected():
    # red-team V1-6: a huge print size would allocate a gigapixel canvas -> OOM.
    # 40x40 in @ 300 dpi = 144 MP, over the 120 MP ceiling; refuse before any render.
    s = CompositionSpec(**base_kwargs(print_w_in=40, print_h_in=40))
    assert s.pixel_size(300)[0] * s.pixel_size(300)[1] > MAX_OUTPUT_PIXELS
    with pytest.raises(OutputTooLargeError):
        s.validate(dpi=300)
    assert issubclass(OutputTooLargeError, SpecError)   # API maps SpecError -> 422

def test_nonpositive_print_size_rejected_not_divzero():
    # print size 0 would divide-by-zero the zoom cap; must raise a clean SpecError (422)
    with pytest.raises(SpecError):
        CompositionSpec(**base_kwargs(print_w_in=0.0)).validate(dpi=300)

def test_nonfinite_print_size_is_clean_spec_error():
    # red-team: nan/inf print size would make round() raise ValueError/OverflowError --
    # NOT a SpecError -- and escape the endpoint's `except SpecError` as a 500. validate()
    # must convert it to a clean SpecError (-> 422) before pixel_size().
    for bad in (float("nan"), float("inf")):
        with pytest.raises(SpecError):
            CompositionSpec(**base_kwargs(print_w_in=bad)).validate(dpi=300)
    with pytest.raises(SpecError):
        CompositionSpec(**base_kwargs(crop=(float("nan"), 0.0, 1.0, 1.0))).validate(dpi=300)

def test_zoom_cap_allows_exactly_native():
    # Boundary guard (invariant 6): a crop that lands EXACTLY at native resolution
    # is not finer than the data, so it must be allowed. Pins the strict `<`
    # against an accidental regression to `<=`.
    # 54000 m wide / (18 in * 300 dpi = 5400 px) = exactly 10.0 m/px.
    s = CompositionSpec(**base_kwargs(crop=(430000.0, 4345000.0, 484000.0, 4417000.0)))
    assert s.ground_per_pixel(300) == 10.0
    assert s.validate(dpi=300) is s   # does not raise
