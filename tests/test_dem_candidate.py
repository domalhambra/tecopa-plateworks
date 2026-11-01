# tests/test_dem_candidate.py
# A candidate DEM is built on the plate's committed grid and outside regions/, so it can
# be compared before anything is swapped.
import json
import os

import numpy as np
import pytest

pytest.importorskip("region_prep")
rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin  # noqa: E402

from app import relief  # noqa: E402
from scripts import dem_candidate as dc  # noqa: E402

BBOX = [-106.85, 39.10, -106.79, 39.15]
BOUNDS = [317000.0, 4331000.0, 321000.0, 4335000.0]     # off plan_build's own grid


def _plate(root, rid="p"):
    d = os.path.join(root, rid)
    os.makedirs(d)
    with open(os.path.join(d, "region.json"), "w") as f:
        json.dump({"id": rid, "crs": "EPSG:32613", "bounds": BOUNDS, "native_resolution_m": 10,
                   "elevation_min": 2000.0, "elevation_max": 3000.0}, f)
    with open(os.path.join(d, "sources.json"), "w") as f:
        json.dump({"fetch_bbox_4326": BBOX}, f)
    return d


def _tif(path, a):
    with rasterio.open(path, "w", driver="GTiff", dtype="float32", count=1, height=a.shape[0],
                       width=a.shape[1], crs="EPSG:32613", nodata=np.nan,
                       transform=from_origin(BOUNDS[0], BOUNDS[3], 10, 10)) as d:
        d.write(a.astype("float32"), 1)
    return path


def test_committed_plan_uses_the_grid_in_region_json(tmp_path):
    bbox, crs, plan = dc.committed_plan(_plate(str(tmp_path)))
    assert list(bbox) == BBOX and crs == "EPSG:32613"
    assert plan["grid"] == (400, 400)
    t = plan["transform"]
    assert (t.c, t.f, t.a, -t.e) == (BOUNDS[0], BOUNDS[3], 10, 10)


def test_candidate_refuses_to_write_into_regions(tmp_path, capsys):
    root = tmp_path / "regions"
    root.mkdir()
    _plate(str(root))
    out = root / "p" / "candidate"
    assert dc.main(["p", "--out", str(out), "--regions-root", str(root)]) == 2
    assert not out.exists()
    assert "outside" in capsys.readouterr().err


def test_compare_reports_overshoot_above_elevation_max(tmp_path):
    a = 2500.0 + np.zeros((400, 400))
    b = a.copy()
    b[10, 10] = 3002.0
    old, new = _tif(str(tmp_path / "o.tif"), a), _tif(str(tmp_path / "n.tif"), b)
    c = dc.compare(old, new, {"elevation_max": 3000.0})
    assert c["over_max_share"] == pytest.approx(1 / 160000)
    assert c["new_max"] == 3002.0 and c["new_min"] == 2500.0
    assert c["rms_m"] > 0 and c["old_scan"]["valid"] == c["new_scan"]["valid"]


def test_a_summit_above_elevation_max_renders():
    # region.json keeps its range on a rebuild, so Lanczos overshoot lands above it.
    y, x = np.indices((200, 200), dtype="float32")
    e = 2800.0 + 180.0 * np.exp(-((x - 100) ** 2 + (y - 100) ** 2) / 900.0)
    over = e.copy()
    over[e > 2978.0] += 2.0                 # above elevation_max = 2980 at the very top
    assert over.max() > 2980.0
    kw = dict(seed=7, shadow=0.5, shadow_res_m=10.0)
    base = np.asarray(relief.shaded_relief(e, 10, 2000.0, 2980.0, **kw), "float32")
    hot = np.asarray(relief.shaded_relief(over, 10, 2000.0, 2980.0, **kw), "float32")
    assert np.isfinite(hot).all()
    top = e > 2970.0
    assert np.abs(hot[top].mean(0) - base[top].mean(0)).max() < 0.08 * max(1.0, base.max())
