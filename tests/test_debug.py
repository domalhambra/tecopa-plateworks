# tests/test_debug.py
# The read-only debug routes behind TECOPA_DEBUG=1 (the `tecopa` tool reads them).
# The router is built on a small app of its own here, so the gate-on shape is tested
# without re-importing app.main. The gate-off shape is tested on the live app.
import time
import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app import basecache, debug, jobs, session
from app.ingest import Track
from app.spec import CompositionSpec
from starlette.requests import Request


def _client():
    q = jobs.ThreadJobQueue(max_concurrency=2)
    app = FastAPI()
    app.include_router(debug.build_router(
        queues={"render": q}, caches={"base": basecache.BaseCache(1000)},
        started=time.time() - 5))
    # the routes answer only a local Host header, and TestClient's default is "testserver"
    return TestClient(app, base_url="http://127.0.0.1"), q


def _track():
    return Track("t-0", np.array([[1100.0, 2100.0], [3900.0, 5900.0]]), "2024-06-01")


def _make_session(with_spec=False):
    t = _track()
    spec = None
    if with_spec:
        spec = CompositionSpec(region_id="lassen_ca", crs="EPSG:32610",
                               crop=(1000.0, 2000.0, 4000.0, 6000.0),
                               print_w_in=9, print_h_in=12, native_resolution_m=10,
                               tracks=[t.coords], hotspots=[], seed=7,
                               title_text="LASSEN")
    return session.create({"region_id": "lassen_ca", "tracks": [t],
                           "hotspots": [{"x": 1.0, "y": 2.0, "weight": 1, "label": "Camp"}],
                           "spec": spec})


def test_gate_reads_only_the_exact_value():
    assert debug.enabled({"TECOPA_DEBUG": "1"})
    assert not debug.enabled({})
    assert not debug.enabled({"TECOPA_DEBUG": "0"})
    assert not debug.enabled({"TECOPA_DEBUG": "true"})


def test_gate_off_means_the_live_app_has_no_debug_routes():
    # conftest removes TECOPA_DEBUG, so app.main was imported with the gate off
    from app.main import app
    r = TestClient(app).get("/api/debug/engine")
    assert r.status_code == 404
    # the tecopa tool reads this exact body to say "the debug routes are off"
    assert r.json() == {"detail": "Not Found"}


def test_engine_reports_identity_and_queue_widths():
    c, _ = _client()
    body = c.get("/api/debug/engine").json()
    assert body["engine"] == "tecopa-plateworks"
    assert body["engine_version"]
    assert body["queues"] == {"render": 2}
    assert body["uptime_s"] >= 5
    assert body["pid"] > 0
    assert body["store"] in ("MemoryStore", "SqliteStore")
    assert all(k.startswith("TECOPA_") for k in body["env"])


def test_jobs_lists_each_queue_without_results():
    c, q = _client()
    jid = q.submit(lambda: "secret-result")
    deadline = time.time() + 5
    while q.status(jid)["state"] != "done" and time.time() < deadline:
        time.sleep(0.01)
    rows = c.get("/api/debug/jobs").json()["jobs"]
    assert len(rows) == 1
    assert rows[0]["queue"] == "render" and rows[0]["jid"] == jid
    assert rows[0]["state"] == "done" and "result" not in rows[0]


def test_sessions_lists_a_summary_row():
    c, _ = _client()
    sid = _make_session()
    rows = {r["sid"]: r for r in c.get("/api/debug/sessions").json()["sessions"]}
    assert rows[sid] == {"sid": sid, "region_id": "lassen_ca", "tracks": 1,
                         "hotspots": 1, "has_spec": False}


def test_session_detail_holds_no_geometry_unless_asked():
    c, _ = _client()
    sid = _make_session(with_spec=True)
    body = c.get(f"/api/debug/sessions/{sid}").json()
    assert body["tracks"] == [{"track_id": "t-0", "points": 2, "day": "2024-06-01"}]
    assert body["spec"]["title_text"] == "LASSEN"
    assert body["spec"]["tracks"] == 1          # a count, never the coordinates
    assert "coords" not in str(body)
    assert "1100.0" not in str(body) and "5900.0" not in str(body)
    assert body["hotspots"][0]["label"] == "Camp"   # the user's own labelled points stay


def test_session_detail_full_returns_the_geometry():
    c, _ = _client()
    sid = _make_session(with_spec=True)
    assert c.get(f"/api/debug/sessions/{sid}?full=true").status_code == 200
    full = c.get(f"/api/debug/sessions/{sid}?full=1").json()
    assert full["tracks"][0]["coords"] == [[1100.0, 2100.0], [3900.0, 5900.0]]
    assert full["spec"]["tracks"] == [[[1100.0, 2100.0], [3900.0, 5900.0]]]


def test_unknown_session_is_a_404_that_names_the_cause():
    c, _ = _client()
    r = c.get("/api/debug/sessions/nope")
    assert r.status_code == 404 and r.json()["detail"] == "Unknown session"


def test_caches_reports_each_cache():
    c, _ = _client()
    body = c.get("/api/debug/caches").json()
    assert body == {"base": {"entries": 0, "bytes": 0, "max_bytes": 1000,
                             "hits": 0, "misses": 0}}


LOCAL_ONLY = "Debug routes answer only a local Host header."


def test_a_foreign_host_header_is_refused_on_every_route():
    # a page that uses DNS rebinding reaches 127.0.0.1 with its own Host header
    c, _ = _client()
    sid = _make_session(with_spec=True)
    for path in ("/engine", "/jobs", "/sessions", "/sessions/x?full=1",
                 f"/sessions/{sid}?full=1", "/caches"):
        r = c.get("/api/debug" + path, headers={"Host": "attacker.example:8848"})
        assert r.status_code == 403, path
        # 403 and not 404: the tecopa tool reads a 404 "Not Found" as "the gate is off"
        assert r.json() == {"detail": LOCAL_ONLY}, path
        assert "1100.0" not in r.text, path


@pytest.mark.parametrize("host", ["localhost:8848", "127.0.0.1", "[::1]:8848",
                                  "127.0.0.1:8848", "localhost", "[::1]",
                                  "LOCALHOST:8848"])
def test_a_local_host_header_is_answered(host):
    c, _ = _client()
    assert c.get("/api/debug/engine", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["attacker.example", "127.0.0.1.attacker.example",
                                  "localhost.attacker.example:8848", "::1",
                                  "[::1]x:8848", "[::1].attacker.example",
                                  "127.0.0.1:8848:1", "localhost:", "127.0.0.2",
                                  "0.0.0.0:8848", "testserver", ""])
def test_a_host_header_that_only_looks_local_is_refused(host):
    c, _ = _client()
    r = c.get("/api/debug/engine", headers={"Host": host})
    assert r.status_code == 403 and r.json() == {"detail": LOCAL_ONLY}


def test_a_request_with_no_host_header_is_refused():
    # httpx always sends a Host header, so the dependency is called directly
    with pytest.raises(HTTPException) as refused:
        debug._local_host_only(Request({"type": "http", "headers": []}))
    assert refused.value.status_code == 403 and refused.value.detail == LOCAL_ONLY
