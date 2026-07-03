# app/main.py
import io, json, os, shutil, time
import logging
from typing import List, Optional
from PIL import Image
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.geo import (crs_to_overview_px, crop_px_to_crs_window,
                     overview_px_to_crs, starter_crop)
from app.ingest import load_tracks
from app.density import hotspots
from app.spec import CompositionSpec, SpecError
from app import session, render, regions, blobs, jobs, logconfig, provenance

logconfig.setup_logging()
log = logging.getLogger("trailprint.api")

# The registry replaces the old single hardcoded region: every regions/<id> built
# by region_prep.py is now selectable. Discovered once at import. The root is
# env-overridable (TRAILPRINT_REGIONS) so a deploy or the test harness can point
# the app at a different region tree without editing code.
REGIONS_ROOT = os.environ.get("TRAILPRINT_REGIONS", "regions")
REGIONS = regions.discover(REGIONS_ROOT)

PROOF_DPI = 96    # cheap mid-fidelity preview
FINAL_DPI = 300   # print resolution -- the zoom cap is judged against THIS

# Lifecycle TTL (red-team V1-8): a back-to-back concierge day otherwise leaks disk +
# memory (finals, blobs, job records, uploaded photos were never evicted). Default 24h;
# set 0 to disable eviction (e.g. an archival run).
TTL_SECONDS = float(os.environ.get("TRAILPRINT_TTL_SECONDS", 86400))

# server foundation (v1.3): outputs go to a blob store, finals render off the
# request thread via a job queue. Both are local impls behind interfaces that a
# networked store / broker drops into later (see blobs.py, jobs.py).
BLOBS = blobs.LocalBlobs(os.environ.get("TRAILPRINT_BLOBS", "blobs"), ttl_seconds=TTL_SECONDS)
# one render at a time by default: a 300-dpi final peaks at ~5 GB RSS, so unbounded
# concurrency could OOM the operator's machine on double-click (red-team).
QUEUE = jobs.ThreadJobQueue(
    ttl_seconds=TTL_SECONDS,
    max_concurrency=int(os.environ.get("TRAILPRINT_RENDER_CONCURRENCY", 1)))

app = FastAPI()

# The deliverable isn't only a print: a PDF suits "an image someone saves for
# themselves" and is what a print shop asks for anyway (V1-10). Both encode the
# same rasterized spec; PDF embeds the page size via `resolution`.
FINAL_FORMATS = {"png": ("PNG", "image/png"), "pdf": ("PDF", "application/pdf")}

# sRGB ICC profile for the final PNG so a print lab / color-managed viewer reads our
# colors as intended instead of guessing (V1-10 print-correctness). Pillow bundles
# littlecms; fall back to no profile rather than fail the render if it's absent.
try:
    from PIL import ImageCms
    SRGB_PROFILE = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
except Exception:                                          # pragma: no cover
    SRGB_PROFILE = None

def _encode_final(img, fmt: str, manifest=None) -> bytes:
    pil_fmt, _ = FINAL_FORMATS[fmt]
    buf = io.BytesIO()
    if fmt == "pdf":
        # resolution -> true page size (300 dpi). Pillow embeds RGB PDF pages as JPEG;
        # the libjpeg defaults (quality 75, 4:2:0 chroma subsampling) fringe exactly
        # our crisp features -- a saturated gold line on desaturated paper -- so pass
        # print-grade encoder params through (they reach the embedded JPEG encoder).
        # (Pillow cannot embed a PDF output intent; the PNG carries the sRGB profile
        # AND the reprint manifest -- so self-describing posters are PNG-only.)
        img.save(buf, pil_fmt, resolution=FINAL_DPI, quality=95, subsampling=0)
    else:
        kw = {"dpi": (FINAL_DPI, FINAL_DPI)}                # a print shop reads true size
        if SRGB_PROFILE:
            kw["icc_profile"] = SRGB_PROFILE
        if manifest is not None:
            # the provenance manifest, one compressed zTXt chunk -- the file becomes
            # stateless-reprintable (POST /api/reprint). Embedded at encode time so we
            # never re-encode the PNG (self-describing posters).
            kw["pnginfo"] = provenance.manifest_pnginfo(manifest)
        img.save(buf, pil_fmt, **kw)
    return buf.getvalue()

