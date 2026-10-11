# app/debug.py
"""Debug routes for the `tecopa` tool, behind TECOPA_DEBUG=1.

The studio is the only client the engine was built for, and it holds its own state.
A diagnosis from outside the browser needs to see what the engine holds: which jobs
are queued or failed, which sessions exist, what the caches are doing. These routes
show that.

Every route is read-only except POST /api/debug/studio. That one changes the studio
report buffer in this module and nothing else. No route here changes a session, a
job, a cache or a plate, and no route writes to disk.

The studio reports: the browser posts its small state and its errors, and
GET /api/debug/studio returns them, so a fault in the page can be read from outside
it. The reports stay in engine memory, in a buffer of fixed size, and a restart of
the engine empties it. A report's state never holds journey data: the route keeps a
fixed list of state keys and drops every other one. An error's message, source and
stack are kept as the page sent them, cut to a fixed length.

The gate is off by default. A route that lists sessions and tracks must not exist on
a host that did not ask for it, so with the gate off app.main never includes this
router and every /api/debug path is a plain 404 (a POST gets the static mount's 405).
The macOS launcher sets the gate. With the gate on, the routes answer only a request
whose Host header is local, and the studio routes also refuse an Origin header that
is not local.

Design: docs/superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md."""
from __future__ import annotations
import collections
import inspect
import json
import logging
import math
import os
import platform
import re
import threading
import time
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.requests import ClientDisconnect
from app import geo, provenance, serialize, session

log = logging.getLogger("tecopa.debug")


def enabled(env=None) -> bool:
    """True only for the exact value "1". Anything else, the routes do not exist."""
    env = os.environ if env is None else env
    return env.get("TECOPA_DEBUG", "") == "1"


# The Host values a debug route answers, after the port is removed. IPv6 keeps its
# brackets in a Host header, so "[::1]:8848" loses only the ":8848".
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})
_PORT = re.compile(r":[0-9]+\Z")


def _local_host_only(request: Request) -> None:
    # DNS rebinding: a web page can point its own name at 127.0.0.1, and the browser
    # then lets that page read these routes. The request still carries the page's
    # name in Host, so a Host that is not local is refused. A missing Host is too.
    # 403 and not 404: the tecopa tool reads a 404 "Not Found" as "the gate is off".
    host = _PORT.sub("", request.headers.get("host", ""), count=1).lower()
    if host not in _LOCAL_HOSTS:
        raise HTTPException(403, "Debug routes answer only a local Host header.")


# The Origin values the studio routes answer. A page on another website can send a
# POST to 127.0.0.1, and the browser sends the local Host with it, so the Host check
# passes. The browser also sends the page's own Origin, and that is refused here.
# "null" (a sandboxed page, a file) is not local. A request with no Origin passes:
# the tecopa tool sends none, and a browser adds one to every cross-site POST.
# For the GET this refuses only a fetch that asks to read the answer. An <img> or a
# no-cors GET sends no Origin and gets its 200, which the page cannot read: the
# engine sends no CORS header, and the Host check stops a rebound name.
_LOCAL_ORIGIN = re.compile(r"http://(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]+)?")


def _local_origin_only(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is not None and not _LOCAL_ORIGIN.fullmatch(origin):
        raise HTTPException(403, "Debug routes answer only a local Origin header.")


# ---- the studio reports ----

MAX_BODY = 64 * 1024            # bytes in one studio post
MAX_ERRORS_PER_POST = 20
# The only keys a state keeps. This list is the privacy rule: a report never holds
# tracks, markers, labels, filenames, the crop or the title, whatever the page sends.
STATE_KEYS = ("session", "target", "view", "region", "output", "edition",
              "has_spec", "proof_stale")
STATE_TEXT = 200                # characters in one state value
ERROR_KINDS = frozenset({"error", "rejection", "toast"})
ERROR_TEXT = {"message": 2000, "source": 300, "stack": 8000}
_TAB = re.compile(r"[a-z0-9]{8,32}")
_SAFE_INT = 2 ** 53             # past this a JSON reader no longer holds the integer


# NUL, ESC and the other control characters, except the tab and the line end
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _text(value: str, limit: int) -> str:
    # Cut, not refused. A lone surrogate is legal in a JSON string and cannot be
    # written back as UTF-8: one in the buffer would make every later GET a 500.
    # A control character goes too: the tecopa tool prints this text in a terminal.
    value = _CONTROL.sub("", value[:limit])
    return value.encode("utf-8", "replace").decode("utf-8")


def _whole(value) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and abs(value) <= _SAFE_INT)


def _clean_state(raw) -> dict | None:
    """The named keys with a scalar value. None if `raw` is not an object."""
    if not isinstance(raw, dict):
        return None
    state = {}
    for key in STATE_KEYS:
        if key not in raw:
            continue
        v = raw[key]
        if isinstance(v, str):
            state[key] = _text(v, STATE_TEXT)
        elif v is None or isinstance(v, bool) or _whole(v):
            state[key] = v
        elif isinstance(v, float) and math.isfinite(v):   # JSON has no NaN to send back
            state[key] = v
    return state


