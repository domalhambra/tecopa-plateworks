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

def _arr_or_none(a):
    """Per-vertex float array -> JSON list with null for NaN (JSON has no NaN), or None."""
    if a is None:
        return None
    return [None if not np.isfinite(v) else float(v) for v in a]

def _none_to_nan(lst):
    if lst is None:
        return None
    return np.asarray([np.nan if v is None else float(v) for v in lst], dtype=float)

def track_to_json(t: Track) -> dict:
    d = {"track_id": t.track_id, "coords": t.coords.tolist(), "day": t.day}
    # Journey Light session data (v1.9): omitted when absent so pre-feature rows are
    # unaffected. Per-vertex arrays store NaN as null (JSON has no NaN token).
    if t.t0 is not None:
        d["t0"] = t.t0
    if t.t1 is not None:
        d["t1"] = t.t1
    if t.lonlat is not None:
        d["lonlat"] = list(t.lonlat)
    if t.coords_t is not None:
        d["coords_t"] = _arr_or_none(t.coords_t)
    if t.summit_t is not None:
        d["summit_t"] = t.summit_t
        d["summit_ele"] = t.summit_ele
    return d

def track_from_json(d: dict) -> Track:
    # .get(...) drift tolerance: a row written by a pre-Journey-Light build lacks these.
    ll = d.get("lonlat")
    return Track(track_id=d["track_id"],
                 coords=np.asarray(d["coords"], dtype=float), day=d["day"],
                 t0=d.get("t0"), t1=d.get("t1"),
                 lonlat=tuple(ll) if ll is not None else None,
                 coords_t=_none_to_nan(d.get("coords_t")),
                 summit_t=d.get("summit_t"), summit_ele=d.get("summit_ele"))

def spec_to_json(s: CompositionSpec) -> dict:
    d = {f.name: getattr(s, f.name) for f in fields(s)}
    d["crop"] = list(s.crop)
    d["tracks"] = [np.asarray(a, float).tolist() for a in s.tracks]
    # the additive contract (docs/MANIFEST.md): a key added AFTER a poster was
    # printed is omitted at its default, so /api/reprint re-stamps a pre-credit
    # manifest byte-identically -- emitting "credit_text": "" would break the
    # forever-contract's sha256 check. spec_from_json refills the default.
    if not d["credit_text"]:
        del d["credit_text"]
    # same contract for the High-relief knob: 0.0 (the classic top-down sheet) is the
    # pre-feature look, so it is omitted and a pre-oblique manifest re-stamps
    # byte-identically; spec_from_json refills the 0.0 default.
    if not d["oblique"]:
        del d["oblique"]
    # Journey Light (v1.9): archival is the pre-feature light, so all three light keys are
    # omitted at that default -- a pre-Journey-Light manifest re-stamps byte-identically,
    # and spec_from_json refills the defaults. Only a "journey" poster carries the
    # resolved sun into the manifest (that IS the record; the timestamps never ride).
    if d["light_mode"] == "archival":
        for k in ("light_mode", "sun_azimuth_deg", "sun_altitude_deg", "golden_strength"):
            del d[k]
    # elevation profile + track coloring: omitted at their off/none defaults, same contract.
    if not d["profile"]:
        del d["profile"]
        del d["profile_height_in"]
    if d["track_color_by"] == "none":
        del d["track_color_by"]
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