def _require_format(fmt: str) -> str:
    fmt = (fmt or "png").lower()
    if fmt not in FINAL_FORMATS:
        raise HTTPException(422, f"format must be one of {sorted(FINAL_FORMATS)}")
    return fmt

def _render_to_blob(spec, region_dir, key, fmt="png", manifest=None):
    """The render worker: rasterize the stamped spec at print DPI and store the
    encoded output. Runs on a queue thread, so it touches only its arguments."""
    img = render.rasterize(spec, dpi=FINAL_DPI, region_dir=region_dir, watermark=False)
    BLOBS.put(key, _encode_final(img, fmt, manifest))
    return key                                         # job result = the blob key

def _region_or_404(rid):
    if rid not in REGIONS:
        raise HTTPException(404, f"Unknown region {rid!r}")
    return REGIONS[rid]

def _load_all(payloads, region):
    """Parse every uploaded file into tracks for one region; skip unparseable ones
    rather than 500 the batch (matches the per-file tolerance the UI relies on)."""
    out = []
    for data, fn in payloads:
        try:
            out += load_tracks(data, region.geo, filename=fn)   # GPX / KML / KMZ
        except Exception:
            continue
    return out

def _count_in_bounds(tracks, region):
    b = region.cfg["bounds"]
    n = 0
    for t in tracks:
        c = t.coords
        n += int(((c[:, 0] >= b[0]) & (c[:, 0] <= b[2]) &
                  (c[:, 1] >= b[1]) & (c[:, 1] <= b[3])).sum())
    return n

def _best_region(payloads):
    """The region holding the most track points (None if the tracks land nowhere)."""
    best, best_tracks, best_n = None, [], 0
    for r in REGIONS.values():
        tracks = _load_all(payloads, r)
        n = _count_in_bounds(tracks, r)
        if n > best_n:
            best, best_tracks, best_n = r, tracks, n
    return best, best_tracks


def _resolve_region(payloads, session_id, region_id):
    """Decide which region an upload belongs to and return (region, parsed_tracks).
    Order: an existing session is already bound; else an explicit region_id (with
    cross-region auto-recovery if the tracks don't fall in it); else the sole region;
    else auto-detect the region holding the most track points. EVERY branch enforces
    the in-bounds check -- the session and single-region paths used to skip it, so
    out-of-region tracks accumulated silently instead of a clean 422."""
    if session_id and session.has(session_id):
        region = _region_or_404(session.get(session_id)["region_id"])
        tracks = _load_all(payloads, region)
        if tracks and _count_in_bounds(tracks, region) == 0:
            raise HTTPException(
                422, f"Tracks don't fall within this session's region ({region.name})")
        return region, tracks
    if region_id:
        region = _region_or_404(region_id)
        tracks = _load_all(payloads, region)
        # Auto-recovery: the operator pre-picked a region, but if the tracks land
        # nowhere inside it and another built region actually holds them, switch --
        # a forgiving "you dropped the wrong region's tracks" fix (v1.2).
        if _count_in_bounds(tracks, region) == 0:
            alt, alt_tracks = _best_region(payloads)
            if alt is not None:
                return alt, alt_tracks
            # tracks land in NO built region -> clean 422 (same as auto-detect),
            # rather than rendering a garbage poster for out-of-bounds tracks.
            raise HTTPException(422, "Tracks don't fall within any available region")
        return region, tracks
    if len(REGIONS) == 1:
        region = next(iter(REGIONS.values()))
        tracks = _load_all(payloads, region)
        if tracks and _count_in_bounds(tracks, region) == 0:
            raise HTTPException(422, "Tracks don't fall within any available region")
        return region, tracks
    best, best_tracks = _best_region(payloads)
    if best is None:
        raise HTTPException(422, "Tracks don't fall within any available region")
    return best, best_tracks

