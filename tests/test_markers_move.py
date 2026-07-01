# tests/test_markers_move.py
# Non-gated: the move endpoint is pure geo (no DEM/rasterize), so these run on a
# fresh clone. The spec-invalidation happy-path (needs a stamped proof -> DEM) lives
# in the DEM-gated tests/test_main.py.
from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app)


def _upload(c):
    files = [("files", ("a.gpx", open("tests/fixtures/sample.gpx", "rb").read(),
                        "application/gpx+xml"))]
    r = c.post("/api/upload", files=files)
    assert r.status_code == 200
    return r.json()


def test_move_returns_ok_and_snapped_px():
    c = _client(); j = _upload(c)
    w, h = j["overview_size"]
    r = c.post("/api/markers/move", data={"session_id": j["session"], "i": 0,
               "px": w * 0.5, "py": h * 0.5})
    assert r.status_code == 200
    out = r.json()
    assert out["ok"] is True
    # a point well inside bounds round-trips unchanged (linear px<->crs map)
    assert abs(out["px"] - w * 0.5) < 1e-6
    assert abs(out["py"] - h * 0.5) < 1e-6


def test_move_clamps_out_of_bounds():
    c = _client(); j = _upload(c)
    w, h = j["overview_size"]
    r = c.post("/api/markers/move", data={"session_id": j["session"], "i": 0,
               "px": -500.0, "py": h + 500.0})
    assert r.status_code == 200
    out = r.json()
    # clamped back onto the region edge -> returned px/py inside [0, w] x [0, h]
    assert -1e-6 <= out["px"] <= w + 1e-6
    assert -1e-6 <= out["py"] <= h + 1e-6
    assert out["px"] > -500.0 and out["py"] < h + 500.0   # actually moved inward


def test_move_bad_index_422():
    c = _client(); j = _upload(c)
    r = c.post("/api/markers/move", data={"session_id": j["session"], "i": 999,
               "px": 10.0, "py": 10.0})
    assert r.status_code == 422


def test_move_unknown_session_404():
    c = _client()
    r = c.post("/api/markers/move",
               data={"session_id": "nope", "i": 0, "px": 1.0, "py": 1.0})
    assert r.status_code == 404
