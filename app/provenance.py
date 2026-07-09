# app/provenance.py
"""Self-describing posters -- "the file is the artwork".

Every PNG final carries a provenance manifest in one compressed zTXt chunk: the full
CompositionSpec (via serialize.spec_to_json), the sha256 of each source GPX, and the
engine/schema version. That makes the file stateless-reprintable -- /api/reprint
re-renders it at print resolution from the PNG alone, no session and no DB row. Same
spec -> pixel-identical reprint (invariants 1 + 3); the manifest carries no clock, so
even the embedded file is deterministic.

SECURITY: a reprint spec is UNTRUSTED input. Pinned photos travel INSIDE the manifest
as embedded JPEG data URIs (build_final_spec), never as server file paths, so a crafted
PNG has no path to traverse -- `drop_unembedded_photos` keeps a hotspot photo only if it
is a size-bounded embedded JPEG and drops anything else, and `load_photo` decodes those
bytes in memory behind a pixel-count bomb guard. Resizing safety is already covered by
spec.validate (aspect, the 120 MP ceiling, the zoom cap).

The manifest schema is a FOREVER-CONTRACT: a poster printed today must still reprint
after future upgrades. `manifest_version` gates that and spec_from_json already
tolerates added/removed spec fields; test_provenance freezes a v1 fixture to guard it.
"""
from __future__ import annotations
import base64
import copy
import dataclasses
import hashlib
import io
import json
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from app import serialize
from app.spec import CompositionSpec, SpecError

MANIFEST_KEY = "trailprint"        # the zTXt chunk keyword
MANIFEST_VERSION = 1
ENGINE = "trailprint"

# Embedded photos ("the file is the whole record"): a pinned photo travels INSIDE the
# manifest as a render-resolution JPEG data URI -- never as a server file path. So a
# reprint reproduces the photo forever (no uploads dir, no TTL loss), and an untrusted
# manifest carries only inert bytes we decode in memory, never a path we could be
# tricked into reading off disk. build_final_spec canonicalizes a live session's photo
# paths to this form once, and the SAME spec feeds the render and the manifest, so the
# final and its reprint decode identical bytes (invariants 1 + 3 hold for photos too).
PHOTO_DATA_PREFIX = "data:image/jpeg;base64,"
PHOTO_EMBED_QUALITY = 82
MAX_PHOTO_EMBED_BYTES = 512 * 1024     # per-photo ceiling on the encoded JPEG
MAX_PHOTO_EMBED_PIXELS = 8_000_000     # decode guard for an untrusted embedded photo

# Living editions: the ancestor chain that lets a poster prove its lineage from the
# file alone is capped so a century of yearly editions can't unbound the manifest
# (past the cap the oldest ancestors drop; the file never refuses to embed).
LINEAGE_MAX = 100

# A manifest is UNTRUSTED input (see /api/continue, /api/reprint). bound_geometry
# refuses a crafted spec whose track/point/hotspot counts would balloon the render
# before validate()/rasterize even runs -- the geometry-bomb guard.
MAX_MANIFEST_TRACKS = 4096
MAX_MANIFEST_POINTS = 5_000_000
MAX_MANIFEST_HOTSPOTS = 64


def source_entry(data: bytes, filename: str | None) -> dict:
    """One source-file provenance record: name + sha256 + byte length."""
    return {"filename": filename or "track.gpx",
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data)}


def build_manifest(spec: CompositionSpec, sources: list | None = None,
                   lineage: list | None = None, animation: dict | None = None) -> dict:
    """The provenance record for one poster: schema version, engine, region, the full
    spec, and the source-file hashes. A pure function of its inputs (no timestamp), so
    the same spec yields the same manifest bytes.

    Living editions: from the SECOND edition on, the manifest also carries `edition`
    and `lineage` (the ancestor chain, newest-capped at LINEAGE_MAX). Time-lapse: an
    animated file also carries an `animation` block (the pacing + render dpi) so the
    film re-renders from the file alone. All three keys are OMITTED when absent, so
    every pre-feature manifest -- including the frozen v1 / wallpaper / edition fixtures
    -- is byte-for-byte unchanged and MANIFEST_VERSION stays 1 (purely additive)."""
    m = {
        "manifest_version": MANIFEST_VERSION,
        "engine": ENGINE,
        "region_id": spec.region_id,
        "spec": serialize.spec_to_json(spec),
        "sources": list(sources or []),
    }
    edition = int(getattr(spec, "edition", 1) or 1)
    if edition >= 2:
        m["edition"] = edition
        m["lineage"] = list(lineage or [])[-LINEAGE_MAX:]   # keep newest, drop oldest
    if animation is not None:
        m["animation"] = dict(animation)
    return m


