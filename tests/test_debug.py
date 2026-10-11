# tests/test_debug.py
# The debug routes behind TECOPA_DEBUG=1 (the `tecopa` tool reads them). Each one is
# read-only except the studio post, and that one changes only the report buffer.
# The router is built on a small app of its own here, so the gate-on shape is tested
# without re-importing app.main. The gate-off shape is tested on the live app.
import ast
import asyncio
import inspect
import json
import logging
import time
import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app import basecache, debug, geo, jobs, main, serialize, session
from app.ingest import Track
from app.spec import CompositionSpec
from starlette.requests import Request


def _client():
    q = jobs.ThreadJobQueue(max_concurrency=2)
    app = FastAPI()
    app.include_router(debug.build_router(
        queues={"render": q}, caches={"base": basecache.BaseCache(1000)},
        started=time.time() - 5, forms=main.DEBUG_FORMS, regions=main.REGIONS,
        proof_form=main._proof_form_for, crop_px=main._crop_to_overview_px))
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


def _upload():
    # a real upload on the live app: the session store is shared, so the debug client
    # reads the same session, and the answer carries the crop the studio starts from
    files = [("files", ("a.gpx", open("tests/fixtures/sample.gpx", "rb").read(),
                        "application/gpx+xml"))]
    r = TestClient(main.app).post("/api/upload", files=files)
    assert r.status_code == 200, r.text
    return r.json()


def _frozen(sid):
    # the whole session as text, so a before and an after compare exactly
    data = dict(session.get(sid))
    data["tracks"] = [serialize.track_to_json(t) for t in data["tracks"]]
    if data.get("spec") is not None:
        data["spec"] = serialize.spec_to_json(data["spec"])
    return json.dumps(data, sort_keys=True)


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


FORM_ROUTES = {"proof": "/api/proof", "final_submit": "/api/final/submit",
               "wallpapers_submit": "/api/wallpapers/submit",
               "timelapse_submit": "/api/timelapse/submit",
               "reprint": "/api/reprint", "continue": "/api/continue"}


def test_forms_names_each_route_functions_fields_in_declaration_order():
    c, _ = _client()
    forms = c.get("/api/debug/forms").json()
    assert list(forms) == list(FORM_ROUTES)
    assert forms["proof"] == list(inspect.signature(main.proof).parameters)
    for name in ("session_id", "x0", "title", "print_w", "soft_light", "bleed"):
        assert name in forms["proof"], name
    assert forms["final_submit"] == ["session_id", "format", "embed_spec"]
    # a file parameter is a field too: the tool sends the file under this name
    assert forms["reprint"][0] == "file" and forms["continue"][0] == "file"
    for name, fn in main.DEBUG_FORMS.items():
        assert forms[name] == list(inspect.signature(fn).parameters), name


def test_forms_table_holds_the_function_each_route_runs():
    # The table holds the functions, not their names, so a rename with no table edit
    # is a NameError when app.main is imported. This holds the other half: an entry
    # that names a function its route no longer runs.
    posts = {r.path: r.endpoint for r in main.app.routes
             if "POST" in (getattr(r, "methods", None) or ())}
    assert main.DEBUG_FORMS == {name: posts[path] for name, path in FORM_ROUTES.items()}


def test_starter_crop_at_the_default_size_is_the_upload_answer():
    c, _ = _client()
    up = _upload()
    r = c.get(f"/api/debug/sessions/{up['session']}/starter_crop?print_w=17&print_h=22")
    assert r.status_code == 200, r.text
    assert r.json() == {"starter_crop": up["starter_crop"]}


def test_starter_crop_takes_the_shape_of_the_print_size():
    c, _ = _client()
    up = _upload()
    r = c.get(f"/api/debug/sessions/{up['session']}/starter_crop?print_w=11&print_h=17")
    x0, y0, x1, y1 = r.json()["starter_crop"]
    assert x0 < x1 and y0 < y1
    # the shape is judged on the ground, where the proof judges it
    region = main.REGIONS[up["region"]].geo
    left, top = geo.overview_px_to_crs(region, x0, y0)
    right, bottom = geo.overview_px_to_crs(region, x1, y1)
    assert abs((right - left) / (top - bottom) - 11 / 17) < 1e-6
    assert [x0, y0, x1, y1] != up["starter_crop"]


def test_starter_crop_of_an_unknown_session_is_a_404_that_names_the_cause():
    c, _ = _client()
    r = c.get("/api/debug/sessions/nope/starter_crop?print_w=17&print_h=22")
    assert r.status_code == 404 and r.json()["detail"] == "Unknown session"


def test_starter_crop_of_a_session_on_an_unknown_plate_is_a_404():
    c, _ = _client()
    sid = session.create({"region_id": "no_such_plate", "tracks": [_track()],
                          "hotspots": []})
    r = c.get(f"/api/debug/sessions/{sid}/starter_crop?print_w=17&print_h=22")
    assert r.status_code == 404 and r.json()["detail"] == "Unknown region 'no_such_plate'"


