# app/debug.py
"""Read-only debug routes for the `tecopa` tool, behind TECOPA_DEBUG=1.

The studio is the only client the engine was built for, and it holds its own state.
A diagnosis from outside the browser needs to see what the engine holds: which jobs
are queued or failed, which sessions exist, what the caches are doing. These routes
show that and change nothing.

The gate is off by default. A route that lists sessions and tracks must not exist on
a host that did not ask for it, so with the gate off app.main never includes this
router and every /api/debug path is a plain 404. The macOS launcher sets the gate.

Design: docs/superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md."""
from __future__ import annotations
import os
import platform
import time
from fastapi import APIRouter, HTTPException
from app import provenance, serialize, session


def enabled(env=None) -> bool:
    """True only for the exact value "1". Anything else, the routes do not exist."""
    env = os.environ if env is None else env
    return env.get("TECOPA_DEBUG", "") == "1"


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


def build_router(*, queues: dict, caches: dict, started: float) -> APIRouter:
    """`queues` maps a name to a ThreadJobQueue, `caches` a name to a BaseCache,
    `started` is the engine's start time. Passed in, not imported, so this module
    never imports app.main."""
    r = APIRouter(prefix="/api/debug")

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
    async def session_detail(sid: str, full: int = 0):
        if not session.has(sid):
            raise HTTPException(404, "Unknown session")
        return _session_detail(sid, session.get(sid), bool(full))

    @r.get("/caches")
    async def list_caches():
        return {name: c.stats() for name, c in caches.items()}

    return r
