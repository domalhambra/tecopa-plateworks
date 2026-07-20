# /api/regions/plan + /api/regions/build against stub scripts (no network).
import io
import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import regions as regions_mod

client = TestClient(main.app)

GPX_ALPS = b"""<?xml version="1.0"?>
<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">
 <trk><name>Haute Route</name><trkseg>
  <trkpt lat="45.9" lon="6.9"/><trkpt lat="45.95" lon="7.0"/>
 </trkseg></trk></gpx>"""


def _plan(files):
    return client.post("/api/regions/plan",
                       files=[("files", (n, io.BytesIO(d), "application/gpx+xml"))
                              for d, n in files])


def test_plan_in_us_returns_estimate_and_prefill():
    data = open("tests/fixtures/sample.gpx", "rb").read()
    r = _plan([(data, "sample.gpx")])
    assert r.status_code == 200
    j = r.json()
    assert j["us_covered"] is True
    assert j["epsg"] == 32610                      # Lassen -> UTM 10N
    assert j["name_prefill"] == "Susanville to Eagle Lake 2024-06-01"
    assert j["id"] and j["id"] not in main.REGIONS  # collision-checked slug
    assert j["resolution_m"] in (10, 30, 60)
    assert j["grid"][0] > 0 and j["est_dem_mb"] > 0
    assert "transform" not in j                    # not JSON-serializable; never leaks

def test_plan_outside_us_is_honest():
    r = _plan([(GPX_ALPS, "alps.gpx")])
    assert r.status_code == 200
    j = r.json()
    assert j["us_covered"] is False

def test_plan_no_points_is_422():
    r = _plan([(b"<gpx></gpx>", "empty.gpx")])
    assert r.status_code == 422

def test_plan_reports_prep_readiness(monkeypatch):
    monkeypatch.setattr(main, "PREP_PYTHON", "/nonexistent/python")
    data = open("tests/fixtures/sample.gpx", "rb").read()
    assert _plan([(data, "sample.gpx")]).json()["prep_ready"] is False


# ---- build ----

def _stub_env(tmp_path, monkeypatch, prep_body_ok=True):
    regions_root = tmp_path / "regions"
    regions_root.mkdir()
    monkeypatch.setenv("STUB_REGIONS_ROOT", str(regions_root))
    monkeypatch.setattr(main, "REGIONS_ROOT", str(regions_root))
    prep = tmp_path / "prep.py"
    ok_body = (
        "import argparse, os, json\n"
        "ap = argparse.ArgumentParser()\n"
        "for a in ('--id','--name','--epsg'): ap.add_argument(a, required=True)\n"
        "ap.add_argument('--bbox', nargs=4, type=float, required=True)\n"
        "a = ap.parse_args()\n"
        "out = os.path.join(os.environ['STUB_REGIONS_ROOT'], a.id)\n"
        "os.makedirs(out, exist_ok=True)\n"
        "print('Build plan: stub')\n")
    if prep_body_ok:
        # region.json must satisfy regions.Region(); copy a real one and re-name it.
        ok_body += (
            "cfg = json.load(open('regions/susanville_reno/region.json'))\n"
            "cfg['name'] = a.name\n"
            "json.dump(cfg, open(os.path.join(out, 'region.json'), 'w'))\n"
            "open(os.path.join(out, 'overview.png'), 'wb').write(b'x')\n")
    else:
        ok_body += "import sys; sys.exit(3)\n"
    prep.write_text(ok_body)
    labels = tmp_path / "labels.py"
    labels.write_text("import sys\nsys.exit(0)\n")
    monkeypatch.setattr(main, "PREP_PYTHON", sys.executable)
    monkeypatch.setattr(main, "PREP_SCRIPT", str(prep))
    monkeypatch.setattr(main, "LABELS_SCRIPT", str(labels))
    return regions_root


def _wait_done(jid, timeout=15):
    for _ in range(timeout * 10):
        st = client.get(f"/api/regions/build/{jid}").json()
        if st["state"] in ("done", "error"):
            return st
        time.sleep(0.1)
    raise AssertionError("build job never finished")


BUILD_REQ = {"id": "stub_built", "name": "Stub Built",
             "bbox": [-120.9, 40.3, -120.5, 40.8], "epsg": 32610}


def test_build_end_to_end_hot_reloads_registry(tmp_path, monkeypatch):
    _stub_env(tmp_path, monkeypatch)
    saved = dict(main.REGIONS)
    try:
        r = client.post("/api/regions/build", json=BUILD_REQ)
        assert r.status_code == 200
        st = _wait_done(r.json()["job"])
        assert st["state"] == "done", st
        assert "stub_built" in main.REGIONS         # in-place hot reload
    finally:
        main.REGIONS.clear(); main.REGIONS.update(saved)


