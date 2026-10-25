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
import math
import os
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from app import serialize
from app.spec import CompositionSpec, SpecError, PHOTO_SOURCES

MANIFEST_KEY = "trailprint"        # the zTXt chunk keyword -- FROZEN v1 format keyword: it
                                   # predates the Tecopa Plateworks rename and every existing
                                   # poster carries it; renaming would orphan those files.
MANIFEST_VERSION = 1
ENGINE = "tecopa-plateworks"
# Manifests written by earlier engine names carry "trailprint" (pre 2026-07-19) or
# "tecopa-printworks" (2026-07-19..21); readers treat all three as this engine
# (docs/MANIFEST.md). Nothing in this module gates on the engine value.
LEGACY_ENGINES = ("trailprint", "tecopa-printworks")
ENGINE_URL = "https://github.com/domalhambra/tecopa-plateworks"
# Must track the repo's real name, not a redirect.

def _engine_version() -> str:
    """The build identity stamped into every manifest. With the forever-contract
    retired (docs/superpowers/specs/2026-07-27-retire-the-forever-contract-design.md),
    cross-build drift is RECORDED rather than prevented: when a reprint stops matching,
    the file says which build painted it. TECOPA_ENGINE_VERSION overrides for packaged
    builds; otherwise the git commit of the running checkout; "unknown" headless."""
    v = os.environ.get("TECOPA_ENGINE_VERSION")
    if v:
        return v
    try:
        import subprocess
        return subprocess.run(
            ["git", "-C", os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
             "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True).stdout.strip() or "unknown"
    except Exception:
        return "unknown"

ENGINE_VERSION = _engine_version()


class ManifestError(SpecError):
    """An untrusted manifest can't be turned into a safe, renderable spec because it isn't
    a well-formed Tecopa Plateworks manifest. A SpecError subclass, so a single `except SpecError`
    in the API catches it alongside the geometry/zoom gates as one 422 (see
    spec_from_manifest)."""

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
# PIL refuses to open a PNG whose zTXt chunk holds more than 1 MiB (1,048,576 bytes,
# ImageFile.MAX_TEXT_CHUNK): Image.open() raises and extract() returns None. The file is
# the record, openable by anyone with plain PIL, so a record the order pipeline writes
# keeps its WHOLE manifest, photos included, under this budget. Never raise PIL's limit.
MAX_RECORD_MANIFEST_BYTES = 900_000
PHOTO_QUALITY_LADDER = (82, 72, 62, 52)   # JPEG qualities tried at the full size, in order
RECORD_SHRINK = 0.85                   # then each step shrinks the size, at quality 62
RECORD_SHRINK_QUALITY = 62
RECORD_MIN_SIDE_PX = 16                # a photo that must go smaller cannot be recorded

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
                   lineage: list | None = None, animation: dict | None = None,
                   region_pack: dict | None = None) -> dict:
    """The provenance record for one poster: schema version, engine, region, the full
    spec, and the source-file hashes. A pure function of its inputs (no timestamp), so
    the same spec yields the same manifest bytes.

    Living editions: from the SECOND edition on, the manifest also carries `edition`
    and `lineage` (the ancestor chain, newest-capped at LINEAGE_MAX). Time-lapse: an
    animated file also carries an `animation` block (the pacing + render dpi) so the
    film re-renders from the file alone. Plate identity: a file rendered against a
    hash-manifested region also carries a `region_pack` block (region_pack_block) so a
    reprint can verify it runs against the SAME terrain. All four keys are OMITTED when
    absent, so every pre-feature manifest -- including the frozen v1 / wallpaper /
    edition fixtures -- is byte-for-byte unchanged and MANIFEST_VERSION stays 1
    (purely additive)."""
    m = {
        "manifest_version": MANIFEST_VERSION,
        "engine": ENGINE,
        "engine_version": ENGINE_VERSION,
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
    if region_pack is not None:
        m["region_pack"] = dict(region_pack)
    return m


def region_pack_block(region_dir, labels: bool = False, biome: bool = False,
                      dry_lakes: bool = False) -> dict | None:
    """The plate's identity, for the manifest's `region_pack` block: the sha256 of each
    plate asset the RENDER reads, hashed from the bytes on disk -- never trusted from
    sources.json, whose recorded hashes can drift from the assets (a re-prep that
    crashed before the sidecar write, a fresh clone whose DEM is a synthetic stand-in)
    and would then stamp -- and verify -- a plate the pixels were never painted with.
    sources.json still gates the feature: its asset LIST names the plate's files, and a
    hand-built plate without one gets None (callers then OMIT the block; the file stays
    printable, just unverifiable). USGS re-flies 3DEP; a silently rebuilt plate would
    reprint an old poster *differently* -- this block is what lets a reprint detect
    that. Pixel-honesty bounds the hash: overview.png only feeds the browser aim canvas
    (rasterize never reads it), labels.json is read only when the spec draws labels
    (`labels`), and landcover.tif only when the biome tint is on (`biome`) -- none of
    them enters the identity of a poster whose pixels never touched it, otherwise a
    routine GNIS labels rebake (or an NLCD refresh) would refuse exact-identical
    reprints of every poster that never drew them. `pack_version` is a short digest
    of the sorted asset hashes (one id to name the whole plate); `assets` is the
    per-file detail. No caching: read at final/submit/verify time, never per frame."""
    try:
        with open(os.path.join(region_dir, "sources.json")) as f:
            names = sorted(json.load(f)["assets"])
    except Exception:
        return None
    assets = {}
    for name in names:
        if name == "overview.png":                   # aim canvas only, never a pixel
            continue
        if name == "labels.json" and not labels:     # read only when labels are drawn
            continue
        if name == "landcover.tif" and not biome:    # read only when the tint is on
            continue
        if name == "playa.json" and not dry_lakes:   # read only when dry lakes draw
            # Same pixel-honesty rule, and here it is what makes the feature shippable
            # at all: baking playa onto an existing plate must not change the identity
            # of posters that never draw it, or every poster ever printed would report
            # a mismatch on reprint the day dry lakes landed.
            continue
        try:
            h = hashlib.sha256()
            with open(os.path.join(region_dir, name), "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
        except OSError:
            continue    # listed but absent paints nothing; it can't be plate identity
        assets[name] = h.hexdigest()
    if not assets:
        return None
    joined = "\n".join(f"{name}:{assets[name]}" for name in sorted(assets))
    return {"pack_version": hashlib.sha256(joined.encode()).hexdigest()[:12],
            "assets": assets}


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
    Image.save(pnginfo=...). Embedding at encode time avoids a lossless re-encode.
    Share copies (embed_spec=false) pass manifest=None to the encoders and skip
    pnginfo entirely -- no manifest. (The plain-tEXt resurrection note that used to
    ride beside the manifest was retired with the forever-contract; files already
    printed keep theirs, and readers never depended on it.)"""
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
    ValueError) on a manifest that isn't a well-formed Tecopa Plateworks one; callers map to
    422. spec_from_json fills missing fields with dataclass defaults (forward-compat)."""
    return serialize.spec_from_json(manifest["spec"])


def is_embedded_photo(value) -> bool:
    """True if a hotspot's `photo` is an embedded JPEG data URI (the record's own bytes)
    rather than a live-session file path."""
    return isinstance(value, str) and value.startswith(PHOTO_DATA_PREFIX)


class RecordBudgetError(ValueError):
    """A photo cannot be embedded in the record within its share of the manifest budget."""


def _is_square_cut(hs: dict) -> bool:
    """True if the renderer cuts this hotspot's photo to a square: it has a `box` offset
    or a `crop` focus the renderer reads (render._photo_box_offset / _photo_crop_focus,
    so their finiteness test, render._finite_real, is the one used here). Without either
    the photo is fitted, as it always was."""
    from app import render           # here: render imports this module
    return (render._photo_box_offset(hs) is not None
            or render._photo_crop_focus(hs) is not None)


def _fit_scale(w: int, h: int, edge: int, square: bool) -> float:
    """The scale that puts a photo's SHORT side (a square cut) or LONG side (a fitted
    photo) at `edge` pixels, never above 1 (the source is not upscaled) and never past
    MAX_PHOTO_EMBED_PIXELS."""
    side = min(w, h) if square else max(w, h)
    return min(1.0, edge / side, math.sqrt(MAX_PHOTO_EMBED_PIXELS / (w * h)))


def _scaled(im: Image.Image, scale: float) -> Image.Image:
    """`im` at `scale` (LANCZOS), or `im` itself at 1. Rounding never goes past the pixel
    guard."""
    if scale >= 1.0:
        return im
    tw, th = max(1, round(im.width * scale)), max(1, round(im.height * scale))
    while tw * th > MAX_PHOTO_EMBED_PIXELS:
        tw, th = max(1, tw - 1), max(1, th - 1)
    return im.resize((tw, th), Image.LANCZOS)


def _jpeg(im: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _data_uri(raw: bytes) -> str:
    return PHOTO_DATA_PREFIX + base64.b64encode(raw).decode("ascii")


def _encode_photo(path: str, box_px: int, square: bool = False) -> str | None:
    """Read a photo file and return a render-resolution JPEG data URI, or None if it
    can't be read/encoded within the per-photo byte ceiling. `box_px` is the pixel edge
    the poster paints the photo at (photo_box_in * final_dpi). A fitted photo is its
    LONG side at `box_px`, so the embedded copy is exactly what the sheet shows -- never
    larger, so the file stays lean.

    A `square` photo (the hotspot has a box or a crop) is cut to a box x box square from
    this copy, so its SHORT side must carry `box_px`: fitting the long side would upscale
    a 3:2 photo's square about 1.5x. That copy is never larger than the source and never
    past MAX_PHOTO_EMBED_PIXELS. If it breaks the byte ceiling the JPEG quality goes
    down (PHOTO_QUALITY_LADDER), never the size: the print is never silently soft.
    Encoding is deterministic for fixed pixels (invariant 3)."""
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            if not square:
                im.thumbnail((box_px, box_px))
                qualities = (PHOTO_EMBED_QUALITY,)
            else:
                im = _scaled(im, _fit_scale(im.width, im.height, box_px, True))
                qualities = PHOTO_QUALITY_LADDER
            for quality in qualities:
                raw = _jpeg(im, quality)
                if len(raw) <= MAX_PHOTO_EMBED_BYTES:
                    return _data_uri(raw)
    except Exception:
        return None
    return None


def _record_photo(path: str, box_px: int, square: bool, room: int):
    """A photo for the record, as a data URI of at most `room` characters, with a flag
    that says it was reduced below the print's box resolution; None when the file cannot
    be read. The ladder is fixed, so the same input gives the same bytes (invariant 3):
    JPEG quality 82, 72, 62, 52 at the size the print uses (the short side of a square cut
    at `box_px`, else the long side; the source is never upscaled), then the size shrinks
    by RECORD_SHRINK per step at quality RECORD_SHRINK_QUALITY until the copy fits. Raises
    RecordBudgetError when it fits only below RECORD_MIN_SIDE_PX."""
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            scale0 = _fit_scale(im.width, im.height, box_px, square)
            full = _scaled(im, scale0)
            for quality in PHOTO_QUALITY_LADDER:
                uri = _data_uri(_jpeg(full, quality))
                if len(uri) <= room:
                    return uri, False
            step = 0
            while True:
                step += 1
                scale = scale0 * RECORD_SHRINK ** step
                if min(im.width, im.height) * scale < RECORD_MIN_SIDE_PX:
                    raise RecordBudgetError("a photo does not fit the record")
                uri = _data_uri(_jpeg(_scaled(im, scale), RECORD_SHRINK_QUALITY))
                if len(uri) <= room:
                    return uri, True
    except RecordBudgetError:
        raise
    except Exception:
        return None


def build_record_manifest(spec: CompositionSpec, box_px: int, region_pack: dict | None = None,
                          budget: int | None = None):
    """The manifest of a print's record (work/record.png) and the record's spec, whose
    hotspot photos are embedded JPEGs. Returns (record spec, manifest, reduced); a COPY,
    `spec` is untouched (it keeps the photos as paths: the print renders from those,
    full resolution, so its sharpness never depends on the record's size).

    The WHOLE manifest stays within `budget` (MAX_RECORD_MANIFEST_BYTES, see there).
    Each photo's share is (budget - the manifest without these photos) / the photo count;
    _record_photo fits each into its share. `reduced` is True when a photo had to go
    below the print's box resolution. A photo that cannot be read is left out of the
    record spec (the caller compares counts); one that cannot fit raises
    RecordBudgetError. A photo that is already embedded is kept verbatim."""
    budget = MAX_RECORD_MANIFEST_BYTES if budget is None else budget
    hotspots = copy.deepcopy(list(spec.hotspots or []))
    todo = [hs for hs in hotspots if isinstance(hs, dict) and hs.get("photo")
            and not is_embedded_photo(hs["photo"])]
    paths = [hs.pop("photo") for hs in todo]
    base = len(_manifest_str(build_manifest(
        dataclasses.replace(spec, hotspots=hotspots), region_pack=region_pack)))
    overhead = len(',"photo":""')
    share = (budget - base) // len(todo) if todo else 0
    reduced = False
    for hs, path in zip(todo, paths):
        got = (_record_photo(path, box_px, _is_square_cut(hs), share - overhead)
               if isinstance(path, str) else None)
        if got is None:
            continue                             # unreadable: left out, the caller counts
        hs["photo"], was_reduced = got
        reduced = reduced or was_reduced
    record = dataclasses.replace(spec, hotspots=hotspots)
    return record, build_manifest(record, region_pack=region_pack), reduced


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
        enc = (_encode_photo(p, box_px, square=_is_square_cut(hs))
               if isinstance(p, str) else None)
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


def _finite_number(v) -> bool:
    """A real, finite JSON number. A bool is not one (True would pass as 1)."""
    if isinstance(v, bool):
        return False
    if isinstance(v, int):                  # always finite; math.isfinite(10**400) raises
        return True
    return isinstance(v, float) and math.isfinite(v)


def bound_photo_keys(spec: CompositionSpec) -> CompositionSpec:
    """SECURITY: bound the keys that place a photo, for an UNTRUSTED manifest-derived
    spec (order photos, B1). A hotspot's `box` is {"dx_in","dy_in"}, finite numbers whose
    magnitude is at most the sheet's larger side in inches; `crop` is {"cx","cy"}, finite
    and within 0..1; `source` is one of PHOTO_SOURCES. A malformed key is dropped from
    its hotspot -- the hotspot, and its other keys, stay -- so a crafted file is a
    cleaner render, never an exception. A well-formed key is rebuilt with only its named
    members, so nothing rides along inside it. Mutates and returns the spec. Call it
    AFTER validate: the sheet size it bounds against is then a checked pair of numbers."""
    limit = max(spec.print_w_in, spec.print_h_in)
    for hs in spec.hotspots:
        if not isinstance(hs, dict):
            continue
        box = hs.get("box")
        if "box" in hs:
            if (isinstance(box, dict)
                    and _finite_number(box.get("dx_in")) and _finite_number(box.get("dy_in"))
                    and abs(box["dx_in"]) <= limit and abs(box["dy_in"]) <= limit):
                hs["box"] = {"dx_in": box["dx_in"], "dy_in": box["dy_in"]}
            else:
                del hs["box"]
        crop = hs.get("crop")
        if "crop" in hs:
            if (isinstance(crop, dict)
                    and _finite_number(crop.get("cx")) and _finite_number(crop.get("cy"))
                    and 0 <= crop["cx"] <= 1 and 0 <= crop["cy"] <= 1):
                hs["crop"] = {"cx": crop["cx"], "cy": crop["cy"]}
            else:
                del hs["crop"]
        if "source" in hs and not (isinstance(hs["source"], str)
                                   and hs["source"] in PHOTO_SOURCES):
            del hs["source"]
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


def spec_from_manifest(manifest: dict) -> CompositionSpec:
    """THE one door an UNTRUSTED manifest passes through to become a safe, render-ready
    spec. Every file-consuming verb (/api/reprint, /api/continue, and any future one)
    calls this, so the entire untrusted-input guard chain lives in ONE audited place and
    a new verb inherits it by construction instead of re-deriving (and possibly
    mis-copying) it:

      1. manifest_to_spec        -- parse the manifest; a malformed one -> ManifestError.
      2. drop_unembedded_photos  -- keep only size-bounded embedded photos, so no server
                                    path can ride in on a hotspot (nothing to traverse).
      3. bound_geometry          -- refuse a geometry bomb (millions of points / thousands
                                    of tracks) BEFORE validate/rasterize allocate anything.
      4. validate(final_dpi)     -- aspect, the 120 MP output ceiling, the zoom cap.
      5. bound_photo_keys        -- a photo's box / crop / source: finite, on the sheet,
                                    in range, or dropped from its hotspot.

    Raises only SpecError (ManifestError for a bad manifest; ZoomTooTight / OutputTooLarge
    / plain SpecError for a bad geometry), so one `except SpecError` at the call site maps
    every rejection to a 422. Region AVAILABILITY is intentionally NOT checked here -- it
    needs the server's region registry and a verb-specific message -- so the caller does
    that on the returned spec."""
    try:
        spec = manifest_to_spec(manifest)
    except SpecError:
        raise
    except Exception as e:
        raise ManifestError("This file's Tecopa Plateworks manifest is malformed.") from e
    # The same rule for the three steps below. validate() names a field of the wrong
    # type itself; this catches what it does not name (a hotspot list that is a number,
    # a track that is not a list), so the promise above holds: only SpecError leaves.
    try:
        drop_unembedded_photos(spec)
        bound_geometry(spec)
        spec.validate(spec.final_dpi())
        bound_photo_keys(spec)
    except SpecError:
        raise
    except Exception as e:
        raise ManifestError("This file's Tecopa Plateworks manifest is malformed.") from e
    return spec