def _clean_errors(raw) -> list[dict]:
    """The first 20 entries of `raw`, without each one that is not an error of a
    known kind. Each error that stays has the same five fields."""
    if not isinstance(raw, list):
        return []
    errors = []
    for e in raw[:MAX_ERRORS_PER_POST]:
        if not isinstance(e, dict):
            continue
        kind = e.get("kind")
        if not isinstance(kind, str) or kind not in ERROR_KINDS:
            continue
        message, source, line, stack = (e.get(k) for k in
                                        ("message", "source", "line", "stack"))
        errors.append({
            "kind": kind,
            "message": _text(message, ERROR_TEXT["message"]) if isinstance(message, str) else "",
            "source": _text(source, ERROR_TEXT["source"]) if isinstance(source, str) else None,
            "line": line if _whole(line) else None,
            "stack": _text(stack, ERROR_TEXT["stack"]) if isinstance(stack, str) else None})
    return errors


class StudioReports:
    """The studio's reports, in memory only: the latest state for each of at most
    MAX_TABS tabs, and the last MAX_ERRORS errors from all tabs. `add` takes values
    that are already clean. Nothing here goes to disk, so a restart empties it."""
    MAX_TABS = 20
    MAX_ERRORS = 50

    def __init__(self):
        self._lock = threading.Lock()
        self._tabs: dict[str, dict] = {}      # in report order, the oldest first
        self._errors: collections.deque = collections.deque(maxlen=self.MAX_ERRORS)

    def add(self, tab: str, state: dict | None, errors: list[dict]) -> None:
        with self._lock:
            received = time.time()            # the engine's clock, not the browser's
            last = self._tabs.pop(tab, None)
            if state is None and last is not None:
                state = last["state"]         # errors alone keep the state
            self._tabs[tab] = {"received": received, "state": state}
            while len(self._tabs) > self.MAX_TABS:
                del self._tabs[next(iter(self._tabs))]
            for e in errors:
                self._errors.append({"tab": tab, "received": received, **e})

    def snapshot(self) -> dict:
        """Both lists, newest first. The rows are copies."""
        with self._lock:
            tabs = [{"tab": tab, "received": row["received"],
                     "state": None if row["state"] is None else dict(row["state"])}
                    for tab, row in reversed(self._tabs.items())]
            errors = [dict(e) for e in reversed(self._errors)]
        return {"tabs": tabs, "errors": errors}


async def _read_capped(request: Request, limit: int = MAX_BODY) -> bytes:
    """The body, or a 413 as soon as it passes `limit`. Content-Length can refuse a
    post early. It cannot admit one: the bytes are counted as they arrive, and the
    read stops at the limit, so a sender cannot fill the engine's memory."""
    too_large = HTTPException(413, "A studio report is at most 64 KB.")
    try:
        declared = int(request.headers.get("content-length", ""))
    except ValueError:
        declared = 0
    if declared > limit:
        raise too_large
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise too_large
    return bytes(body)


def _session_row(sid: str, data: dict) -> dict:
    return {"sid": sid, "region_id": data.get("region_id"),
            "tracks": len(data.get("tracks") or []),
            "hotspots": len(data.get("hotspots") or []),
            "has_spec": data.get("spec") is not None}


def _session_detail(sid: str, data: dict, full: bool) -> dict:
    spec = serialize.spec_to_json(data["spec"]) if data.get("spec") else None
    if full:
        tracks = [serialize.track_to_json(t) for t in data.get("tracks") or []]
    else:
        tracks = [{"track_id": t.track_id, "points": int(len(t.coords)), "day": t.day}
                  for t in data.get("tracks") or []]
        if spec is not None:
            # spec_to_json carries the track geometry too; without full=1 a reader
            # gets the count and never the coordinates
            spec["tracks"] = len(spec.get("tracks") or [])
    return {"sid": sid, "region_id": data.get("region_id"), "spec": spec,
            "tracks": tracks, "hotspots": data.get("hotspots") or [],
            "edition": data.get("edition", 1), "lineage": data.get("lineage", [])}


