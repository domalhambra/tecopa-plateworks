# app/debug.py
"""Read-only debug routes for the `tecopa` tool, behind TECOPA_DEBUG=1.

The studio is the only client the engine was built for, and it holds its own state.
A diagnosis from outside the browser needs to see what the engine holds: which jobs
are queued or failed, which sessions exist, what the caches are doing. These routes
show that and change nothing.

The gate is off by default. A route that lists sessions and tracks must not exist on
a host that did not ask for it, so with the gate off app.main never includes this
router and every /api/debug path is a plain 404. The macOS launcher sets the gate.
With the gate on, the routes answer only a request whose Host header is local.

Design: docs/superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md."""
from __future__ import annotations
import inspect
import math
import os
import platform
import re
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from app import geo, provenance, serialize, session


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

    return r