@app.get("/readyz")
async def readyz():
    """Readiness probe: every discovered region must have a present DEM whose bounds
    and CRS match its region.json. 503 (with a per-region report) if any region can't
    render -- so a deploy/health check catches a missing or bounds-drifted DEM up front
    instead of a client hitting a 500 or a fabricated-terrain poster (V1-1/V1-2)."""
    report = [r.readiness() for r in REGIONS.values()]
    ok = bool(report) and all(e["ready"] for e in report)
    return JSONResponse({"ready": ok, "regions": report},
                        status_code=200 if ok else 503)

@app.get("/api/regions")
async def list_regions():
    """The region-picker gallery: every built region, lightweight metadata only."""
    return [r.meta() for r in REGIONS.values()]

# Track-upload caps (red-team): photos and KMZ contents were capped in the V1-6 pass
# but raw GPX/KML uploads were not -- one huge file ballooned RSS before any parsing.
TRACK_FILE_MAX_BYTES = 64 * 1024 * 1024
TRACK_BATCH_MAX_BYTES = 256 * 1024 * 1024

# nearest-hotspot radius when carrying annotations across a recompute; matches
# density.hotspots' min_spacing_m, so "nearest" is unambiguous within one spacing.
ANNOTATION_CARRY_M = 6000.0

def _carry_annotations(old_spots, new_spots):
    """Recomputing hotspots must never destroy operator work: transfer each annotated
    old hotspot's label/icon/photo onto the nearest recomputed hotspot (within one
    hotspot spacing); if none is near or the near one is already annotated, keep the
    old annotated spot itself. Before this, adding one more day's GPX to a session
    silently wiped every label, icon, and pinned photo (red-team, high)."""
    keys = ("label", "icon", "photo")
    out = [dict(s) for s in new_spots]
    for old in old_spots:
        if not any(old.get(k) for k in keys):
            continue
        best, best_d = None, None
        for s in out:
            d = ((s["x"] - old["x"]) ** 2 + (s["y"] - old["y"]) ** 2) ** 0.5
            if best is None or d < best_d:
                best, best_d = s, d
        if (best is not None and best_d <= ANNOTATION_CARRY_M
                and not any(best.get(k) for k in keys)):
            for k in keys:
                if old.get(k):
                    best[k] = old[k]
        else:
            out.append(dict(old))          # keep the annotated spot verbatim
    return out