@pytest.mark.parametrize("query", ["print_w=0&print_h=22", "print_w=17&print_h=0",
                                   "print_w=-17&print_h=22", "print_w=17&print_h=-22",
                                   "print_w=nan&print_h=22", "print_w=17&print_h=nan",
                                   "print_w=inf&print_h=22", "print_w=17&print_h=-inf",
                                   "print_w=wide&print_h=22",
                                   # finite and positive, and still no usable sheet
                                   "print_w=1e308&print_h=22", "print_w=5e-324&print_h=22",
                                   "print_w=1e-300&print_h=1e300",
                                   "print_w=17&print_h=1e15", "print_w=1e-200&print_h=22",
                                   "print_w=17", "print_h=22", ""])
def test_starter_crop_refuses_a_size_that_is_not_finite_and_positive(query):
    c, _ = _client()
    sid = _make_session()
    r = c.get(f"/api/debug/sessions/{sid}/starter_crop?{query}")
    assert r.status_code == 422, r.text


def test_gate_off_means_the_live_app_has_no_forms_and_no_starter_crop():
    sid = _make_session()
    live = TestClient(main.app)
    for path in ("/forms", f"/sessions/{sid}/starter_crop?print_w=17&print_h=22"):
        r = live.get("/api/debug" + path)
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}, path


def test_forms_and_starter_crop_leave_the_session_as_it_was():
    c, _ = _client()
    sid = _upload()["session"]
    before = _frozen(sid)
    assert c.get("/api/debug/forms").status_code == 200
    for size in ("print_w=17&print_h=22", "print_w=11&print_h=17"):
        assert c.get(f"/api/debug/sessions/{sid}/starter_crop?{size}").status_code == 200
    assert _frozen(sid) == before


# ---- sessions/{sid}/proof_form: the proof fields of a session's stamped spec ----
# A change to a session the studio has open (one --set, a new crop) must start from
# the session's own fields. Without them, one field would put every other one back to
# the engine default. The proof is a round trip: send proof_form and crop back to
# /api/proof, and the spec it stamps is the spec the session had.

STYLED = {"print_w": 6, "print_h": 8, "title": "Three Summers", "bleed": 0.125,
          "contours": "true", "compass": "false", "labels": "true",
          "track_width_pt": 3.4, "track_halo": 0.4, "track_color": "#4a6936",
          "marker_size_in": 0.31, "marker_ring": 0.12, "photo_style": "polaroid",
          "furniture_scale": 1.2, "terrain_depth": 0.8, "shadow_strength": 0.3,
          "soft_light": 0.4, "haze_strength": 0.25, "water_depth": 0.5,
          "track_color_by": "elevation", "label_place": "anchor",
          "track_weave": "false"}


def _as_form(proof_form):
    # the way a form sends it: a boolean is "true" or "false"
    return {k: ("true" if v else "false") if isinstance(v, bool) else v
            for k, v in proof_form.items()}


def _proofed(c, **fields):
    # a real session with a stamped spec: upload, frame it for the sheet, proof it
    sid = _upload()["session"]
    w, h = fields.get("print_w", 17), fields.get("print_h", 22)
    crop = c.get(f"/api/debug/sessions/{sid}/starter_crop"
                 f"?print_w={w}&print_h={h}").json()["starter_crop"]
    r = TestClient(main.app).post("/api/proof", data={
        "session_id": sid, **dict(zip(("x0", "y0", "x1", "y1"), crop)), **fields})
    assert r.status_code == 200, r.text
    return sid


def test_proof_form_and_crop_stamp_the_same_spec_again():
    c, _ = _client()
    sid = _proofed(c, **STYLED)
    first = session.get(sid)["spec"]
    # the first proof left the defaults: a default-only round trip proves nothing
    plain = CompositionSpec(region_id="lassen_ca", crs="EPSG:32610",
                            crop=(0.0, 0.0, 3.0, 4.0), print_w_in=17, print_h_in=22,
                            native_resolution_m=10, tracks=[], hotspots=[], seed=0)
    moved = {n for n in ("print_w_in", "print_h_in", "title_text", "bleed_in",
                         "contours", "compass", "labels", "track_width_pt",
                         "track_halo", "track_rgb", "marker_diameter_in",
                         "marker_ring", "photo_frame_style", "furniture_scale",
                         "terrain_depth", "shadow_strength", "soft_light",
                         "haze_strength", "water_depth", "track_color_by")
             if getattr(first, n) != getattr(plain, n)}
    assert len(moved) == 20, moved
    # these two leave the form defaults ("smart", true), which are not the spec's
    assert first.label_place == "anchor" and first.track_weave is False

    r = c.get(f"/api/debug/sessions/{sid}/proof_form")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"proof_form", "crop"}
    form, crop = body["proof_form"], body["crop"]
    assert form == main._proof_form_for(first)
    assert set(form) <= set(inspect.signature(main.proof).parameters)
    assert isinstance(crop, list) and len(crop) == 4
    assert all(type(v) in (int, float) for v in crop), crop
    assert crop[0] < crop[2] and crop[1] < crop[3]

    x0, y0, x1, y1 = crop
    r = TestClient(main.app).post("/api/proof", data={
        "session_id": sid, "x0": x0, "y0": y0, "x1": x1, "y1": y1, **_as_form(form)})
    assert r.status_code == 200, r.text
    second = session.get(sid)["spec"]
    a, b = (json.loads(json.dumps(serialize.spec_to_json(s))) for s in (first, second))
    diff = [f"{k}: {str(a.get(k))[:80]} -> {str(b.get(k))[:80]}"
            for k in sorted(set(a) | set(b)) if k != "crop" and a.get(k) != b.get(k)]
    assert not diff, "proof_form did not restore: " + "; ".join(diff)
    # the crop goes CRS metres -> overview px -> CRS metres, so not bit for bit
    drift = max(abs(p - q) for p, q in zip(first.crop, second.crop))
    assert drift < 1e-3, f"crop moved {drift} m: {first.crop} -> {second.crop}"


