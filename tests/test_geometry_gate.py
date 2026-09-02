# tests/test_geometry_gate.py
# The DEM geometry gate: a plate whose dem.tif no longer matches its region.json must
# refuse to render with a 503 that names the drift. This is the pull-orphan failure
# (CLAUDE.md § Known local failures): a cloud plate rebuild ships region.json to main,
# the gitignored DEM stays behind, and the next pull pairs new bounds with old terrain.
# Before this gate the poster painted with no error, just wrong. Every test CONSTRUCTS
# its drift in tmp_path (tests/test_plates.py rule: never inherit drift from the host).
import io
import os

import numpy as np
import pytest
import rasterio
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pyproj import Transformer
from rasterio.transform import from_bounds

import app.main as main
from app import regions
from tests.test_readyz import _write_region

client = TestClient(main.app)

GOOD = (600000.0, 4400000.0, 610000.0, 4410000.0)        # UTM 10N, 10 km square
SHIFTED = (605000.0, 4405000.0, 615000.0, 4415000.0)     # the DEM moved 5 km -> orphan
FAR = (300000.0, 4000000.0, 310000.0, 4010000.0)         # a second plate, nowhere near
CRS = "EPSG:32610"


def _gpx_inside(bounds, n=12):
    """A GPX track walking the middle of `bounds`, in lon/lat, with timestamps."""
    w, s, e, nn = bounds
    tr = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    pts = []
    for i in range(n):
        f = 0.2 + 0.6 * i / (n - 1)
        lon, lat = tr.transform(w + f * (e - w), s + f * (nn - s))
        pts.append(f'<trkpt lat="{lat:.6f}" lon="{lon:.6f}">'
                   f'<time>2024-06-01T10:{i:02d}:00Z</time></trkpt>')
    body = ("<?xml version=\"1.0\"?><gpx version=\"1.1\" creator=\"t\" "
            "xmlns=\"http://www.topografix.com/GPX/1/1\"><trk><name>t</name><trkseg>"
            + "".join(pts) + "</trkseg></trk></gpx>")
    return body.encode()


def _upload(gpx, **fields):
    return client.post("/api/upload",
                       files=[("files", ("t.gpx", io.BytesIO(gpx), "application/gpx+xml"))],
                       data=fields)


def _rewrite_dem(region_dir, bounds):
    """Overwrite the plate's DEM with one covering `bounds` -- the orphan, in place."""
    prof = dict(driver="GTiff", dtype="float32", count=1, height=20, width=20,
                crs=CRS, transform=from_bounds(*bounds, 20, 20), nodata=np.nan)
    with rasterio.open(os.path.join(region_dir, "dem.tif"), "w", **prof) as ds:
        ds.write(np.full((20, 20), 1500.0, "float32"), 1)


@pytest.fixture
def plates(tmp_path):
    """Install tmp plates into main.REGIONS for one test; restore the real registry after.
    Yields a function: install(rid=Region, ...) replaces the registry with exactly those."""
    saved = dict(main.REGIONS)

    def install(**by_id):
        main.REGIONS.clear()
        main.REGIONS.update(by_id)
    try:
        yield install
    finally:
        main.REGIONS.clear()
        main.REGIONS.update(saved)


def _plate(tmp_path, rid, cfg_bounds, dem_bounds):
    _write_region(str(tmp_path), rid, cfg_bounds, dem_bounds, crs=CRS)
    return regions.Region(rid, root=str(tmp_path))


def test_explicit_plate_with_drifted_dem_is_503_naming_the_drift(tmp_path, plates):
    plates(orphan=_plate(tmp_path, "orphan", GOOD, SHIFTED))
    r = _upload(_gpx_inside(GOOD), region_id="orphan")
    assert r.status_code == 503, r.text
    d = r.json()["detail"]
    assert d.startswith("Plate orphan can't render:")
    assert "5000.00 m" in d and "region.json" in d
    assert "verify_regions.py" in d


def test_healthy_plate_still_uploads(tmp_path, plates):
    plates(good=_plate(tmp_path, "good", GOOD, GOOD))
    r = _upload(_gpx_inside(GOOD), region_id="good")
    assert r.status_code == 200, r.text
    assert r.json()["region"] == "good"


def test_the_orphan_sequence_upload_then_swap_then_proof(tmp_path, plates):
    """The real failure: the session was bound BEFORE the pull swapped the DEM."""
    good = _plate(tmp_path, "good", GOOD, GOOD)
    plates(good=good)
    sid = _upload(_gpx_inside(GOOD), region_id="good").json()["session"]
    _rewrite_dem(good.dir, SHIFTED)                      # the pull lands
    r = client.post("/api/proof", data={"session_id": sid, "x0": 10, "y0": 10,
                                        "x1": 60, "y1": 80})
    assert r.status_code == 503, r.text
    assert r.json()["detail"].startswith("Plate good can't render:")


def test_missing_dem_is_503_not_500(tmp_path, plates):
    _write_region(str(tmp_path), "nodem", GOOD, GOOD, crs=CRS, with_dem=False)
    plates(nodem=regions.Region("nodem", root=str(tmp_path)))
    r = _upload(_gpx_inside(GOOD), region_id="nodem")
    assert r.status_code == 503, r.text
    assert "DEM is missing" in r.json()["detail"]


def test_auto_detect_into_a_drifted_plate_is_the_drift_503_not_a_no_region_422(tmp_path, plates):
    """Two plates, the tracks land in the drifted one. The winner must be gated: the
    operator needs 'this plate drifted', not 'tracks fall in no region'."""
    plates(orphan=_plate(tmp_path, "orphan", GOOD, SHIFTED),
           far=_plate(tmp_path, "far", FAR, FAR))
    r = _upload(_gpx_inside(GOOD))                       # no region_id -> auto-detect
    assert r.status_code == 503, r.text
    assert r.json()["detail"].startswith("Plate orphan can't render:")


def test_single_plate_branch_is_gated(tmp_path, plates):
    plates(orphan=_plate(tmp_path, "orphan", GOOD, SHIFTED))
    r = _upload(_gpx_inside(GOOD))                       # one plate -> the sole-plate branch
    assert r.status_code == 503, r.text
    assert r.json()["detail"].startswith("Plate orphan can't render:")


def test_auto_recovery_into_a_drifted_plate_is_gated(tmp_path, plates):
    """Operator picked 'far', the tracks are really in 'orphan': recovery switches to
    the drifted plate and must refuse there, not paint."""
    plates(orphan=_plate(tmp_path, "orphan", GOOD, SHIFTED),
           far=_plate(tmp_path, "far", FAR, FAR))
    r = _upload(_gpx_inside(GOOD), region_id="far")
    assert r.status_code == 503, r.text
    assert r.json()["detail"].startswith("Plate orphan can't render:")


def test_manifest_region_gate_refuses_a_drifted_plate_before_the_pack_check(tmp_path, plates):
    """Reprint and continue resolve their plate here. Geometry is checked BEFORE the
    pack-version comparison, so allow_plate_mismatch can never walk past an orphan."""
    from types import SimpleNamespace
    plates(orphan=_plate(tmp_path, "orphan", GOOD, SHIFTED))
    spec = SimpleNamespace(region_id="orphan", labels=False, biome=False, dry_lakes=False)
    with pytest.raises(HTTPException) as ei:
        main._manifest_region_or_422(spec, "reprinted", manifest=None,
                                     allow_plate_mismatch=True)
    assert ei.value.status_code == 503
    assert ei.value.detail.startswith("Plate orphan can't render:")