@app.post("/api/upload")
async def upload(files: List[UploadFile] = File(...),
                 session_id: Optional[str] = Form(None),
                 region_id: Optional[str] = Form(None)):
    _sweep_uploads()                        # opportunistic eviction of stale photo dirs
    payloads = []
    total = 0
    for f in files:
        data = await f.read()
        total += len(data)
        if len(data) > TRACK_FILE_MAX_BYTES or total > TRACK_BATCH_MAX_BYTES:
            raise HTTPException(422, "Track upload exceeds the size limit")
        payloads.append((data, f.filename))
    region, new = _resolve_region(payloads, session_id, region_id)
    # recovery = the operator's explicit region was overridden because the tracks
    # actually belong to a different built region (not a plain auto-detect).
    recovered = bool(region_id and region.id != region_id
                     and not (session_id and session.has(session_id)))
    # source-file hashes for the self-describing manifest (accumulate with the tracks).
    new_sources = [provenance.source_entry(data, fn) for data, fn in payloads]
    old_spots, old_sources = [], []
    if session_id and session.has(session_id):
        st = session.get(session_id)
        tracks = st["tracks"] + new                                    # accumulate
        old_spots = st["hotspots"]
        old_sources = st.get("sources", [])
        sid = session_id
    else:
        tracks, sid = new, None
    if not tracks:
        raise HTTPException(400, "No usable tracks in file(s)")
    spots = _carry_annotations(old_spots,
                               hotspots(tracks, region_bounds=region.cfg["bounds"]))
    sources = old_sources + new_sources
    if sid is None:
        sid = session.create({"tracks": tracks, "hotspots": spots,
                              "region_id": region.id, "sources": sources})
    else:
        # invalidate any stamped spec: the track set changed, so /api/final must
        # not render a stale proof (it re-enforces "approve a proof first").
        session.update(sid, tracks=tracks, hotspots=spots, spec=None, sources=sources)
    # project to overview pixels for the aim canvas; carry any marker metadata so
    # the editor can show current label/icon/photo state after a reload.
    tpx = [[crs_to_overview_px(region.geo, x, y) for x, y in t.coords] for t in tracks]
    hpx = [{"px": crs_to_overview_px(region.geo, s["x"], s["y"]), "weight": s["weight"],
            "label": s.get("label", ""), "icon": s.get("icon", ""),
            "photo": bool(s.get("photo"))} for s in spots]
    # a floor-safe default crop for the Frame step (default print size 18x24); the
    # client re-fits it in place when the operator changes the print size.
    start = starter_crop(region.geo, tpx, 18, 24,
                         native_resolution_m=region.cfg["native_resolution_m"])
    log.info("event=upload session=%s region=%s tracks=%d hotspots=%d recovered=%s",
             sid, region.id, len(tracks), len(spots), recovered)
    return {"session": sid, "region": region.id, "name": region.name,
            "overview": f"/regions/{region.id}/overview.png",
            "overview_size": region.cfg["overview_size"], "tracks": tpx,
            "hotspots": hpx, "starter_crop": list(start), "recovered": recovered}

VALID_ICONS = {"", "dot", "peak", "camp", "water", "flag", "camera", "star"}
# env-overridable so the test harness never writes into the operator's live dir
UPLOADS_DIR = os.environ.get("TRAILPRINT_UPLOADS", "uploads")

def _sweep_uploads(ttl_seconds=TTL_SECONDS, root=UPLOADS_DIR):
    """Evict per-session photo dirs whose last write is older than the TTL (V1-8).
    Never touch a dir whose session still exists -- a stamped proof may reference the
    photos, and deleting them under a live session silently dropped photos from a
    final rendered the next day (red-team). Dir name == session id."""
    if not ttl_seconds or not os.path.isdir(root):
        return
    cutoff = time.time() - ttl_seconds
    removed = 0
    for name in os.listdir(root):
        d = os.path.join(root, name)
        try:
            if os.path.isdir(d) and os.path.getmtime(d) < cutoff and not session.has(name):
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except OSError:
            pass
    if removed:
        log.info("event=uploads.sweep removed=%d ttl_s=%s", removed, ttl_seconds)

# Photo upload guards (red-team V1-6): a small file can declare enormous dimensions
# (decompression bomb) or just be huge. Cap the raw bytes and the decoded pixel count.
PHOTO_MAX_BYTES = 20 * 1024 * 1024
PHOTO_MAX_PIXELS = 64_000_000
# Process-wide PIL backstop: sits above the render output ceiling (spec.MAX_OUTPUT_PIXELS
# = 120 MP), so it never trips a legitimate render (built via Image.new/fromarray, not
# decoded from a file) but still bombs out an absurdly large decoded upload.
Image.MAX_IMAGE_PIXELS = 200_000_000

def _require_session(session_id):
    """Session or 404, in one store round-trip (was has()+get(), and half the
    endpoints re-implemented it inline with try/except -- one idiom now)."""
    try:
        return session.get(session_id)
    except KeyError:
        raise HTTPException(404, "Unknown or expired session")

