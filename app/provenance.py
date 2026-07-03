# app/provenance.py
"""Self-describing posters -- "the file is the artwork".

Every PNG final carries a provenance manifest in one compressed zTXt chunk: the full
CompositionSpec (via serialize.spec_to_json), the sha256 of each source GPX, and the
engine/schema version. That makes the file stateless-reprintable -- /api/reprint
re-renders it at print resolution from the PNG alone, no session and no DB row. Same
spec -> pixel-identical reprint (invariants 1 + 3); the manifest carries no clock, so
even the embedded file is deterministic.

SECURITY: a reprint spec is UNTRUSTED input, and render._draw_photos opens each
hotspot's `photo` path with Image.open. `sanitize_photos` keeps a photo only if its
real path stays inside the uploads dir (else drops the key) -- a crafted PNG must
never read arbitrary server files into a poster. Resizing safety is already covered by
spec.validate (aspect, the 120 MP ceiling, the zoom cap).

The manifest schema is a FOREVER-CONTRACT: a poster printed today must still reprint
after future upgrades. `manifest_version` gates that and spec_from_json already
tolerates added/removed spec fields; test_provenance freezes a v1 fixture to guard it.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from app import serialize
from app.spec import CompositionSpec

MANIFEST_KEY = "trailprint"        # the zTXt chunk keyword
MANIFEST_VERSION = 1
ENGINE = "trailprint"


def source_entry(data: bytes, filename: str | None) -> dict:
    """One source-file provenance record: name + sha256 + byte length."""
    return {"filename": filename or "track.gpx",
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data)}


def build_manifest(spec: CompositionSpec, sources: list | None = None) -> dict:
    """The provenance record for one poster: schema version, engine, region, the full
    spec, and the source-file hashes. A pure function of its inputs (no timestamp), so
    the same spec yields the same manifest bytes."""
    return {
        "manifest_version": MANIFEST_VERSION,
        "engine": ENGINE,
        "region_id": spec.region_id,
        "spec": serialize.spec_to_json(spec),
        "sources": list(sources or []),
    }


def _manifest_str(manifest: dict) -> str:
    # sorted keys + compact separators => byte-stable for a given manifest
    return json.dumps(manifest, separators=(",", ":"), sort_keys=True)


def manifest_pnginfo(manifest: dict) -> PngInfo:
    """A PngInfo carrying the manifest as a compressed zTXt chunk, to hand straight to
    Image.save(pnginfo=...). Embedding at encode time avoids a lossless re-encode."""
    info = PngInfo()
    info.add_text(MANIFEST_KEY, _manifest_str(manifest), zip=True)
    return info


def extract(png_bytes: bytes) -> dict | None:
    """The manifest dict embedded in a PNG, or None if the file carries none / is not a
    PNG / the chunk isn't valid JSON. Reads text chunks only -- never decodes pixels,
    so a decompression-bomb image can't blow up an inspect call."""
    try:
        with Image.open(io.BytesIO(png_bytes)) as im:
            raw = (getattr(im, "text", {}) or {}).get(MANIFEST_KEY)
            if raw is None:
                raw = im.info.get(MANIFEST_KEY)
    except Exception:
        return None
    if not raw:
        return None
    try:
        m = json.loads(raw)
    except Exception:
        return None
    return m if isinstance(m, dict) and "spec" in m else None


def manifest_to_spec(manifest: dict) -> CompositionSpec:
    """Rebuild the CompositionSpec from a manifest. Raises (KeyError / TypeError /
    ValueError) on a manifest that isn't a well-formed TrailPrint one; callers map to
    422. spec_from_json fills missing fields with dataclass defaults (forward-compat)."""
    return serialize.spec_from_json(manifest["spec"])


def sanitize_photos(spec: CompositionSpec, uploads_dir: str) -> CompositionSpec:
    """SECURITY (see module docstring): keep a hotspot photo only if its real path
    resolves inside uploads_dir; otherwise drop the key so the render skips it. Mutates
    and returns the spec. A path-traversal / absolute path (../../etc, /etc/passwd, a
    symlink out) is dropped rather than opened."""
    root = os.path.realpath(uploads_dir)
    prefix = root + os.sep
    for hs in spec.hotspots:
        p = hs.get("photo")
        if not p:
            continue
        rp = os.path.realpath(p)
        if rp != root and not rp.startswith(prefix):
            hs.pop("photo", None)
    return spec
