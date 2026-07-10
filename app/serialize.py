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
    d["tracks"] = [np.asarray(a, float).tolist() for a in s.tracks]
    return d

def spec_from_json(d: dict) -> CompositionSpec:
    d = dict(d)
    d["crop"] = tuple(d["crop"])
    if "track_rgb" in d:
        d["track_rgb"] = tuple(d["track_rgb"])   # JSON lists -> the tuple validate expects
    d["tracks"] = [np.asarray(a, float) for a in d["tracks"]]
    # UNTRUSTED manifests deserialize here too (provenance.manifest_to_spec): a crafted
    # spec can carry a non-list `hotspots` (null / a number) or `track_days`, which
    # every consumer iterates (drop_unembedded_photos, bound_geometry, _stats_line, the
    # continue rebuild). Coerce to safe shapes so a hostile file is a clean 422/no-op,
    # never a 500. A well-formed spec and every persisted session row is already
    # list-shaped here, so this is a no-op for them.
    if not isinstance(d.get("hotspots"), list):
        d["hotspots"] = []
    if "track_days" in d and not isinstance(d["track_days"], list):
        d["track_days"] = None
    # tolerate schema drift in persisted rows, both directions: a row written by an
    # older build lacks new fields (dataclass defaults fill them), and a row written
    # before a field was REMOVED (e.g. track_color) must not TypeError the load.
    known = {f.name for f in fields(CompositionSpec)}
    return CompositionSpec(**{k: v for k, v in d.items() if k in known})

def dump_session(data: dict) -> dict:
    """A live session dict -> JSON-able dict (tracks/spec flattened)."""
    return {
        "region_id": data["region_id"],
        "hotspots": data["hotspots"],
        "tracks": [track_to_json(t) for t in data["tracks"]],
        "spec": spec_to_json(data["spec"]) if data.get("spec") else None,
        # source-file provenance (self-describing posters): carried so the final's
        # embedded manifest can hash-name the GPX. .get keeps old rows loadable.
        "sources": data.get("sources", []),
        # living editions: the session's authoritative edition counter + ancestor
        # chain (set by /api/continue), stamped onto the spec + manifest at final
        # time. .get -> a pre-feature row loads as an unlabeled first edition.
        "edition": data.get("edition", 1),
        "lineage": data.get("lineage", []),
    }

def load_session(d: dict) -> dict:
    """The inverse of dump_session: JSON-able dict -> live session dict."""
    return {
        "region_id": d["region_id"],
        "hotspots": d["hotspots"],
        "tracks": [track_from_json(t) for t in d["tracks"]],
        "spec": spec_from_json(d["spec"]) if d.get("spec") else None,
        "sources": d.get("sources", []),      # drift tolerance: absent in pre-feature rows
        "edition": d.get("edition", 1),        # living editions (absent -> first edition)
        "lineage": d.get("lineage", []),
    }
