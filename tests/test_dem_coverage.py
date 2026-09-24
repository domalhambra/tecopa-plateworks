# tests/test_dem_coverage.py
# Coverage is what keeps an order honest: the 3DEP dynamic service fills gaps in a
# fine layer with resampled coarse data and says nothing. The pure fraction runs in
# CI; the network query is checked by hand on the Mac (plan Task 4).
import subprocess
import sys

import pytest
from shapely.geometry import box

rp = pytest.importorskip("region_prep")
BBOX = (0.0, 0.0, 2.0, 1.0)


def test_full_cover():
    assert rp.coverage_fraction([box(-1, -1, 3, 2)], BBOX) == pytest.approx(1.0)


def test_half_cover_from_two_overlapping_footprints():
    parts = [box(0, 0, 0.8, 1), box(0.5, 0, 1.0, 1)]      # union is x 0..1
    assert rp.coverage_fraction(parts, BBOX) == pytest.approx(0.5)


def test_no_cover():
    assert rp.coverage_fraction([box(5, 5, 6, 6)], BBOX) == 0.0
    assert rp.coverage_fraction([], BBOX) == 0.0


def test_cli_usage_error_exits_2():
    out = subprocess.run([sys.executable, "scripts/dem_coverage.py", "1", "2"],
                         capture_output=True, text=True)
    assert out.returncode == 2
    assert "usage" in out.stderr


# ---- the index query: Esri rings, and a failed query never reads as 0.0 ----
import io
import json
import urllib.error
import urllib.request

CW_OUTER = [[0, 0], [0, 4], [4, 4], [4, 0], [0, 0]]         # clockwise: outer
CCW_HOLE = [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]         # counter-clockwise: hole


def test_esri_ring_with_a_hole():
    g = rp.esri_rings_to_geom([CW_OUTER, CCW_HOLE])
    assert g.area == pytest.approx(16 - 1)


def test_esri_two_disjoint_outers():
    other = [[10, 0], [10, 2], [12, 2], [12, 0], [10, 0]]   # clockwise
    g = rp.esri_rings_to_geom([CW_OUTER, other])
    assert g.area == pytest.approx(16 + 4)


def _fake_urlopen(bodies):
    """urlopen stand-in that answers each call with the next body; an Exception
    in the list is raised instead."""
    calls = []

    def urlopen(url, context=None, timeout=None):
        calls.append(url)
        body = bodies[len(calls) - 1]
        if isinstance(body, Exception):
            raise body
        return io.BytesIO(json.dumps(body).encode())
    return urlopen, calls


def test_no_features_is_zero_and_the_query_is_simplified(monkeypatch):
    urlopen, calls = _fake_urlopen([{"features": []}] * len(rp.COVERAGE_LAYERS_M))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    cov = rp.layer_coverage((-116.27, 35.88, -116.24, 35.91))
    assert cov == {r: 0.0 for r in rp.COVERAGE_LAYERS_M}
    assert all("maxAllowableOffset=0.0005" in u for u in calls)
    assert "/MapServer/18/query" in calls[0]                 # 1 m layer


def test_footprint_is_measured(monkeypatch):
    square = [[-116.27, 35.88], [-116.27, 35.91], [-116.24, 35.91],
              [-116.24, 35.88], [-116.27, 35.88]]           # clockwise, the whole bbox
    full = {"features": [{"attributes": {"OBJECTID": 1},
                          "geometry": {"rings": [square]}}]}
    urlopen, _ = _fake_urlopen([full] * len(rp.COVERAGE_LAYERS_M))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    cov = rp.layer_coverage((-116.27, 35.88, -116.24, 35.91))
    assert cov[1] == pytest.approx(1.0)


@pytest.mark.parametrize("body", [
    {"error": {"code": 400, "message": "Error performing query operation"}},
    {"features": [], "exceededTransferLimit": True},
])
def test_a_failed_query_raises_not_zero(monkeypatch, body):
    urlopen, _ = _fake_urlopen([body, body])
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(RuntimeError, match="1 m"):
        rp.layer_coverage((0.0, 0.0, 1.0, 1.0))


def test_a_5xx_is_retried_once_then_raises(monkeypatch):
    err = urllib.error.HTTPError("u", 500, "Error performing query operation", {}, None)
    urlopen, calls = _fake_urlopen([err, err])
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(RuntimeError, match="HTTP 500"):
        rp.layer_coverage((0.0, 0.0, 1.0, 1.0))
    assert len(calls) == 2


def test_a_5xx_then_success_recovers(monkeypatch):
    err = urllib.error.HTTPError("u", 503, "busy", {}, None)
    bodies = [err] + [{"features": []}] * len(rp.COVERAGE_LAYERS_M)
    urlopen, _ = _fake_urlopen(bodies)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert rp.layer_coverage((0.0, 0.0, 1.0, 1.0))[1] == 0.0


def _cw_square(x0, y0, x1, y1):
    return [[x0, y0], [x0, y1], [x1, y1], [x1, y0], [x0, y0]]


def _ccw_square(x0, y0, x1, y1):
    return list(reversed(_cw_square(x0, y0, x1, y1)))


def test_esri_island_inside_a_hole_is_kept():
    rings = [_cw_square(0, 0, 10, 10),          # outer, 100
             _ccw_square(2, 2, 8, 8),           # hole, 36
             _cw_square(4, 4, 6, 6)]            # island in the hole, 4
    assert rp.esri_rings_to_geom(rings).area == pytest.approx(100 - 36 + 4)


def test_esri_hole_only_cuts_its_own_outer():
    # a second outer overlapping the first's hole is not cut by that hole
    rings = [_cw_square(0, 0, 10, 10), _ccw_square(2, 2, 8, 8),
             _cw_square(20, 0, 30, 10)]
    assert rp.esri_rings_to_geom(rings).area == pytest.approx(64 + 100)


def test_esri_all_counter_clockwise_rings_are_outers():
    # some servers flip orientation: with no clockwise ring, every ring is an outer
    rings = [_ccw_square(0, 0, 4, 4), _ccw_square(10, 0, 12, 2)]
    assert rp.esri_rings_to_geom(rings).area == pytest.approx(16 + 4)


def test_esri_self_intersecting_outer_is_repaired():
    bowtie = [[0, 0], [0, 2], [2, 0], [2, 2], [0, 0]]   # two triangles, 1 each
    g = rp.esri_rings_to_geom([bowtie])
    assert g.is_valid and g.area == pytest.approx(2.0)