def test_proof_form_of_an_unknown_session_is_a_404_that_names_the_cause():
    c, _ = _client()
    r = c.get("/api/debug/sessions/nope/proof_form")
    assert r.status_code == 404 and r.json() == {"detail": "Unknown session"}


def test_proof_form_of_a_session_with_no_proof_is_a_409():
    c, _ = _client()
    for sid in (_make_session(), _upload()["session"]):
        r = c.get(f"/api/debug/sessions/{sid}/proof_form")
        assert r.status_code == 409, r.text
        assert r.json() == {"detail": "This session has no proof yet."}


def test_proof_form_of_a_session_on_an_unknown_plate_is_a_404():
    c, _ = _client()
    sid = _make_session(with_spec=True)
    session.update(sid, region_id="no_such_plate")
    r = c.get(f"/api/debug/sessions/{sid}/proof_form")
    assert r.status_code == 404 and r.json()["detail"] == "Unknown region 'no_such_plate'"


def test_gate_off_means_the_live_app_has_no_proof_form():
    sid = _make_session(with_spec=True)
    r = TestClient(main.app).get(f"/api/debug/sessions/{sid}/proof_form")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_proof_form_leaves_the_session_as_it_was():
    c, _ = _client()
    sid = _proofed(c, print_w=6, print_h=8, title="Trip")
    before = _frozen(sid)
    assert '"title_text": "Trip"' in before     # the frozen text holds the spec too
    for _ in range(2):
        assert c.get(f"/api/debug/sessions/{sid}/proof_form").status_code == 200
    assert _frozen(sid) == before


def test_debug_module_never_imports_app_main():
    # build_router takes what it needs as arguments. An import of app.main from
    # app.debug is a cycle: app.main imports app.debug to build this router.
    tree = ast.parse(open(debug.__file__).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name != "app.main" for a in node.names), node.lineno
        if isinstance(node, ast.ImportFrom):
            assert node.module != "app.main", node.lineno
            if node.module in ("app", None):
                assert all(a.name != "main" for a in node.names), node.lineno


LOCAL_ONLY = "Debug routes answer only a local Host header."


def test_a_foreign_host_header_is_refused_on_every_route():
    # a page that uses DNS rebinding reaches 127.0.0.1 with its own Host header
    c, _ = _client()
    sid = _make_session(with_spec=True)
    report = {"tab": TAB, "state": {"session": sid},
              "errors": [{"kind": "error", "message": "from another site"}]}
    for method, path in (("GET", "/engine"), ("GET", "/jobs"), ("GET", "/sessions"),
                         ("GET", "/sessions/x?full=1"), ("GET", f"/sessions/{sid}?full=1"),
                         ("GET", "/caches"), ("GET", "/forms"),
                         ("GET", f"/sessions/{sid}/starter_crop?print_w=17&print_h=22"),
                         ("GET", f"/sessions/{sid}/proof_form"),
                         ("GET", "/studio"), ("POST", "/studio")):
        r = c.request(method, "/api/debug" + path,
                      headers={"Host": "attacker.example:8848"},
                      json=report if method == "POST" else None)
        assert r.status_code == 403, (method, path)
        # 403 and not 404: the tecopa tool reads a 404 "Not Found" as "the gate is off"
        assert r.json() == {"detail": LOCAL_ONLY}, (method, path)
        assert "1100.0" not in r.text, (method, path)
    # the refused post left nothing in the buffer
    assert c.get("/api/debug/studio").json() == {"tabs": [], "errors": []}


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


# ---- /api/debug/studio: the studio's reports, held in engine memory ----
# The browser posts its small state and its errors, and the tecopa tool reads them
# back. The post is the one debug route that changes anything, and it changes only
# the report buffer. A report never holds journey data, so the route keeps a fixed
# list of state keys and drops the rest.

TAB = "tab00001"
STUDIO = "/api/debug/studio"
STATE = {"session": "0123abcd", "target": "print", "view": "proof",
         "region": "lassen_ca", "output": "poster", "edition": 2,
         "has_spec": True, "proof_stale": False}
LOCAL_ORIGIN_ONLY = "Debug routes answer only a local Origin header."


def _error(message="boom", kind="error", **more):
    return {"kind": kind, "message": message, "source": "app.js", "line": 12,
            "stack": "Error: boom\n    at app.js:12", **more}