def _require_stamped(session_id):
    """The shared gate for both final endpoints: session -> 404, no stamped spec ->
    400 (approve a proof first), the region it renders against, and the source hashes
    (for the self-describing manifest)."""
    st = _require_session(session_id)
    spec = st.get("spec")
    if spec is None:
        raise HTTPException(400, "Approve a proof first")
    return spec, _region_or_404(st["region_id"]), st.get("sources", [])

def _final_manifest(spec, sources, embed_spec):
    """Build the provenance manifest for a final, or None when the client opted out of
    embedding (a share copy: the manifest carries the exact track coordinates)."""
    return provenance.build_manifest(spec, sources) if embed_spec else None

@app.post("/api/markers")
async def set_markers(session_id: str = Form(...), markers: str = Form(...)):
    """Set per-hotspot label/icon. `markers` is a JSON list of {i, label, icon};
    editing markers invalidates any stamped spec so the final reflects the edits."""
    st = _require_session(session_id)
    try:
        edits = json.loads(markers)
    except Exception:
        raise HTTPException(422, "markers must be JSON")
    if not isinstance(edits, list):
        raise HTTPException(422, "markers must be a JSON list")
    spots = st["hotspots"]
    for e in edits:
        if not isinstance(e, dict):       # a bare string/number entry must not 500
            continue
        i = e.get("i")
        if not isinstance(i, int) or not (0 <= i < len(spots)):
            continue
        if "label" in e:
            spots[i]["label"] = str(e["label"])[:60]
        if "icon" in e:
            icon = str(e["icon"])
            spots[i]["icon"] = icon if icon in VALID_ICONS else ""
    session.update(session_id, hotspots=spots, spec=None)   # re-proof to apply
    return {"ok": True}

@app.post("/api/photo")
async def set_photo(session_id: str = Form(...), i: int = Form(...),
                    file: UploadFile = File(...)):
    """Attach a photo to hotspot i. Stored under uploads/<session>/ and referenced
    by path on the spec; the file itself never rides the spec (same as the DEM)."""
    st = _require_session(session_id)
    spots = st["hotspots"]
    if not (0 <= i < len(spots)):
        raise HTTPException(422, "marker index out of range")
    data = await file.read()
    if len(data) > PHOTO_MAX_BYTES:
        raise HTTPException(422, "photo exceeds the size limit")
    try:
        im = Image.open(io.BytesIO(data))
        w, h = im.size                           # header read; no full decode yet
        if w * h > PHOTO_MAX_PIXELS:
            raise HTTPException(422, "photo dimensions are too large")
        im.verify()                              # reject corrupt/non-image bytes
    except HTTPException:
        raise                                    # keep the specific 422 above
    except Exception:
        raise HTTPException(422, "not a readable image")
    dst_dir = os.path.join(UPLOADS_DIR, session_id)
    os.makedirs(dst_dir, exist_ok=True)
    path = os.path.join(dst_dir, f"{i}_{os.path.basename(file.filename or 'photo')}")
    with open(path, "wb") as f:
        f.write(data)
    spots[i]["photo"] = path
    session.update(session_id, hotspots=spots, spec=None)   # re-proof to apply
    return {"ok": True}

@app.post("/api/markers/move")
async def move_marker(session_id: str = Form(...), i: int = Form(...),
                      px: float = Form(...), py: float = Form(...)):
    """Persist a hand-dragged hotspot. Convert overview px -> CRS, clamp to region
    bounds (never reject: 'snap the dot'), write x/y, invalidate the stamped spec so
    the next proof reflects the move. Returns the clamped position back in overview px
    so the client can snap the dot to where it actually landed."""
    st = _require_session(session_id)
    spots = st["hotspots"]
    if not (0 <= i < len(spots)):
        raise HTTPException(422, "marker index out of range")
    import math
    if not (math.isfinite(px) and math.isfinite(py)):
        # pydantic parses "nan"/"inf" floats; min/max would propagate NaN into the
        # stored x/y and poison the session permanently (red-team) -- reject instead.
        raise HTTPException(422, "marker position must be finite")
    region = _region_or_404(st["region_id"])                 # geo lives on the region
    x, y = overview_px_to_crs(region.geo, px, py)
    min_x, min_y, max_x, max_y = region.cfg["bounds"]
    x = min(max(x, min_x), max_x)                             # clamp, don't reject
    y = min(max(y, min_y), max_y)
    spots[i]["x"], spots[i]["y"] = x, y
    session.update(session_id, hotspots=spots, spec=None)     # re-proof to apply
    cpx, cpy = crs_to_overview_px(region.geo, x, y)           # snap-back position
    return {"ok": True, "px": cpx, "py": cpy}

