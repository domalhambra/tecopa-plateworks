# app/serialize.py
"""(De)serialize a session payload to plain JSON-able data.

The session holds live Python objects -- Track dataclasses with numpy arrays and a
CompositionSpec. Both persistence (store.py) and the render queue (jobs.py) need
that state as plain data they can write to a row or hand to a worker, so the
conversion lives here in one place. Round-trips float64 exactly (JSON preserves
double precision), which matters for registration (invariant 5)."""
from __future__ import annotations
from dataclasses import fields
import numpy as np
from app.ingest import Track
from app.spec import CompositionSpec

def track_to_json(t: Track) -> dict:
    return {"track_id": t.track_id, "coords": t.coords.tolist(), "day": t.day}

def track_from_json(d: dict) -> Track:
    return Track(track_id=d["track_id"],
                 coords=np.asarray(d["coords"], dtype=float), day=d["day"])

def spec_to_json(s: CompositionSpec) -> dict:
    d = {f.name: getattr(s, f.name) for f in fields(s)}
    d["crop"] = list(s.crop)
    d["track_color"] = list(s.track_color)
    d["tracks"] = [np.asarray(a, float).tolist() for a in s.tracks]
    return d

def spec_from_json(d: dict) -> CompositionSpec:
    d = dict(d)
    d["crop"] = tuple(d["crop"])
    d["track_color"] = tuple(d["track_color"])
    d["tracks"] = [np.asarray(a, float) for a in d["tracks"]]
    return CompositionSpec(**d)

def dump_session(data: dict) -> dict:
    """A live session dict -> JSON-able dict (tracks/spec flattened)."""
    return {
        "region_id": data["region_id"],
        "hotspots": data["hotspots"],
        "tracks": [track_to_json(t) for t in data["tracks"]],
        "spec": spec_to_json(data["spec"]) if data.get("spec") else None,
    }

def load_session(d: dict) -> dict:
    """The inverse of dump_session: JSON-able dict -> live session dict."""
    return {
        "region_id": d["region_id"],
        "hotspots": d["hotspots"],
        "tracks": [track_from_json(t) for t in d["tracks"]],
        "spec": spec_from_json(d["spec"]) if d.get("spec") else None,
    }