def _raw(c, content, **headers):
    # the body as bytes, for a body that json= would not build
    return c.post(STUDIO, content=content,
                  headers={"Content-Type": "application/json", **headers})


def test_studio_starts_empty_for_each_router():
    a, _ = _client()
    assert a.get(STUDIO).json() == {"tabs": [], "errors": []}
    assert a.post(STUDIO, json={"tab": TAB, "state": STATE}).status_code == 204
    # the buffer belongs to the router: a new engine starts with none
    b, _ = _client()
    assert b.get(STUDIO).json() == {"tabs": [], "errors": []}


def test_studio_post_is_a_204_and_the_get_returns_the_report():
    c, _ = _client()
    before = time.time()
    r = c.post(STUDIO, json={"tab": TAB, "state": STATE, "errors": [_error()]})
    after = time.time()
    assert r.status_code == 204 and r.content == b""
    body = c.get(STUDIO).json()
    assert list(body) == ["tabs", "errors"]
    assert len(body["tabs"]) == 1 and len(body["errors"]) == 1
    tab, err = body["tabs"][0], body["errors"][0]
    assert list(tab) == ["tab", "received", "state"]
    assert tab["tab"] == TAB and tab["state"] == STATE
    assert list(err) == ["tab", "received", "kind", "message", "source", "line", "stack"]
    assert err == {"tab": TAB, "received": err["received"], **_error()}
    # the engine's clock, not the browser's
    for row in (tab, err):
        assert type(row["received"]) is float and before <= row["received"] <= after


def test_studio_state_keeps_only_the_named_keys():
    c, _ = _client()
    journey = {"tracks": [[1100.0, 2100.0]], "hotspots": [{"label": "SECRET-CAMP"}],
               "markers": "SECRET-MARKER", "labels": "SECRET-LABEL",
               "files": "SECRET-FILE.gpx", "filename": "SECRET-NAME.gpx",
               "crop": "SECRET-CROP", "title": "SECRET-TITLE", "sid": "SECRET-SID",
               "Session": "SECRET-CASE", "session ": "SECRET-SPACE"}
    assert c.post(STUDIO, json={"tab": TAB, "state": {**STATE, **journey},
                                "tracks": "SECRET-TOP", "extra": 1}).status_code == 204
    r = c.get(STUDIO)
    assert r.json()["tabs"][0]["state"] == STATE
    assert set(r.json()["tabs"][0]) == {"tab", "received", "state"}
    assert "SECRET" not in r.text and "1100.0" not in r.text


def test_studio_state_keeps_only_scalar_values():
    c, _ = _client()
    state = {"session": ["0123abcd"], "target": {"kind": "print"}, "view": None,
             "region": "r" * 201, "output": "o" * 200, "edition": 3,
             "has_spec": True, "proof_stale": 0.5}
    assert c.post(STUDIO, json={"tab": TAB, "state": state}).status_code == 204
    # a list and an object are dropped, and a string is cut at 200 characters
    assert c.get(STUDIO).json()["tabs"][0]["state"] == {
        "view": None, "region": "r" * 200, "output": "o" * 200, "edition": 3,
        "has_spec": True, "proof_stale": 0.5}


def test_studio_drops_a_value_that_is_nested_deep():
    # 30,000 levels fit in 64 KB. The value is dropped whole and never walked.
    c, _ = _client()
    deep = b"[" * 30000 + b"]" * 30000
    body = (b'{"tab": "tab00001", "state": {"session": ' + deep + b', "view": "proof"},'
            b' "errors": [{"kind": "error", "message": ' + deep[:2000] + deep[-2000:]
            + b', "stack": "s"}]}')
    assert _raw(c, body).status_code == 204
    r = c.get(STUDIO)
    assert r.status_code == 200, r.text
    assert r.json()["tabs"][0]["state"] == {"view": "proof"}
    assert (r.json()["errors"][0]["message"], r.json()["errors"][0]["stack"]) == ("", "s")
    assert _raw(c, b'{"tab": "tab00001", "state": ' + deep + b"}").status_code == 204
    assert c.get(STUDIO).json()["tabs"][0]["state"] == {"view": "proof"}


def test_studio_drops_a_value_that_json_cannot_send_back():
    # Python reads NaN, an infinity and a lone surrogate. JSON cannot write them, so
    # one of them in the buffer would make every later GET a 500.
    c, _ = _client()
    body = (b'{"tab": "tab00001", "state": {"edition": NaN, "view": 1e999,'
            b' "target": -Infinity, "region": "a\\ud800b", "output": "ok"},'
            b' "errors": [{"kind": "toast", "message": "m\\udc00", "line": 1e999,'
            b' "source": "s\\ud800", "stack": "k\\ud800"}]}')
    assert _raw(c, body).status_code == 204
    r = c.get(STUDIO)
    assert r.status_code == 200, r.text
    assert r.json()["tabs"][0]["state"] == {"region": "a?b", "output": "ok"}
    err = r.json()["errors"][0]
    assert (err["message"], err["source"], err["stack"], err["line"]) == (
        "m?", "s?", "k?", None)