def test_build_failure_surfaces_error(tmp_path, monkeypatch):
    _stub_env(tmp_path, monkeypatch, prep_body_ok=False)
    saved = dict(main.REGIONS)
    try:
        r = client.post("/api/regions/build", json=BUILD_REQ)
        st = _wait_done(r.json()["job"])
        assert st["state"] == "error"
        assert "exit 3" in st["error"]
    finally:
        main.REGIONS.clear(); main.REGIONS.update(saved)


def test_build_rejects_bad_id_us_and_collision(tmp_path, monkeypatch):
    _stub_env(tmp_path, monkeypatch)
    bad = dict(BUILD_REQ, id="Bad Id!")
    assert client.post("/api/regions/build", json=bad).status_code == 422
    alps = dict(BUILD_REQ, bbox=[7.0, 45.8, 7.9, 46.2])
    assert client.post("/api/regions/build", json=alps).status_code == 422
    taken = dict(BUILD_REQ, id=next(iter(main.REGIONS)))
    assert client.post("/api/regions/build", json=taken).status_code == 409

def test_build_unknown_job_404():
    assert client.get("/api/regions/build/nope").status_code == 404


def test_build_rejects_over_budget_bbox():
    # A US-covered but corridor-scale box: bbox_covered passes, but plan_build's
    # auto path is over budget even at 60 m -> 422, before any job is submitted.
    huge = {"id": "conus_scale", "name": "Too Big",
            "bbox": [-125.4, 24.4, -66.9, 49.4], "epsg": 32614}
    r = client.post("/api/regions/build", json=huge)
    assert r.status_code == 422
    assert "corridor-scale" in r.json()["detail"]


def test_build_rejects_bad_epsg():
    # epsg is only int-typed; an out-of-UTM value would 500 in plan_build -> reject 422.
    bad = dict(BUILD_REQ, epsg=0)
    r = client.post("/api/regions/build", json=bad)
    assert r.status_code == 422
    assert "UTM" in r.json()["detail"]


def test_plan_rejects_oversize_upload(monkeypatch):
    monkeypatch.setattr(main, "TRACK_FILE_MAX_BYTES", 64)
    big = b"<gpx>" + b"x" * 200 + b"</gpx>"
    r = _plan([(big, "big.gpx")])
    assert r.status_code == 422
    assert "size limit" in r.json()["detail"]


def test_build_streams_progress_to_status(tmp_path, monkeypatch):
    # Exercise the endpoint's real progress glue (holder -> BUILD_QUEUE.set_progress):
    # a stub that emits a marker then blocks, so the status poll can observe it.
    regions_root = tmp_path / "regions"
    regions_root.mkdir()
    monkeypatch.setenv("STUB_REGIONS_ROOT", str(regions_root))
    monkeypatch.setattr(main, "REGIONS_ROOT", str(regions_root))
    prep = tmp_path / "prep.py"
    prep.write_text(
        "import argparse, os, json, time\n"
        "ap = argparse.ArgumentParser()\n"
        "for a in ('--id','--name','--epsg'): ap.add_argument(a, required=True)\n"
        "ap.add_argument('--bbox', nargs=4, type=float, required=True)\n"
        "a = ap.parse_args()\n"
        "out = os.path.join(os.environ['STUB_REGIONS_ROOT'], a.id)\n"
        "os.makedirs(out, exist_ok=True)\n"
        "print('STREAM_MARKER', flush=True)\n"
        "time.sleep(1.2)\n"
        "cfg = json.load(open('regions/susanville_reno/region.json'))\n"
        "cfg['name'] = a.name\n"
        "json.dump(cfg, open(os.path.join(out, 'region.json'), 'w'))\n"
        "open(os.path.join(out, 'overview.png'), 'wb').write(b'x')\n")
    labels = tmp_path / "labels.py"
    labels.write_text("import sys\nsys.exit(0)\n")
    monkeypatch.setattr(main, "PREP_PYTHON", sys.executable)
    monkeypatch.setattr(main, "PREP_SCRIPT", str(prep))
    monkeypatch.setattr(main, "LABELS_SCRIPT", str(labels))
    saved = dict(main.REGIONS)
    try:
        jid = client.post("/api/regions/build",
                          json=dict(BUILD_REQ, id="stream_test")).json()["job"]
        saw = False
        for _ in range(60):
            prog = client.get(f"/api/regions/build/{jid}").json()["progress"]
            if prog and "STREAM_MARKER" in prog:
                saw = True
                break
            time.sleep(0.1)
        assert saw, "progress never reflected the streamed prep output"
        assert _wait_done(jid)["state"] == "done"
    finally:
        main.REGIONS.clear(); main.REGIONS.update(saved)
