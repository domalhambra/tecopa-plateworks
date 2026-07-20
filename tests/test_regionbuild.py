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


# ---- ingest.lonlat_extent: raw bounds + name prefill, no region required ----

from app import ingest

GPX_ALPS = b"""<?xml version="1.0"?>
<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">
 <trk><name>Haute Route Day 1</name><trkseg>
  <trkpt lat="45.9" lon="6.9"/><trkpt lat="45.95" lon="7.0"/>
 </trkseg></trk></gpx>"""

KML_MIN = b"""<?xml version="1.0"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>
<LineString><coordinates>-112.5,38.4,0 -112.4,38.5,0</coordinates></LineString>
</Placemark></Document></kml>"""


def test_lonlat_extent_gpx_bounds_and_name():
    ext = ingest.lonlat_extent([(GPX_ALPS, "day1.gpx")])
    assert ext["name"] == "Haute Route Day 1"
    w, s, e, n = ext["bbox"]
    assert (w, s, e, n) == pytest.approx((6.9, 45.9, 7.0, 45.95))

def test_lonlat_extent_kml_and_merge():
    ext = ingest.lonlat_extent([(GPX_ALPS, "a.gpx"), (KML_MIN, "b.kml")])
    w, s, e, n = ext["bbox"]
    assert w == pytest.approx(-112.5) and e == pytest.approx(7.0)

def test_lonlat_extent_fixture_has_bounds_and_name():
    data = open("tests/fixtures/sample.gpx", "rb").read()
    ext = ingest.lonlat_extent([(data, "sample.gpx")])
    assert ext["name"] == "Susanville to Eagle Lake 2024-06-01"
    assert ext["bbox"] is not None

def test_lonlat_extent_no_points_is_none():
    ext = ingest.lonlat_extent([(b"<gpx></gpx>", "empty.gpx")])
    assert ext["bbox"] is None

def test_lonlat_extent_garbage_is_skipped_not_raised():
    ext = ingest.lonlat_extent([(b"\x00\x01not xml", "junk.gpx"),
                                (KML_MIN, "b.kml")])
    assert ext["bbox"] is not None            # the good file still counts


# ---- run_build: subprocess orchestration against stub scripts (no network) ----

import json as _json
import sys


def _write_stub_prep(tmp_path, body):
    """A stand-in region_prep.py: same argv contract, controllable behavior."""
    p = tmp_path / "stub_prep.py"
    p.write_text(
        "import argparse, os, sys, json\n"
        "ap = argparse.ArgumentParser()\n"
        "for a in ('--id','--name','--epsg'): ap.add_argument(a, required=True)\n"
        "ap.add_argument('--bbox', nargs=4, type=float, required=True)\n"
        "args = ap.parse_args()\n" + body)
    return str(p)

STUB_OK = """
out = os.path.join(os.environ['STUB_REGIONS_ROOT'], args.id)
os.makedirs(out, exist_ok=True)
print('Build plan: 10 m (auto) -> grid 100x100')
print('Fetching NHD hydrography...')
json.dump({'name': args.name, 'id': args.id}, open(os.path.join(out, 'region.json'), 'w'))
open(os.path.join(out, 'overview.png'), 'wb').write(b'png')
print('done')
"""

STUB_FAIL = """
out = os.path.join(os.environ['STUB_REGIONS_ROOT'], args.id)
os.makedirs(out, exist_ok=True)
open(os.path.join(out, 'region.json'), 'w').write('{}')   # partial output
print('Build plan: ...')
print('Fetching NHD hydrography...')
sys.exit(3)
"""


def _write_stub_labels(tmp_path, ok=True):
    p = tmp_path / "stub_labels.py"
    p.write_text("import sys\nsys.exit(0)\n" if ok else "import sys\nsys.exit(1)\n")
    return str(p)


def _params():
    return {"id": "stub_region", "name": "Stub Region",
            "bbox": (-120.9, 40.3, -120.5, 40.8), "epsg": 32610}


def test_run_build_streams_progress_and_returns(tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_REGIONS_ROOT", str(tmp_path / "regions"))
    lines = []
    res = rb.run_build(_params(), repo_root=".",
                       regions_root=str(tmp_path / "regions"),
                       prep_python=sys.executable,
                       prep_script=_write_stub_prep(tmp_path, STUB_OK),
                       labels_script=_write_stub_labels(tmp_path, ok=True),
                       set_progress=lines.append)
    assert res["labels_note"] is None
    assert any("hydrography" in l for l in lines)
    assert (tmp_path / "regions" / "stub_region" / "region.json").exists()


def test_run_build_failure_cleans_partial_and_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_REGIONS_ROOT", str(tmp_path / "regions"))
    with pytest.raises(RuntimeError) as ei:
        rb.run_build(_params(), repo_root=".",
                     regions_root=str(tmp_path / "regions"),
                     prep_python=sys.executable,
                     prep_script=_write_stub_prep(tmp_path, STUB_FAIL),
                     labels_script=_write_stub_labels(tmp_path),
                     set_progress=lambda s: None)
    assert "hydrography" in str(ei.value)          # tail lines ride the error
    assert not (tmp_path / "regions" / "stub_region").exists()   # partial swept


def test_run_build_labels_failure_is_nonfatal(tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_REGIONS_ROOT", str(tmp_path / "regions"))
    res = rb.run_build(_params(), repo_root=".",
                       regions_root=str(tmp_path / "regions"),
                       prep_python=sys.executable,
                       prep_script=_write_stub_prep(tmp_path, STUB_OK),
                       labels_script=_write_stub_labels(tmp_path, ok=False),
                       set_progress=lambda s: None)
    assert res["labels_note"]                       # note, not an exception
    assert (tmp_path / "regions" / "stub_region").exists()