def test_studio_state_that_is_not_an_object_counts_as_no_state():
    c, _ = _client()
    assert c.post(STUDIO, json={"tab": TAB, "state": STATE}).status_code == 204
    for bad in ("print", 7, ["session"], None):
        assert c.post(STUDIO, json={"tab": TAB, "state": bad}).status_code == 204
        assert c.get(STUDIO).json()["tabs"][0]["state"] == STATE
    # an empty object is a state: the studio holds nothing yet
    assert c.post(STUDIO, json={"tab": TAB, "state": {}}).status_code == 204
    assert c.get(STUDIO).json()["tabs"][0]["state"] == {}


def test_studio_error_strings_are_cut_and_not_refused():
    c, _ = _client()
    long = {"kind": "error", "message": "m" * 2001, "source": "s" * 301,
            "line": 4, "stack": "k" * 8001}
    exact = {"kind": "error", "message": "m" * 2000, "source": "s" * 300,
             "line": 4, "stack": "k" * 8000}
    assert c.post(STUDIO, json={"tab": TAB, "errors": [long]}).status_code == 204
    err = c.get(STUDIO).json()["errors"][0]
    assert {k: err[k] for k in exact} == exact
    assert c.post(STUDIO, json={"tab": TAB, "errors": [exact]}).status_code == 204
    err = c.get(STUDIO).json()["errors"][0]
    assert {k: err[k] for k in exact} == exact


def test_studio_text_loses_its_control_characters():
    # the tecopa tool prints this text in a terminal, where ESC starts a command
    c, _ = _client()
    sent = {"kind": "toast", "message": "a\x00b\x1b[31mc\x7f\n\td", "source": "s\x08t"}
    assert c.post(STUDIO, json={"tab": TAB, "state": {"view": "m\x1bap"},
                                "errors": [sent]}).status_code == 204
    got = c.get(STUDIO).json()
    assert got["errors"][0]["message"] == "ab[31mc\n\td"
    assert got["errors"][0]["source"] == "st"
    assert got["tabs"][0]["state"] == {"view": "map"}