def build_router(*, queues: dict, caches: dict, started: float, forms: dict,
                 regions: dict, proof_form, crop_px) -> APIRouter:
    """`queues` maps a name to a ThreadJobQueue, `caches` a name to a BaseCache,
    `started` is the engine's start time, `forms` maps a name to a route function,
    `regions` a region id to a Region. `proof_form` turns a spec into its /api/proof
    form fields, and `crop_px` turns a region's geo and a CRS crop into overview
    pixels: the two helpers /api/continue answers with. Passed in, not imported, so
    this module never imports app.main."""
    r = APIRouter(prefix="/api/debug", dependencies=[Depends(_local_host_only)])
    # One buffer for the life of this router: an engine start, or a test client,
    # begins with no report.
    studio = StudioReports()
    studio_only = [Depends(_local_origin_only)]

    @r.get("/engine")
    async def engine():
        return {"engine": provenance.ENGINE,
                "engine_version": provenance.ENGINE_VERSION,
                "pid": os.getpid(),
                "uptime_s": round(time.time() - started, 1),
                "python": platform.python_version(),
                "env": {k: v for k, v in sorted(os.environ.items())
                        if k.startswith("TECOPA_")},
                "store": session.kind(),
                "queues": {name: q.max_concurrency for name, q in queues.items()}}

    @r.get("/jobs")
    async def list_jobs():
        rows = [{"queue": name, **row}
                for name, q in queues.items() for row in q.snapshot()]
        rows.sort(key=lambda row: row["created"], reverse=True)
        return {"jobs": rows}

    @r.get("/sessions")
    async def list_sessions():
        rows = []
        for sid in session.ids():
            try:
                rows.append(_session_row(sid, session.get(sid)))
            except KeyError:        # dropped between ids() and get()
                continue
        return {"sessions": rows}

    @r.get("/sessions/{sid}")
    async def session_detail(sid: str, full: bool = False):
        try:
            data = session.get(sid)
        except KeyError:
            raise HTTPException(404, "Unknown session")
        return _session_detail(sid, data, full)

    @r.get("/sessions/{sid}/starter_crop")
    async def session_starter_crop(sid: str, print_w: float, print_h: float):
        bad_size = HTTPException(422, "print_w and print_h must be finite and positive")
        if not all(math.isfinite(v) and v > 0 for v in (print_w, print_h)):
            raise bad_size
        try:
            data = session.get(sid)
        except KeyError:
            raise HTTPException(404, "Unknown session")
        region = regions.get(data.get("region_id"))
        if region is None:
            raise HTTPException(404, f"Unknown region {data.get('region_id')!r}")
        # the same two steps as /api/upload, so 17 by 22 gives the upload's own crop:
        # the tracks go to overview pixels, then app.geo frames them
        tpx = [[geo.crs_to_overview_px(region.geo, x, y) for x, y in t.coords]
               for t in data.get("tracks") or []]
        try:
            crop = geo.starter_crop(region.geo, tpx, print_w, print_h,
                                    native_resolution_m=region.cfg["native_resolution_m"])
        except (ArithmeticError, ValueError):
            # a size such as 1e308 is finite and still overflows the floor arithmetic
            raise bad_size
        # an aspect such as 17 by 1e15 frames a box with no width: not a crop
        if not (crop[2] - crop[0] > 1e-6 and crop[3] - crop[1] > 1e-6):
            raise bad_size
        return {"starter_crop": list(crop)}

    @r.get("/sessions/{sid}/proof_form")
    async def session_proof_form(sid: str):
        # A change to a session's proof must start from the session's own fields:
        # /api/proof builds every field it is not sent from the engine default, so
        # one field alone would put the rest of the look back to plain.
        try:
            data = session.get(sid)
        except KeyError:
            raise HTTPException(404, "Unknown session")
        spec = data.get("spec")
        if spec is None:
            raise HTTPException(409, "This session has no proof yet.")
        region = regions.get(data.get("region_id"))
        if region is None:
            raise HTTPException(404, f"Unknown region {data.get('region_id')!r}")
        # the two answers /api/continue gives for a file, here for a live session:
        # the form fields, and the crop in the overview pixels /api/proof takes
        return {"proof_form": proof_form(spec),
                "crop": list(crop_px(region.geo, spec.crop))}

    @r.get("/forms")
    async def list_forms():
        # FastAPI ignores a form field it does not know. The tecopa tool refuses a
        # misspelled name against these lists and holds no copy of the names.
        return {name: list(inspect.signature(fn).parameters)
                for name, fn in forms.items()}

    @r.get("/caches")
    async def list_caches():
        return {name: c.stats() for name, c in caches.items()}

    @r.post("/studio", status_code=204, dependencies=studio_only)
    async def studio_report(request: Request):
        # The one debug route that changes anything: it adds to the report buffer.
        # application/json is required because a page on another website cannot send
        # it without a preflight, and the engine answers no preflight.
        kind = request.headers.get("content-type", "").split(";", 1)[0].strip(" \t").lower()
        if kind != "application/json":
            raise HTTPException(415, "A studio report is sent as application/json.")
        try:
            body = await _read_capped(request)
        except ClientDisconnect:
            # the page closed while it sent. Nothing to keep, and no traceback in the log.
            return Response(status_code=204)
        try:
            report = json.loads(body)
        except (ValueError, RecursionError):
            # not JSON, not UTF-8, an integer too long to read, or nested so deep
            # that the reader runs out of stack
            raise HTTPException(422, "A studio report is one JSON object.")
        if not isinstance(report, dict):
            raise HTTPException(422, "A studio report is one JSON object.")
        tab = report.get("tab")
        if not isinstance(tab, str) or not _TAB.fullmatch(tab):
            raise HTTPException(422, "tab is 8 to 32 characters of a-z and 0-9.")
        state = _clean_state(report.get("state"))
        errors = _clean_errors(report.get("errors"))
        studio.add(tab, state, errors)
        # the tab id and the counts, never a message or a stack
        log.info("event=debug.studio tab=%s state=%d errors=%d",
                 tab, state is not None, len(errors))
        return Response(status_code=204)

    @r.get("/studio", dependencies=studio_only)
    async def studio_reports():
        return studio.snapshot()

    return r