def bound_geometry(spec: CompositionSpec) -> CompositionSpec:
    """Refuse a manifest-derived spec whose geometry is a resource bomb, BEFORE
    validate()/rasterize touch it. A crafted PNG could declare millions of points or
    thousands of tracks that sail past validate() (which checks the crop/sheet, not the
    track arrays) and only blow up inside the coverage loops. Raises SpecError (the API
    maps it to 422), so both /api/continue and /api/reprint get the same guard."""
    tracks = spec.tracks or []
    if len(tracks) > MAX_MANIFEST_TRACKS:
        raise SpecError(f"manifest declares {len(tracks)} tracks "
                        f"(max {MAX_MANIFEST_TRACKS})")
    total = 0
    for t in tracks:
        shape = getattr(t, "shape", None)
        if shape is not None:
            # a crafted manifest can carry (N,3) / 1-D / 0-D track arrays that sail
            # past validate() (it never inspects the track shapes) and then blow up
            # the (x, y) unpacking in projection / coverage. Demand (N, 2) here.
            if len(shape) != 2 or shape[1] != 2:
                raise SpecError("manifest track arrays must be shaped (N, 2)")
            total += int(shape[0])
        else:
            total += len(t)                            # a plain point list
    if total > MAX_MANIFEST_POINTS:
        raise SpecError(f"manifest declares {total} track points "
                        f"(max {MAX_MANIFEST_POINTS})")
    if len(spec.hotspots or []) > MAX_MANIFEST_HOTSPOTS:
        raise SpecError(f"manifest declares {len(spec.hotspots)} hotspots "
                        f"(max {MAX_MANIFEST_HOTSPOTS})")
    return spec


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


def is_embedded_photo(value) -> bool:
    """True if a hotspot's `photo` is an embedded JPEG data URI (the record's own bytes)
    rather than a live-session file path."""
    return isinstance(value, str) and value.startswith(PHOTO_DATA_PREFIX)


def _encode_photo(path: str, box_px: int) -> str | None:
    """Read a photo file and return a render-resolution JPEG data URI, or None if it
    can't be read/encoded within the per-photo byte ceiling. `box_px` is the pixel long
    edge the poster paints the photo at (photo_box_in * final_dpi), so the embedded copy
    is exactly what the sheet shows -- never larger, so the file stays lean. Encoding is
    deterministic for fixed pixels (invariant 3: the manifest stays byte-stable)."""
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((box_px, box_px))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=PHOTO_EMBED_QUALITY, optimize=True)
    except Exception:
        return None
    raw = buf.getvalue()
    if len(raw) > MAX_PHOTO_EMBED_BYTES:
        return None
    return PHOTO_DATA_PREFIX + base64.b64encode(raw).decode("ascii")


def build_final_spec(spec: CompositionSpec, box_px: int) -> CompositionSpec:
    """Canonicalize a spec's hotspot photos to embedded JPEG data URIs at `box_px`,
    returning a COPY (the live session spec is untouched). A photo already embedded (a
    continued edition, or a re-render) is kept verbatim -- idempotent, so no generation
    loss and the bytes stay deterministic. A path that can't be read/encoded is dropped,
    never fails the deliverable. Feed the returned spec to BOTH the render and the
    manifest so the final and its reprint decode identical bytes (invariants 1 + 3)."""
    hotspots = copy.deepcopy(list(spec.hotspots or []))
    for hs in hotspots:
        if not isinstance(hs, dict):
            continue
        p = hs.get("photo")
        if not p or is_embedded_photo(p):
            continue                             # absent, or already the record's bytes
        enc = _encode_photo(p, box_px) if isinstance(p, str) else None
        if enc is None:
            hs.pop("photo", None)                # unreadable / oversized: drop cleanly
        else:
            hs["photo"] = enc
    return dataclasses.replace(spec, hotspots=hotspots)


def _embedded_within_caps(value: str) -> bool:
    """True if an embedded photo's base64 decodes to non-empty bytes under the per-photo
    ceiling. Cheap (no image decode); the pixel-count bomb guard is in load_photo."""
    try:
        raw = base64.b64decode(value[len(PHOTO_DATA_PREFIX):], validate=True)
    except Exception:
        return False
    return 0 < len(raw) <= MAX_PHOTO_EMBED_BYTES


def drop_unembedded_photos(spec: CompositionSpec) -> CompositionSpec:
    """SECURITY (see module docstring): for an UNTRUSTED manifest-derived spec, keep a
    hotspot photo only if it is a well-formed, size-bounded embedded JPEG data URI; drop
    anything else -- a file path, a non-string, an oversized blob. Replaces the old
    filesystem path sanitizer: a manifest can no longer carry a server path at all, so
    there is nothing to traverse. The photo is inert bytes decoded in memory, or it is
    dropped. Mutates and returns the spec."""
    for hs in spec.hotspots:
        if not isinstance(hs, dict):     # a crafted manifest can carry non-dict entries
            continue
        p = hs.get("photo")
        if not p:
            continue
        if not (is_embedded_photo(p) and _embedded_within_caps(p)):
            hs.pop("photo", None)
    return spec


def load_photo(value: str) -> Image.Image:
    """Open a hotspot photo for rendering, as an RGB image. An embedded (data URI) photo
    decodes from in-memory bytes with a pixel-count guard -- an untrusted manifest could
    embed a decompression bomb whose small JPEG declares huge dimensions. A bare path is
    trusted server state (a live session's own upload) and is opened directly. Raises on
    anything unreadable; the render skips a failed photo so one bad file can't fail a
    poster."""
    if is_embedded_photo(value):
        raw = base64.b64decode(value[len(PHOTO_DATA_PREFIX):], validate=True)
        im = Image.open(io.BytesIO(raw))
        w, h = im.size                                   # header read; no full decode yet
        if w * h > MAX_PHOTO_EMBED_PIXELS:
            raise ValueError("embedded photo exceeds the pixel guard")
        return im.convert("RGB")
    return Image.open(value).convert("RGB")