def test_studio_body_nested_too_deep_to_read_is_a_422(monkeypatch):
    # the JSON reader runs out of stack on a body of many thousand brackets
    class Reader:
        # only this module's reader: the test client reads JSON too
        @staticmethod
        def loads(_):
            raise RecursionError
    monkeypatch.setattr(debug, "json", Reader)
    c, _ = _client()
    r = c.post(STUDIO, content=b"[[[[", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and r.json() == {"detail": "A studio report is one JSON object."}


def test_studio_post_that_ends_before_its_body_is_dropped_without_an_error():
    # a page that closes while it sends: no report, and no traceback in the log
    import asyncio
    c, _ = _client()
    def walk(routes):
        for r in routes:
            yield r
            yield from walk(getattr(r, "routes", None) or
                            getattr(getattr(r, "original_router", None), "routes", []))
    route = next(r for r in walk(c.app.routes)
                 if getattr(r, "path", "").endswith("/studio")
                 and "POST" in (getattr(r, "methods", None) or ()))

    async def closed():
        return {"type": "http.disconnect"}
    request = Request({"type": "http", "method": "POST", "path": STUDIO,
                       "query_string": b"",
                       "headers": [(b"host", b"127.0.0.1:8848"),
                                   (b"content-type", b"application/json")]}, closed)
    reply = asyncio.run(route.endpoint(request))
    assert reply.status_code == 204
    assert c.get(STUDIO).json() == {"tabs": [], "errors": []}


def test_the_engine_answers_no_preflight():
    # The studio post needs application/json because another website cannot send it
    # without a preflight. That holds only while the engine answers none: no CORS
    # middleware, and an OPTIONS that carries no Access-Control header.
    assert not any("cors" in m.cls.__name__.lower() for m in main.app.user_middleware)
    c, _ = _client()
    r = c.options(STUDIO, headers={"Origin": "https://attacker.example",
                                   "Access-Control-Request-Method": "POST",
                                   "Access-Control-Request-Headers": "content-type"})
    assert r.status_code >= 400
    assert not [h for h in r.headers if h.lower().startswith("access-control-")]


def test_studio_error_of_another_kind_is_dropped():
    c, _ = _client()
    errors = [_error("one", "error"), _error("two", "rejection"), _error("three", "toast"),
              _error("four", "warning"), _error("five", "Error"), _error("six", 7),
              _error("seven", None), {"message": "eight"}, "nine", 10, None, ["error"]]
    assert c.post(STUDIO, json={"tab": TAB, "errors": errors}).status_code == 204
    got = c.get(STUDIO).json()["errors"]
    assert [(e["kind"], e["message"]) for e in got] == [
        ("toast", "three"), ("rejection", "two"), ("error", "one")]
    # a list of errors that is not a list holds no error
    for bad in ("error", 7, _error(), None):
        assert c.post(STUDIO, json={"tab": TAB, "errors": bad}).status_code == 204
    assert len(c.get(STUDIO).json()["errors"]) == 3


def test_studio_error_fields_have_one_type_each():
    # the tecopa tool reads these: a message is text, the others are a value or null
    c, _ = _client()
    errors = [{"kind": "error"},
              {"kind": "error", "message": 5, "source": 6, "line": "12", "stack": 7},
              {"kind": "error", "message": "m", "line": 1.5},
              {"kind": "error", "message": "m", "line": True},
              {"kind": "error", "message": "m", "line": 2 ** 70},
              {"kind": "error", "message": "m", "line": 0, "title": "SECRET-TITLE"}]
    assert c.post(STUDIO, json={"tab": TAB, "errors": errors}).status_code == 204
    r = c.get(STUDIO)
    got = r.json()["errors"][::-1]
    empty = {"kind": "error", "message": "", "source": None, "line": None, "stack": None}
    assert [{k: e[k] for k in empty} for e in got] == [
        empty, empty, {**empty, "message": "m"}, {**empty, "message": "m"},
        {**empty, "message": "m"}, {**empty, "message": "m", "line": 0}]
    assert "SECRET" not in r.text       # an error keeps its five fields and no other


def test_studio_takes_the_first_20_errors_of_one_post():
    c, _ = _client()
    errors = [_error(f"m{i}") for i in range(25)]
    assert c.post(STUDIO, json={"tab": TAB, "errors": errors}).status_code == 204
    got = c.get(STUDIO).json()["errors"]
    assert [e["message"] for e in got] == [f"m{i}" for i in range(19, -1, -1)]


def test_studio_keeps_the_last_50_errors():
    c, _ = _client()
    for post in range(3):
        errors = [_error(f"m{post * 20 + i}") for i in range(20)]
        assert c.post(STUDIO, json={"tab": f"tab0000{post}",
                                    "errors": errors}).status_code == 204
    got = c.get(STUDIO).json()["errors"]
    assert [e["message"] for e in got] == [f"m{i}" for i in range(59, 9, -1)]
    assert got[0]["tab"] == "tab00002" and got[-1]["tab"] == "tab00000"


def test_studio_keeps_20_tabs_and_drops_the_one_that_reported_longest_ago():
    c, _ = _client()
    tabs = [f"tab000{i:02d}" for i in range(21)]
    for tab in tabs[:20]:
        assert c.post(STUDIO, json={"tab": tab, "state": {"view": tab}}).status_code == 204
    assert len(c.get(STUDIO).json()["tabs"]) == 20
    # the first tab reports again, so the second is now the oldest
    assert c.post(STUDIO, json={"tab": tabs[0], "errors": [_error()]}).status_code == 204
    assert c.post(STUDIO, json={"tab": tabs[20], "state": {"view": "new"}}).status_code == 204
    got = [t["tab"] for t in c.get(STUDIO).json()["tabs"]]
    assert got == [tabs[20], tabs[0]] + tabs[19:1:-1]
    assert tabs[1] not in got and len(got) == 20


def test_studio_lists_are_newest_first():
    c, _ = _client()
    for n, tab in enumerate(("tab0000a", "tab0000b", "tab0000c")):
        assert c.post(STUDIO, json={"tab": tab, "state": {"edition": n},
                                    "errors": [_error(f"{tab}-1"), _error(f"{tab}-2")]}
                      ).status_code == 204
    assert c.post(STUDIO, json={"tab": "tab0000a", "state": {"edition": 9}}).status_code == 204
    body = c.get(STUDIO).json()
    assert [(t["tab"], t["state"]["edition"]) for t in body["tabs"]] == [
        ("tab0000a", 9), ("tab0000c", 2), ("tab0000b", 1)]
    # in one post the last error is the newest
    assert [e["message"] for e in body["errors"]] == [
        "tab0000c-2", "tab0000c-1", "tab0000b-2", "tab0000b-1", "tab0000a-2", "tab0000a-1"]
    for rows in (body["tabs"], body["errors"]):
        times = [row["received"] for row in rows]
        assert times == sorted(times, reverse=True)


def test_studio_errors_with_no_state_keep_the_state_and_move_the_time():
    c, _ = _client()
    assert c.post(STUDIO, json={"tab": TAB, "state": STATE}).status_code == 204
    first = c.get(STUDIO).json()["tabs"][0]
    time.sleep(0.01)
    assert c.post(STUDIO, json={"tab": TAB, "errors": [_error()]}).status_code == 204
    second = c.get(STUDIO).json()["tabs"]
    assert len(second) == 1 and second[0]["state"] == STATE
    assert second[0]["received"] > first["received"]
    # a tab that has sent only errors is a tab with no state yet
    assert c.post(STUDIO, json={"tab": "tab00002", "errors": [_error()]}).status_code == 204
    newest = c.get(STUDIO).json()["tabs"][0]
    assert newest["tab"] == "tab00002" and newest["state"] is None


TOO_LARGE = "A studio report is at most 64 KB."


def _padded(size):
    # a valid report of exactly `size` bytes: JSON allows the spaces after it
    body = json.dumps({"tab": TAB, "state": STATE}).encode()
    return body + b" " * (size - len(body))


def test_studio_body_of_64_kb_is_taken_and_one_byte_more_is_a_413():
    c, _ = _client()
    assert _raw(c, _padded(64 * 1024)).status_code == 204
    r = _raw(c, _padded(64 * 1024 + 1))
    assert r.status_code == 413 and r.json() == {"detail": TOO_LARGE}
    assert len(c.get(STUDIO).json()["tabs"]) == 1


def test_studio_body_is_measured_and_content_length_is_not_trusted():
    c, _ = _client()
    big = _padded(64 * 1024 + 1)
    # a Content-Length that is small, one that is not a number, and none at all
    for headers in ({"Content-Length": "10"}, {"Content-Length": "many"}):
        r = _raw(c, big, **headers)
        assert r.status_code == 413 and r.json() == {"detail": TOO_LARGE}, headers
    chunked = c.post(STUDIO, content=iter([big[:1000], big[1000:]]),
                     headers={"Content-Type": "application/json"})
    assert "content-length" not in chunked.request.headers
    assert chunked.status_code == 413 and chunked.json() == {"detail": TOO_LARGE}
    # a Content-Length over the limit is refused, whatever the body is
    r = _raw(c, _padded(100), **{"Content-Length": str(64 * 1024 + 1)})
    assert r.status_code == 413
    assert c.get(STUDIO).json() == {"tabs": [], "errors": []}


def test_studio_body_read_stops_at_the_limit():
    # a sender with no Content-Length and no end: the read must stop, not fill memory
    sent = []

    async def receive():
        sent.append(1)
        return {"type": "http.request", "body": b"x" * 1024, "more_body": True}

    request = Request({"type": "http", "method": "POST", "headers": []}, receive)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(debug._read_capped(request))
    assert refused.value.status_code == 413 and refused.value.detail == TOO_LARGE
    assert len(sent) == 65            # 64 KB, and the one chunk that passes it


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded",
                                          "multipart/form-data", "application/jsonx",
                                          "text/json", "application/json+x",
                                          "x; application/json", ""])