def _parse_hex_rgb(s: str):
    """'#rrggbb' -> (r, g, b), or a clean 422 -- the track-color swatch value."""
    s = (s or "").strip().lstrip("#")
    if len(s) != 6:
        raise HTTPException(422, "track_color must be #rrggbb")
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise HTTPException(422, "track_color must be #rrggbb")

def _build_spec(sid, crop_px, print_w, print_h, title="", contours=False, compass=True,
                style=None, biome=False):
    st = _require_session(sid)
    region = _region_or_404(st["region_id"])
    crop = crop_px_to_crs_window(region.geo, *crop_px)
    # A finished poster carries a title block; default to the region's name so the
    # deliverable never ships bare (the old bare-caption title was unreachable: the
    # API had no title field). Pass title="-" to render a clean, block-free map.
    title = (title or "").strip() or region.name
    if title == "-":
        title = ""
    spec = CompositionSpec(
        region_id=region.id, crs=region.cfg["crs"], crop=crop,
        print_w_in=print_w, print_h_in=print_h,
        native_resolution_m=region.cfg["native_resolution_m"],
        tracks=[t.coords for t in st["tracks"]],
        track_days=[t.day for t in st["tracks"]],   # journey grouping (worn/termini)
        hotspots=st["hotspots"], seed=7, title_text=title,
        contours=contours, compass=compass, biome=biome, **(style or {}))
    spec.validate(FINAL_DPI)   # gate on the resolution the PRINT uses, not the proof's
    # NB: not stamped here -- the caller stamps only after a clean proof render, so a
    # proof that 422s (e.g. off-DEM) leaves no stamped spec for the async final to enqueue.
    return spec, region

@app.post("/api/proof")
async def proof(session_id: str = Form(...),
                x0: float = Form(...), y0: float = Form(...),
                x1: float = Form(...), y1: float = Form(...),
                print_w: float = Form(18.0), print_h: float = Form(24.0),
                title: str = Form(""),
                contours: bool = Form(False), compass: bool = Form(True),
                biome: bool = Form(False),
                track_width_pt: float = Form(2.6), track_halo: float = Form(0.7),
                track_color: str = Form(""), marker_size_in: float = Form(0.24),
                marker_ring: float = Form(0.09), photo_style: str = Form("mat"),
                furniture_scale: float = Form(1.0), terrain_depth: float = Form(1.0),
                shadow_strength: float = Form(0.5)):
    # the Style panel's knobs: all picture decisions, so they ride the spec and the
    # final renders exactly the styled proof. Out-of-range values 422 via validate().
    style = {"track_width_pt": track_width_pt, "track_halo": track_halo,
             "marker_diameter_in": marker_size_in, "marker_ring": marker_ring,
             "photo_frame_style": photo_style, "furniture_scale": furniture_scale,
             "terrain_depth": terrain_depth, "shadow_strength": shadow_strength}
    if track_color.strip():
        style["track_rgb"] = _parse_hex_rgb(track_color)
    try:
        spec, region = _build_spec(session_id, (x0, y0, x1, y1), print_w, print_h,
                                   title, contours, compass, style, biome)
    except SpecError as e:
        raise HTTPException(422, str(e))
    t0 = time.time()
    try:
        img = render.rasterize(spec, dpi=PROOF_DPI, region_dir=region.dir,
                               watermark=True, cfg=region.cfg)
    except SpecError as e:
        log.info("event=proof.reject session=%s reason=%s", session_id, e)
        raise HTTPException(422, str(e))
    # stamp only now (invariant 1): a clean proof means the final renders from this same
    # spec. The off-DEM verdict is DPI-independent, so a stamped spec always renders.
    session.update(session_id, spec=spec)
    log.info("event=proof session=%s region=%s dpi=%d ms=%d",
             session_id, region.id, PROOF_DPI, int((time.time() - t0) * 1000))
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")

