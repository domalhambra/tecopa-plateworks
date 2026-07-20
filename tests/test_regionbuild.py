# Unit tests for the pure planning helpers behind /api/regions/plan.
import math
import pytest

from app import regionbuild as rb


# ---- derive_bbox: pad 20%/side with a 3 km floor ----

def test_derive_bbox_pads_20_percent():
    # a 1-degree square: 20% pad dominates the 3 km floor
    b = rb.derive_bbox(-120.0, 40.0, -119.0, 41.0)
    w, s, e, n = b
    assert w == pytest.approx(-120.2, abs=0.01)
    assert e == pytest.approx(-118.8, abs=0.01)
    assert s == pytest.approx(39.8, abs=0.01)
    assert n == pytest.approx(41.2, abs=0.01)

def test_derive_bbox_floor_dominates_tiny_tracks():
    # a ~100 m track: the 3 km floor dominates. 3 km of latitude ~ 0.02695 deg.
    b = rb.derive_bbox(-120.0, 40.0, -119.999, 40.001)
    w, s, e, n = b
    assert (n - s) >= 0.001 + 2 * 0.9 * (3000.0 / 111320.0)   # floor applied both sides
    # longitude floor is wider on the ground->degree conversion at 40N
    assert (e - w) >= 0.001 + 2 * 0.9 * (3000.0 / (111320.0 * math.cos(math.radians(40))))

def test_derive_bbox_ordering_holds():
    w, s, e, n = rb.derive_bbox(-120.5, 40.1, -120.2, 40.6)
    assert w < e and s < n


# ---- utm_epsg ----

def test_utm_epsg_utah():
    # Tushar Mountains centroid ~ -112.5 -> zone 12 -> EPSG:32612
    assert rb.utm_epsg((-113.0, 38.0, -112.0, 39.0)) == 32612

def test_utm_epsg_california():
    # Lassen ~ -120.9..-120.5 -> zone 10 -> EPSG:32610
    assert rb.utm_epsg((-120.9, 40.3, -120.5, 40.8)) == 32610


# ---- US 3DEP coverage envelope ----

def test_us_coverage_conus_alaska_hawaii():
    assert rb.bbox_covered((-120.9, 40.3, -120.5, 40.8))        # CA
    assert rb.bbox_covered((-150.0, 61.0, -149.0, 62.0))        # AK
    assert rb.bbox_covered((-156.6, 20.5, -156.0, 21.0))        # Maui

def test_us_coverage_rejects_alps_and_straddle():
    assert not rb.bbox_covered((7.0, 45.8, 7.9, 46.2))          # Alps
    # straddling the border: not FULLY inside an envelope -> not covered
    assert not rb.bbox_covered((-120.0, 48.0, -119.0, 50.5))    # into BC


# ---- slug + collision ----

def test_slugify():
    assert rb.slugify("Sawtooth Traverse 2026!") == "sawtooth_traverse_2026"
    assert rb.slugify("  --  ") == "region"
    assert rb.slugify("") == "region"

def test_unique_id_suffixes():
    existing = {"sawtooth", "sawtooth_2"}
    assert rb.unique_id("sawtooth", existing) == "sawtooth_3"
    assert rb.unique_id("fresh", existing) == "fresh"