def test_studio_post_that_is_not_json_by_content_type_is_a_415(content_type):
    # a page on another site can send these three form types with no preflight
    c, _ = _client()
    r = c.post(STUDIO, content=json.dumps({"tab": TAB, "state": STATE}),
               headers={"Content-Type": content_type})
    assert r.status_code == 415, r.text
    assert r.json() == {"detail": "A studio report is sent as application/json."}
    assert c.get(STUDIO).json() == {"tabs": [], "errors": []}


def test_studio_post_with_no_content_type_is_a_415():
    c, _ = _client()
    # httpx adds no Content-Type to a body given as text
    r = c.post(STUDIO, content=json.dumps({"tab": TAB, "state": STATE}))
    assert "content-type" not in r.request.headers
    assert r.status_code == 415
    assert c.get(STUDIO).json() == {"tabs": [], "errors": []}


@pytest.mark.parametrize("content_type", ["application/json",
                                          "application/json; charset=utf-8",
                                          "application/json;charset=UTF-8",
                                          "Application/JSON", " application/json "])
def test_studio_post_takes_json_with_parameters(content_type):
    c, _ = _client()
    r = c.post(STUDIO, content=json.dumps({"tab": TAB, "state": STATE}),
               headers={"Content-Type": content_type})
    assert r.status_code == 204, r.text


@pytest.mark.parametrize("origin", ["https://attacker.example", "null", "",
                                    "http://attacker.example",
                                    "http://127.0.0.1.attacker.example",
                                    "http://localhost.attacker.example:8848",
                                    "https://127.0.0.1:8848", "https://localhost",
                                    "http://127.0.0.1:8848/", "http://localhost:",
                                    "http://localhost:8848:1", "http://127.0.0.2",
                                    "http://::1", "http://[::1]x", "http://0.0.0.0:8848",
                                    "http://LOCALHOST:8848", "127.0.0.1:8848",
                                    "http://localhost:8848\n", "http://user@localhost"])
def test_studio_refuses_an_origin_that_is_not_local(origin):
    # A page on another site can post to 127.0.0.1, and the browser sends the local
    # Host. The Origin header still names the page.
    c, _ = _client()
    r = c.post(STUDIO, json={"tab": TAB, "state": STATE}, headers={"Origin": origin})
    assert r.status_code == 403 and r.json() == {"detail": LOCAL_ORIGIN_ONLY}
    assert c.get(STUDIO).json() == {"tabs": [], "errors": []}
    r = c.get(STUDIO, headers={"Origin": origin})
    assert r.status_code == 403 and r.json() == {"detail": LOCAL_ORIGIN_ONLY}


@pytest.mark.parametrize("origin", ["http://127.0.0.1", "http://127.0.0.1:8848",
                                    "http://localhost", "http://localhost:8848",
                                    "http://[::1]", "http://[::1]:8848",
                                    "http://localhost:3000"])
def test_studio_answers_a_local_origin(origin):
    c, _ = _client()
    r = c.post(STUDIO, json={"tab": TAB, "state": STATE}, headers={"Origin": origin})
    assert r.status_code == 204, r.text
    r = c.get(STUDIO, headers={"Origin": origin})
    assert r.status_code == 200 and len(r.json()["tabs"]) == 1


def test_studio_answers_a_request_with_no_origin():
    # the tecopa tool sends none, and a same-origin GET from the studio sends none
    c, _ = _client()
    r = c.post(STUDIO, json={"tab": TAB, "state": STATE})
    assert "origin" not in r.request.headers
    assert r.status_code == 204
    assert c.get(STUDIO).status_code == 200