@app.post("/api/final")
async def final(session_id: str = Form(...), format: str = Form("png"),
                embed_spec: bool = Form(True)):
    fmt = _require_format(format)
    spec, region, sources = _require_stamped(session_id)
    t0 = time.time()
    try:
        img = render.rasterize(spec, dpi=FINAL_DPI, region_dir=region.dir,
                               watermark=False, cfg=region.cfg)
    except SpecError as e:
        log.info("event=final.reject session=%s reason=%s", session_id, e)
        raise HTTPException(422, str(e))
    # Route the final through the blob seam (V1-8): stop littering region.dir with
    # final_*.png. Same key + encoding as the async path, so both serve identically.
    key = f"{session_id}/final.{fmt}"
    BLOBS.put(key, _encode_final(img, fmt, _final_manifest(spec, sources, embed_spec)))
    log.info("event=final session=%s region=%s dpi=%d fmt=%s embed=%s ms=%d",
             session_id, region.id, FINAL_DPI, fmt, embed_spec, int((time.time() - t0) * 1000))
    return FileResponse(BLOBS.path(key), media_type=FINAL_FORMATS[fmt][1],
                        filename=f"trailprint.{fmt}")

@app.post("/api/final/submit")
async def final_submit(session_id: str = Form(...), format: str = Form("png"),
                       embed_spec: bool = Form(True)):
    """Async final: enqueue the render at the compose->rasterize boundary and return
    a job id, so the request thread doesn't block on a 300 dpi paint. Same gate as
    the sync path (a proof must be stamped first)."""
    fmt = _require_format(format)
    spec, region, sources = _require_stamped(session_id)
    jid = QUEUE.submit(_render_to_blob, spec, region.dir, f"{session_id}/final.{fmt}", fmt,
                       _final_manifest(spec, sources, embed_spec))
    return {"job": jid}

@app.get("/api/jobs/{jid}")
async def job_status(jid: str):
    try:
        s = QUEUE.status(jid)
    except KeyError:
        raise HTTPException(404, "Unknown job")
    out = {"state": s["state"], "error": s["error"]}
    if s["state"] == "done":
        out["result"] = f"/api/jobs/{jid}/result"
    return out

@app.get("/api/jobs/{jid}/result")
async def job_result(jid: str):
    try:
        s = QUEUE.status(jid)
    except KeyError:
        raise HTTPException(404, "Unknown job")
    if s["state"] != "done":
        raise HTTPException(409, f"job is {s['state']}")
    key = s["result"]
    if not BLOBS.exists(key):
        raise HTTPException(404, "result expired")
    fmt = "pdf" if key.endswith(".pdf") else "png"     # blob key carries the format
    return FileResponse(BLOBS.path(key), media_type=FINAL_FORMATS[fmt][1],
                        filename=f"trailprint.{fmt}")

# ---- self-describing posters: reprint from the file alone (no session, no DB) ----
# A TrailPrint PNG carries its own spec (see provenance.py). These two endpoints read
# it back: /inspect returns the manifest, /reprint re-renders at print resolution.
REPRINT_MAX_BYTES = 96 * 1024 * 1024   # a 300-dpi PNG is tens of MB; cap the upload

async def _read_capped(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > REPRINT_MAX_BYTES:
        raise HTTPException(422, "File exceeds the size limit")
    return data

def _manifest_or_422(data: bytes) -> dict:
    m = provenance.extract(data)
    if m is None:
        raise HTTPException(422, "This file carries no TrailPrint manifest — it can't be reprinted. "
                                 "Only PNG finals exported with reprint data embedded are self-describing.")
    return m

@app.post("/api/reprint/inspect")
async def reprint_inspect(file: UploadFile = File(...)):
    """Read a poster's provenance without rendering: which region, the source-file
    hashes, and a spec summary. Pure read of the embedded manifest -- never decodes the
    image, so it's cheap and safe on any uploaded PNG."""
    manifest = _manifest_or_422(await _read_capped(file))
    spec_d = manifest.get("spec", {})
    region_id = manifest.get("region_id") or spec_d.get("region_id")
    return {
        "manifest_version": manifest.get("manifest_version"),
        "engine": manifest.get("engine"),
        "region_id": region_id,
        "region_available": region_id in REGIONS,
        "sources": manifest.get("sources", []),
        "print_size_in": [spec_d.get("print_w_in"), spec_d.get("print_h_in")],
        "title": spec_d.get("title_text", ""),
        "tracks": len(spec_d.get("tracks", []) or []),
        "hotspots": len(spec_d.get("hotspots", []) or []),
    }

@app.post("/api/reprint")
async def reprint(file: UploadFile = File(...), format: str = Form("png"),
                  embed_spec: bool = Form(True)):
    """Re-render a TrailPrint PNG at print resolution from the file alone. Stateless:
    the spec rides the file, so no session or DB row is needed -- a printed poster is
    reproducible forever. The embedded spec is UNTRUSTED input; photo paths are
    sanitized to inside the uploads dir (provenance.sanitize_photos) and spec.validate
    re-enforces aspect / the 120 MP ceiling / the zoom cap before any pixels are made."""
    fmt = _require_format(format)
    manifest = _manifest_or_422(await _read_capped(file))
    try:
        spec = provenance.manifest_to_spec(manifest)
    except Exception:
        raise HTTPException(422, "This file's TrailPrint manifest is malformed.")
    region = REGIONS.get(spec.region_id)
    if region is None:
        raise HTTPException(422, f"Region {spec.region_id!r} isn't built on this server, "
                                 "so this poster can't be reprinted here.")
    provenance.sanitize_photos(spec, UPLOADS_DIR)   # drop any out-of-uploads photo path
    try:
        spec.validate(FINAL_DPI)                    # untrusted spec: re-gate the geometry
    except SpecError as e:
        raise HTTPException(422, str(e))
    t0 = time.time()
    try:
        img = render.rasterize(spec, dpi=FINAL_DPI, region_dir=region.dir,
                               watermark=False, cfg=region.cfg)
    except SpecError as e:
        raise HTTPException(422, str(e))
    except Exception:
        # untrusted input: any other render failure (a malformed hotspot, a degenerate
        # geometry the validator doesn't cover) is the FILE's fault, not a server bug --
        # a clean 422, never a 500. Logged so a genuine regression is still visible.
        log.exception("event=reprint.render_error region=%s", spec.region_id)
        raise HTTPException(422, "This poster's embedded recipe couldn't be rendered.")
    # the reprint is itself self-describing (re-embed), unless the client opts out.
    out = _encode_final(img, fmt, _final_manifest(spec, manifest.get("sources", []), embed_spec))
    log.info("event=reprint region=%s fmt=%s embed=%s ms=%d",
             spec.region_id, fmt, embed_spec, int((time.time() - t0) * 1000))
    return StreamingResponse(io.BytesIO(out), media_type=FINAL_FORMATS[fmt][1],
                             headers={"Content-Disposition": f'attachment; filename="trailprint.{fmt}"'})

app.mount("/regions", StaticFiles(directory=REGIONS_ROOT), name="regions")
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