@pytest.mark.parametrize("body", [
    b"", b"not json", b"{", b'{"tab": "tab00001"', b"[]", b'["tab00001"]',
    b'"tab00001"', b"7", b"null", b"true", b"{}", b'{"state": {}}',
    b'{"tab": null}', b'{"tab": 12345678}', b'{"tab": ["tab00001"]}',
    b'{"tab": "short77"}', b'{"tab": "' + b"a" * 33 + b'"}', b'{"tab": ""}',
    b'{"tab": "TAB00001"}', b'{"tab": "tab-0001"}', b'{"tab": "tab 0001"}',
    b'{"tab": "tab00001\\n"}', b'{"tab": "tab0000\xc3\xa9"}',
    b'{"tab": "tab0000\xd9\xa1"}',                  # an Arabic-Indic digit
    b'{"tab": "tab00001", "state": \xff}',          # not UTF-8
    b'{"tab": "tab00001", "state": {"edition": ' + b"9" * 5000 + b"}}"])
def test_studio_post_that_is_not_a_report_is_a_422(body):
    c, _ = _client()
    r = _raw(c, body)
    assert r.status_code == 422, r.text
    assert c.get(STUDIO).json() == {"tabs": [], "errors": []}


@pytest.mark.parametrize("tab", ["abcdefgh", "a" * 32, "01234567", "k3j9x0q2m5"])
def test_studio_takes_a_tab_id_of_8_to_32_lower_case_letters_and_digits(tab):
    c, _ = _client()
    assert c.post(STUDIO, json={"tab": tab}).status_code == 204
    assert c.get(STUDIO).json()["tabs"] == [
        {"tab": tab, "received": c.get(STUDIO).json()["tabs"][0]["received"],
         "state": None}]


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append((record.name, record.levelname, record.getMessage()))


def test_studio_logs_one_line_with_the_counts_and_never_the_text():
    # the handler goes on the module's own logger, so each record arrives one time
    # whatever the loggers above it do
    c, _ = _client()
    logger, seen = logging.getLogger("tecopa.debug"), _Lines()
    level = logger.level
    logger.addHandler(seen)
    logger.setLevel(logging.DEBUG)
    try:
        assert c.post(STUDIO, json={
            "tab": TAB, "state": {**STATE, "title": "SECRET-TITLE"},
            "errors": [_error("SECRET-MESSAGE", stack="SECRET-STACK"),
                       _error("SECRET-TOAST", "toast", source="SECRET-SOURCE"),
                       _error("dropped", "warning")]}).status_code == 204
        assert c.post(STUDIO, json={"tab": "tab00002"}).status_code == 204
        # a refused post and a read leave no line
        assert c.post(STUDIO, json={"tab": "bad"}).status_code == 422
        assert c.get(STUDIO).status_code == 200
    finally:
        logger.removeHandler(seen)
        logger.setLevel(level)
    # a post with no error is at DEBUG: an idle tab posts each 30 seconds, and the
    # launcher log is at INFO
    assert seen.lines == [
        ("tecopa.debug", "INFO", "event=debug.studio tab=tab00001 state=1 errors=2"),
        ("tecopa.debug", "DEBUG", "event=debug.studio tab=tab00002 state=0 errors=0")]


def test_studio_post_leaves_the_session_the_jobs_and_the_caches_as_they_were():
    c, q = _client()
    sid = _upload()["session"]
    jid = q.submit(lambda: "done")
    deadline = time.time() + 5
    while q.status(jid)["state"] != "done" and time.time() < deadline:
        time.sleep(0.01)
    before = (_frozen(sid), sorted(session.ids()), q.snapshot(),
              c.get("/api/debug/caches").json())
    assert c.post(STUDIO, json={"tab": TAB, "state": {**STATE, "session": sid},
                                "errors": [_error()]}).status_code == 204
    assert c.get(STUDIO).json()["tabs"][0]["state"]["session"] == sid
    assert (_frozen(sid), sorted(session.ids()), q.snapshot(),
            c.get("/api/debug/caches").json()) == before


def test_gate_off_means_the_live_app_takes_no_studio_report():
    # The static mount answers the POST, with a 405 and not a 404. The studio hook
    # stops on any first reply that is not 2xx.
    live = TestClient(main.app)
    r = live.post(STUDIO, json={"tab": TAB, "state": STATE})
    assert r.status_code == 405
    r = live.get(STUDIO)
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_debug_module_writes_nothing_to_disk():
    # The reports stay in engine memory. The module opens no file, and imports no
    # module whose work is to write one.
    tree = ast.parse(open(debug.__file__).read())
    writers = {"pathlib", "tempfile", "shutil", "sqlite3", "pickle", "shelve", "io",
               "csv", "dbm"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not writers & {a.name.split(".")[0] for a in node.names}, node.lineno
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in writers, node.lineno
            if node.module == "app":
                assert not {"blobs", "logconfig"} & {a.name for a in node.names}
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            assert name not in ("open", "write", "write_text", "write_bytes",
                                "dump"), node.lineno
