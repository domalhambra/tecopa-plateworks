# app/main.py
import io, json, os, shutil, time
import hashlib
import logging
from typing import List, Optional
from PIL import Image
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.geo import (crs_to_overview_px, crop_px_to_crs_window,
                     overview_px_to_crs, starter_crop)
from app.ingest import load_tracks, Track
from app.density import hotspots
from app.spec import CompositionSpec, SpecError, FINAL_DPI, EDITION_MAX
from app import session, render, regions, blobs, jobs, logconfig, provenance, wallpaper, timelapse

logconfig.setup_logging()
log = logging.getLogger("trailprint.api")

# The registry replaces the old single hardcoded region: every regions/<id> built
# by region_prep.py is now selectable. Discovered once at import. The root is
# env-overridable (TRAILPRINT_REGIONS) so a deploy or the test harness can point
# the app at a different region tree without editing code.
REGIONS_ROOT = os.environ.get("TRAILPRINT_REGIONS", "regions")
REGIONS = regions.discover(REGIONS_ROOT)

# PROOF_DPI / FINAL_DPI describe the PRINT path (FINAL_DPI lives on app.spec -- one
# source of truth). A wallpaper's final dpi is its screen's ppi (spec.final_dpi());
# its proof keeps the same preview ratio: final_dpi * PROOF_DPI / FINAL_DPI.
PROOF_DPI = 96    # cheap mid-fidelity preview

def _proof_dpi(spec):
    return spec.final_dpi() * PROOF_DPI / FINAL_DPI    # 96 for a print, ppi*0.32 for a wallpaper

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

# Time-lapse ceiling: total painted pixels across all frames (frames x w x h). A film
# is many frames, so it needs its own guard above the still-render 120 MP ceiling --
# a 40-frame 4K film is ~330 MP, a 120-frame one ~1 GP. Refuse past this before enqueue
# with an honest fix ("fewer frames or a smaller target"), never OOM the worker.
MAX_ANIMATION_PIXELS = 600_000_000
# a film is watched, not printed -> default to screen-fidelity frames; a print-dpi film
# is allowed up to the ceiling for whoever wants one.
TIMELAPSE_DEFAULT_DPI = PROOF_DPI

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

def _encode_final(img, fmt: str, manifest=None, dpi: float = FINAL_DPI) -> bytes:
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
        kw = {"dpi": (dpi, dpi)}   # a print shop (or a wallpaper's ppi) reads true size
        if SRGB_PROFILE:
            kw["icc_profile"] = SRGB_PROFILE
        if manifest is not None:
            # the provenance manifest, one compressed zTXt chunk -- the file becomes
            # stateless-reprintable (POST /api/reprint). Embedded at encode time so we
            # never re-encode the PNG (self-describing posters).
            kw["pnginfo"] = provenance.manifest_pnginfo(manifest)
        img.save(buf, pil_fmt, **kw)
    return buf.getvalue()

def _require_format(fmt: str, spec=None) -> str:
    fmt = (fmt or "png").lower()
    if fmt not in FINAL_FORMATS:
        raise HTTPException(422, f"format must be one of {sorted(FINAL_FORMATS)}")
    if spec is not None and spec.output_kind == "wallpaper" and fmt != "png":
        # a wallpaper is a screen deliverable: PDF is the print-shop path, and it
        # can't carry the reprint manifest anyway -- refuse honestly, never coerce.
        raise HTTPException(422, "wallpapers are PNG-only — PDF is a print deliverable")
    return fmt

def _render_to_blob(spec, region_dir, key, fmt="png", manifest=None):
    """The render worker: rasterize the stamped spec at ITS final resolution (print
    dpi, or the device's ppi for a wallpaper) and store the encoded output. Runs on a
    queue thread, so it touches only its arguments."""
    dpi = spec.final_dpi()
    img = render.rasterize(spec, dpi=dpi, region_dir=region_dir, watermark=False)
    BLOBS.put(key, _encode_final(img, fmt, manifest, dpi=dpi))
    return key                                         # job result = the blob key

def _render_timelapse_to_blob(spec, region_dir, key, dpi, pacing, sources, embed_spec,
                              lineage=None):
    """The time-lapse worker: paint the base once and stream the day-ordered journey
    prefixes into one APNG. The manifest (with the `animation` block) rides the file so
    it re-renders from itself. Runs on a queue thread, touching only its arguments."""
    # honor the pacing max_frames that the ceiling was CHECKED against (same spec, same
    # max_frames): render_frames' default plan is DEFAULT_MAX_FRAMES, so omitting the
    # plan here would render more frames than the ceiling validated -> a bypass/OOM.
    plan = timelapse.frame_plan(spec, pacing["max_frames"])
    frames = timelapse.render_frames(spec, dpi=dpi, region_dir=region_dir, plan=plan)
    manifest = None
    if embed_spec:
        anim = timelapse.animation_meta(dpi=dpi, **pacing)
        manifest = provenance.build_manifest(spec, sources, lineage, animation=anim)
    BLOBS.put(key, timelapse.encode_apng(
        frames, manifest=manifest, step_ms=pacing["step_ms"], hold_ms=pacing["hold_ms"],
        leader_ms=pacing["leader_ms"], icc_profile=SRGB_PROFILE))
    return key                                         # job result = the blob key

def _render_bundle_to_blob(items, region_dir, key, cfg, sources, embed_spec, lineage=None):
    """The wallpaper-bundle worker: rasterize each per-device spec at its own ppi and
    store one zip. PNGs are already compressed, so the zip only containers them.
    Region assets (cfg/hydro/labels) are loaded ONCE and shared across the loop --
    only the DEM window read legitimately differs per device. Manifests are built
    here, per item, so N near-identical track copies never sit pinned in the queue.
    A device whose re-fit crop trips a render-time guard (off-DEM: the refit is never
    proofed) is skipped and named in SKIPPED.txt -- one bad device must not void the
    zip. All devices failing = a real error."""
    import zipfile
    hydro = render._load_hydro(region_dir)
    labels = (render._load_labels(region_dir)
              if any(spec.labels for spec, _ in items) else None)
    buf = io.BytesIO()
    skipped = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for spec, arcname in items:
            dpi = spec.final_dpi()
            try:
                img = render.rasterize(spec, dpi=dpi, region_dir=region_dir,
                                       watermark=False, hydro=hydro, cfg=cfg,
                                       labels=labels)
            except SpecError as e:
                skipped.append(f"{arcname}: {e}")
                continue
            z.writestr(arcname,
                       _encode_final(img, "png",
                                     _final_manifest(spec, sources, embed_spec, lineage),
                                     dpi=dpi))
        if skipped:
            z.writestr("SKIPPED.txt",
                       "These devices could not be rendered for this region:\n"
                       + "\n".join(skipped) + "\n")
    if len(skipped) == len(items):
        raise RuntimeError("no requested device could be rendered: "
                           + "; ".join(skipped))
    BLOBS.put(key, buf.getvalue())
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
    # living-editions dedup: skip any file whose bytes already back this poster (its
    # sha256 is already a source). Re-dropping last year's GPX -- the natural yearly
    # ritual when continuing a poster -- must not double-count journeys (which would
    # thicken the worn-width pass) or bloat the source list. Also collapses a file
    # dropped twice in one batch. The first occurrence of a hash is always kept, so
    # this can only empty `payloads` when every file already backs an existing session.
    existing = session.get(session_id) if (session_id and session.has(session_id)) else None
    seen_sha = {s.get("sha256") for s in (existing.get("sources", []) if existing else [])}
    kept, skipped_dupes = [], []
    for data, fn in payloads:
        h = hashlib.sha256(data).hexdigest()
        if h in seen_sha:
            skipped_dupes.append(fn or "track.gpx")
            continue
        seen_sha.add(h)
        kept.append((data, fn))
    payloads = kept
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
        # invalidate any stamped spec ONLY when the track set actually changed: a
        # re-drop of files already on the poster (every file deduped -> `new` empty)
        # is a no-op that must not force a needless re-proof. A real addition re-gates
        # "approve a proof first" so /api/final can't render a stale subset.
        kw = dict(tracks=tracks, hotspots=spots, sources=sources)
        if new:
            kw["spec"] = None
        session.update(sid, **kw)
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
            "hotspots": hpx, "starter_crop": list(start), "recovered": recovered,
            "skipped_duplicates": skipped_dupes}

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
    400 (approve a proof first), the region it renders against, the source hashes
    (for the self-describing manifest), and the edition lineage (living editions)."""
    st = _require_session(session_id)
    spec = st.get("spec")
    if spec is None:
        raise HTTPException(400, "Approve a proof first")
    return (spec, _region_or_404(st["region_id"]),
            st.get("sources", []), st.get("lineage", []))

def _final_manifest(spec, sources, embed_spec, lineage=None):
    """Build the provenance manifest for a final, or None when the client opted out of
    embedding (a share copy: the manifest carries the exact track coordinates). The
    lineage (living editions) rides along; it is emitted only from the 2nd edition on."""
    return provenance.build_manifest(spec, sources, lineage) if embed_spec else None

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
                style=None, biome=False, labels=False, preset=None):
    st = _require_session(sid)
    region = _region_or_404(st["region_id"])
    crop = crop_px_to_crs_window(region.geo, *crop_px)
    # A finished poster carries a title block; default to the region's name so the
    # deliverable never ships bare (the old bare-caption title was unreachable: the
    # API had no title field). Pass title="-" to render a clean, block-free map.
    title = (title or "").strip() or region.name
    if title == "-":
        title = ""
    # wallpaper: the sheet IS the device's glass and the deliverable is a clean map
    # (preset.spec_fields is the single definition); the operator's frame (crop),
    # style knobs, and the labels/contours/biome toggles all still apply.
    kw = (preset.spec_fields() if preset is not None
          else dict(print_w_in=print_w, print_h_in=print_h,
                    title_text=title, compass=compass))
    spec = CompositionSpec(
        region_id=region.id, crs=region.cfg["crs"], crop=crop,
        native_resolution_m=region.cfg["native_resolution_m"],
        tracks=[t.coords for t in st["tracks"]],
        track_days=[t.day for t in st["tracks"]],   # journey grouping (worn/termini)
        hotspots=st["hotspots"], seed=7,
        edition=st.get("edition", 1),               # living editions: draws in the cartouche
        contours=contours, biome=biome, labels=labels, **kw, **(style or {}))
    spec.validate(spec.final_dpi())   # gate on the resolution the FINAL uses, not the proof's
    # NB: not stamped here -- the caller stamps only after a clean proof render, so a
    # proof that 422s (e.g. off-DEM) leaves no stamped spec for the async final to enqueue.
    return spec, region

def _preset_or_422(preset_id: str):
    p = wallpaper.PRESETS.get((preset_id or "").strip())
    if p is None:
        raise HTTPException(422, f"unknown wallpaper preset {preset_id!r}; "
                                 f"see GET /api/wallpapers/presets")
    return p

@app.post("/api/proof")
async def proof(session_id: str = Form(...),
                x0: float = Form(...), y0: float = Form(...),
                x1: float = Form(...), y1: float = Form(...),
                print_w: float = Form(18.0), print_h: float = Form(24.0),
                title: str = Form(""),
                contours: bool = Form(False), compass: bool = Form(True),
                biome: bool = Form(False), labels: bool = Form(False),
                track_width_pt: float = Form(2.6), track_halo: float = Form(0.7),
                track_color: str = Form(""), marker_size_in: float = Form(0.24),
                marker_ring: float = Form(0.09), photo_style: str = Form("mat"),
                furniture_scale: float = Form(1.0), terrain_depth: float = Form(1.0),
                shadow_strength: float = Form(0.5),
                output: str = Form("print"), wallpaper_preset: str = Form("")):
    # the Style panel's knobs: all picture decisions, so they ride the spec and the
    # final renders exactly the styled proof. Out-of-range values 422 via validate().
    style = {"track_width_pt": track_width_pt, "track_halo": track_halo,
             "marker_diameter_in": marker_size_in, "marker_ring": marker_ring,
             "photo_frame_style": photo_style, "furniture_scale": furniture_scale,
             "terrain_depth": terrain_depth, "shadow_strength": shadow_strength}
    if track_color.strip():
        style["track_rgb"] = _parse_hex_rgb(track_color)
    # an unknown output must 422, not silently build a print (same honest-422 pattern
    # as photo_style / track_color / the preset id itself)
    if output not in ("print", "wallpaper"):
        raise HTTPException(422, "output must be 'print' or 'wallpaper'")
    # wallpaper mode: the preset (not the print_w/print_h form fields) sets the sheet
    preset = _preset_or_422(wallpaper_preset) if output == "wallpaper" else None
    try:
        spec, region = _build_spec(session_id, (x0, y0, x1, y1), print_w, print_h,
                                   title, contours, compass, style, biome, labels,
                                   preset=preset)
    except SpecError as e:
        raise HTTPException(422, str(e))
    t0 = time.time()
    try:
        img = render.rasterize(spec, dpi=_proof_dpi(spec), region_dir=region.dir,
                               watermark=True, cfg=region.cfg)
    except SpecError as e:
        log.info("event=proof.reject session=%s reason=%s", session_id, e)
        raise HTTPException(422, str(e))
    # stamp only now (invariant 1): a clean proof means the final renders from this same
    # spec. The off-DEM verdict is DPI-independent, so a stamped spec always renders.
    session.update(session_id, spec=spec)
    log.info("event=proof session=%s region=%s kind=%s dpi=%.0f ms=%d",
             session_id, region.id, spec.output_kind, _proof_dpi(spec),
             int((time.time() - t0) * 1000))
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")

@app.post("/api/final")
async def final(session_id: str = Form(...), format: str = Form("png"),
                embed_spec: bool = Form(True)):
    fmt = _require_format(format)      # membership first: a bad format is a 422 even
                                       # when the session is gone (the old contract)
    spec, region, sources, lineage = _require_stamped(session_id)
    _require_format(fmt, spec)         # the wallpaper PNG-only policy needs the spec
    dpi = spec.final_dpi()
    t0 = time.time()
    try:
        img = render.rasterize(spec, dpi=dpi, region_dir=region.dir,
                               watermark=False, cfg=region.cfg)
    except SpecError as e:
        log.info("event=final.reject session=%s reason=%s", session_id, e)
        raise HTTPException(422, str(e))
    # Route the final through the blob seam (V1-8): stop littering region.dir with
    # final_*.png. Same key + encoding as the async path, so both serve identically.
    key = f"{session_id}/final.{fmt}"
    BLOBS.put(key, _encode_final(img, fmt,
                                 _final_manifest(spec, sources, embed_spec, lineage), dpi=dpi))
    log.info("event=final session=%s region=%s dpi=%.0f fmt=%s embed=%s ms=%d",
             session_id, region.id, dpi, fmt, embed_spec, int((time.time() - t0) * 1000))
    return FileResponse(BLOBS.path(key), media_type=FINAL_FORMATS[fmt][1],
                        filename=f"trailprint.{fmt}")

@app.post("/api/final/submit")
async def final_submit(session_id: str = Form(...), format: str = Form("png"),
                       embed_spec: bool = Form(True)):
    """Async final: enqueue the render at the compose->rasterize boundary and return
    a job id, so the request thread doesn't block on a full-resolution paint. Same
    gate as the sync path (a proof must be stamped first)."""
    fmt = _require_format(format)
    spec, region, sources, lineage = _require_stamped(session_id)
    _require_format(fmt, spec)
    jid = QUEUE.submit(_render_to_blob, spec, region.dir, f"{session_id}/final.{fmt}", fmt,
                       _final_manifest(spec, sources, embed_spec, lineage))
    return {"job": jid}


# ---- wallpapers: the device-preset table + the multi-device bundle ----

@app.get("/api/wallpapers/presets")
async def wallpaper_presets():
    """The device-preset table (single source of truth: app/wallpaper.py). The wizard
    builds its picker from this -- device sizes are never hardcoded client-side."""
    return [p.meta() for p in wallpaper.PRESETS.values()]

@app.post("/api/wallpapers/submit")
async def wallpapers_submit(session_id: str = Form(...), presets: str = Form(...),
                            embed_spec: bool = Form(True)):
    """The bundle: re-target the ACCEPTED composition at each requested device (crop
    re-fit per aspect, sheet re-derived from the glass) and enqueue ONE job that
    renders them all into a zip. Same gate as a final (a proof must be stamped).
    `presets` is a comma-separated list of preset ids. A device the region can't
    satisfy (zoom cap / off-DEM) is skipped and reported, never silently dropped;
    if NO device fits, that's an honest 422."""
    spec, region, sources, lineage = _require_stamped(session_id)
    # dedupe while keeping order: a repeated id would write two identical arcnames
    # into one zip (most unzip tools silently keep only one) and render twice.
    ids = list(dict.fromkeys(p.strip() for p in presets.split(",") if p.strip()))
    if not ids:
        raise HTTPException(422, "presets must name at least one wallpaper preset")
    items, skipped = [], []
    for pid in ids:
        p = _preset_or_422(pid)
        try:
            pspec = wallpaper.spec_for_preset(spec, p, tuple(region.cfg["bounds"]))
        except SpecError as e:
            skipped.append({"preset": pid, "reason": str(e)})
            continue
        # off-DEM probe NOW (cheap, DPI-independent): the re-fit crop was never
        # proofed, and a render-time OffDemError would only surface inside the zip's
        # SKIPPED.txt -- probing here keeps the response's `skipped` list (which the
        # UI shows) the complete truth. The worker's per-item catch stays as backstop.
        nan_frac = render._offdem_fraction(region.dir, region.cfg, pspec.crop)
        if nan_frac > render.MAX_OFFDEM_NAN_FRAC:
            skipped.append({"preset": pid, "reason":
                            f"the re-fit frame extends past the region's elevation "
                            f"data ({nan_frac * 100:.0f}% has no DEM coverage)"})
            continue
        items.append((pspec, f"trailprint_{region.id}_{p.id}_{p.px_w}x{p.px_h}.png"))
    if not items:
        raise HTTPException(422, "No requested device fits this region: "
                            + "; ".join(s["reason"] for s in skipped))
    jid = QUEUE.submit(_render_bundle_to_blob, items, region.dir,
                       f"{session_id}/wallpapers.zip", region.cfg, sources, embed_spec,
                       lineage)
    log.info("event=wallpapers.submit session=%s region=%s n=%d skipped=%d",
             session_id, region.id, len(items), len(skipped))
    return {"job": jid, "count": len(items), "skipped": skipped}

# ---- time-lapse: the poster as a film ----

def _timelapse_pacing_or_422(max_frames, step_ms, hold_ms, leader_ms):
    """Bounds-check the pacing knobs (honest 422, like every other control). Pacing is
    not a picture decision -- it rides the manifest's animation block, not the spec."""
    lo_f, hi_f = timelapse.FRAMES_BOUNDS
    lo_d, hi_d = timelapse.DURATION_MS_BOUNDS
    if not (lo_f <= int(max_frames) <= hi_f):
        raise HTTPException(422, f"max_frames must be between {lo_f} and {hi_f}")
    for name, v in (("step_ms", step_ms), ("hold_ms", hold_ms), ("leader_ms", leader_ms)):
        if not (lo_d <= int(v) <= hi_d):
            raise HTTPException(422, f"{name} must be between {lo_d} and {hi_d} ms")
    return {"max_frames": int(max_frames), "step_ms": int(step_ms),
            "hold_ms": int(hold_ms), "leader_ms": int(leader_ms)}

def _timelapse_target(spec, region, wallpaper_preset, dpi):
    """The (spec, dpi) to film: a wallpaper preset re-fits the accepted composition to
    that device (exact native pixels, at its ppi); a wallpaper accepted-spec keeps its
    own device ppi; a print sheet films at a bounded, screen-default dpi."""
    if (wallpaper_preset or "").strip():
        preset = _preset_or_422(wallpaper_preset)
        try:
            tspec = wallpaper.spec_for_preset(spec, preset, tuple(region.cfg["bounds"]))
        except SpecError as e:
            raise HTTPException(422, str(e))
        # the re-fit crop was never proofed: off-DEM probe now (as wallpapers_submit does)
        nan_frac = render._offdem_fraction(region.dir, region.cfg, tspec.crop)
        if nan_frac > render.MAX_OFFDEM_NAN_FRAC:
            raise HTTPException(422, f"the {preset.name} frame extends past the region's "
                                f"elevation data ({nan_frac * 100:.0f}% has no DEM coverage)")
        return tspec, tspec.final_dpi()
    if spec.output_kind == "wallpaper":
        return spec, spec.final_dpi()                    # a wallpaper film uses its ppi
    import math
    d = dpi if (dpi and math.isfinite(dpi) and dpi > 0) else TIMELAPSE_DEFAULT_DPI
    if not (0 < d <= FINAL_DPI):
        raise HTTPException(422, f"dpi must be between 1 and {FINAL_DPI}")
    return spec, float(d)

def _animation_from_manifest_or_422(anim, spec):
    """Pacing + dpi from an UNTRUSTED animation block (a reprint of an animated file):
    clamp each value to its bound, fall back to the spec's own dpi if the stored dpi is
    unusable. The frame ceiling is enforced separately. A legit film's values are all
    in-bounds, so they are reproduced verbatim -> the reprint is byte-identical."""
    import math
    def _int(v, d):
        try:
            return int(v)
        except (TypeError, ValueError):
            return d
    lo_f, hi_f = timelapse.FRAMES_BOUNDS
    lo_d, hi_d = timelapse.DURATION_MS_BOUNDS
    _clamp = lambda v, lo, hi, d: min(max(_int(v, d), lo), hi)
    pacing = {
        "max_frames": _clamp(anim.get("max_frames"), lo_f, hi_f, timelapse.DEFAULT_MAX_FRAMES),
        "step_ms": _clamp(anim.get("step_ms"), lo_d, hi_d, timelapse.DEFAULT_STEP_MS),
        "hold_ms": _clamp(anim.get("hold_ms"), lo_d, hi_d, timelapse.DEFAULT_HOLD_MS),
        "leader_ms": _clamp(anim.get("leader_ms"), lo_d, hi_d, timelapse.DEFAULT_LEADER_MS),
    }
    try:
        dpi = float(anim.get("dpi"))
    except (TypeError, ValueError):
        dpi = None
    # a legit film's dpi is a print dpi (<= FINAL_DPI) or a device ppi (<= 600, the
    # wallpaper screen-ppi ceiling); anything outside that is a crafted value -> fall
    # back to the spec's own resolution (consistent with the submit path's caps).
    if dpi is None or not math.isfinite(dpi) or not (0 < dpi <= 600):
        dpi = spec.final_dpi()
    return pacing, dpi

def _animation_ceiling_or_422(spec, dpi, max_frames):
    """Refuse a film past the total-pixel ceiling before any painting; return the frame
    count. Guards both submit and a reprint of an (untrusted) animated file."""
    plan = timelapse.frame_plan(spec, max_frames)
    w, h = spec.pixel_size(dpi)
    total = len(plan) * w * h
    if total > MAX_ANIMATION_PIXELS:
        raise HTTPException(422, f"this film is {total / 1e6:.0f} MP across {len(plan)} "
                            f"frames, over the {MAX_ANIMATION_PIXELS // 1_000_000} MP "
                            f"ceiling — choose fewer frames or a smaller target")
    return len(plan)

@app.post("/api/timelapse/submit")
async def timelapse_submit(session_id: str = Form(...),
                           max_frames: int = Form(timelapse.DEFAULT_MAX_FRAMES),
                           step_ms: int = Form(timelapse.DEFAULT_STEP_MS),
                           hold_ms: int = Form(timelapse.DEFAULT_HOLD_MS),
                           leader_ms: int = Form(timelapse.DEFAULT_LEADER_MS),
                           wallpaper_preset: str = Form(""),
                           dpi: float = Form(0.0),
                           embed_spec: bool = Form(True)):
    """Render an accepted composition as a time-lapse APNG: the day-ordered journeys
    accumulate over a static terrain base to the complete poster (the last frame IS the
    still final -- invariant 1). Same stamped-spec gate as a final. Enqueues ONE job ->
    the existing /api/jobs/{id} -> /result flow (.png already maps correctly). The target
    is the accepted sheet (bounded, screen-default dpi) or a wallpaper preset (exact
    device pixels)."""
    spec, region, sources, lineage = _require_stamped(session_id)
    pacing = _timelapse_pacing_or_422(max_frames, step_ms, hold_ms, leader_ms)
    tspec, target_dpi = _timelapse_target(spec, region, wallpaper_preset, dpi)
    frames = _animation_ceiling_or_422(tspec, target_dpi, pacing["max_frames"])
    jid = QUEUE.submit(_render_timelapse_to_blob, tspec, region.dir,
                       f"{session_id}/timelapse.png", target_dpi, pacing, sources,
                       embed_spec, lineage)
    log.info("event=timelapse.submit session=%s region=%s frames=%d dpi=%.0f",
             session_id, region.id, frames, target_dpi)
    return {"job": jid, "frames": frames}

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
    # the blob key carries the format: final.png / final.pdf / wallpapers.zip.
    # FINAL_FORMATS stays the single source of truth for the formats it owns.
    ext = key.rsplit(".", 1)[-1] if "." in key else "png"
    media = (FINAL_FORMATS[ext][1] if ext in FINAL_FORMATS
             else "application/zip" if ext == "zip" else "application/octet-stream")
    return FileResponse(BLOBS.path(key), media_type=media,
                        filename=f"trailprint.{ext}")

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
        # living editions: what edition this file is, and its ancestor chain.
        "edition": manifest.get("edition", spec_d.get("edition", 1)),
        "lineage": manifest.get("lineage", []),
        # time-lapse: the pacing block if this file is a film (None for a still).
        "animation": manifest.get("animation"),
    }

@app.post("/api/reprint")
async def reprint(file: UploadFile = File(...), format: str = Form("png"),
                  embed_spec: bool = Form(True)):
    """Re-render a TrailPrint PNG at print resolution from the file alone. Stateless:
    the spec rides the file, so no session or DB row is needed -- a printed poster is
    reproducible forever. The embedded spec is UNTRUSTED input; photo paths are
    sanitized to inside the uploads dir (provenance.sanitize_photos) and spec.validate
    re-enforces aspect / the 120 MP ceiling / the zoom cap before any pixels are made."""
    fmt = _require_format(format)      # cheap membership check BEFORE reading the file
    data = await _read_capped(file)
    manifest = _manifest_or_422(data)
    try:
        spec = provenance.manifest_to_spec(manifest)
    except Exception:
        raise HTTPException(422, "This file's TrailPrint manifest is malformed.")
    _require_format(fmt, spec)                      # a wallpaper reprints as PNG only
    region = REGIONS.get(spec.region_id)
    if region is None:
        raise HTTPException(422, f"Region {spec.region_id!r} isn't built on this server, "
                                 "so this poster can't be reprinted here.")
    provenance.sanitize_photos(spec, UPLOADS_DIR)   # drop any out-of-uploads photo path
    try:
        provenance.bound_geometry(spec)             # untrusted spec: refuse a geometry bomb
        spec.validate(spec.final_dpi())             # untrusted spec: re-gate the geometry
    except SpecError as e:
        raise HTTPException(422, str(e))
    # an animated file re-renders the FILM (the file promises "the file is the artwork",
    # so honor it for films too). A film render is slow -> through the queue, returning a
    # job like the other async paths, not a synchronous stream. Stills keep today's
    # synchronous contract below.
    anim = manifest.get("animation")
    if isinstance(anim, dict):
        if fmt != "png":
            raise HTTPException(422, "a time-lapse is PNG-only")
        pacing, tl_dpi = _animation_from_manifest_or_422(anim, spec)
        frames = _animation_ceiling_or_422(spec, tl_dpi, pacing["max_frames"])
        key = f"reprint/{hashlib.sha256(data).hexdigest()[:16]}/timelapse.png"
        jid = QUEUE.submit(_render_timelapse_to_blob, spec, region.dir, key, tl_dpi,
                           pacing, manifest.get("sources", []), embed_spec,
                           manifest.get("lineage", []))
        log.info("event=reprint.timelapse region=%s frames=%d dpi=%.0f",
                 spec.region_id, frames, tl_dpi)
        return JSONResponse({"job": jid, "frames": frames})
    t0 = time.time()
    try:
        img = render.rasterize(spec, dpi=spec.final_dpi(), region_dir=region.dir,
                               watermark=False, cfg=region.cfg)
    except SpecError as e:
        raise HTTPException(422, str(e))
    except Exception:
        # untrusted input: any other render failure (a malformed hotspot, a degenerate
        # geometry the validator doesn't cover) is the FILE's fault, not a server bug --
        # a clean 422, never a 500. Logged so a genuine regression is still visible.
        log.exception("event=reprint.render_error region=%s", spec.region_id)
        raise HTTPException(422, "This poster's embedded recipe couldn't be rendered.")
    # the reprint is itself self-describing (re-embed), unless the client opts out. A
    # reprint is a re-render, NOT a new edition: the spec's own edition and the
    # manifest's own lineage are re-embedded verbatim (never incremented here).
    out = _encode_final(img, fmt,
                        _final_manifest(spec, manifest.get("sources", []), embed_spec,
                                        manifest.get("lineage", [])),
                        dpi=spec.final_dpi())
    log.info("event=reprint region=%s fmt=%s embed=%s ms=%d",
             spec.region_id, fmt, embed_spec, int((time.time() - t0) * 1000))
    return StreamingResponse(io.BytesIO(out), media_type=FINAL_FORMATS[fmt][1],
                             headers={"Content-Disposition": f'attachment; filename="trailprint.{fmt}"'})


# ---- living editions: the poster is the save file (POST /api/continue) ----
# Resurrect a live session from a poster's embedded manifest, so last year's PNG + this
# year's GPX renders the next edition. This is /api/reprint's generative twin: reprint
# reproduces the same picture; continue re-opens the composition to edit and carry
# forward. The manifest is UNTRUSTED input, so it reuses reprint's whole posture --
# capped read, photo-path sanitization, geometry bound, and a full validate.

def _finite_num(v) -> bool:
    """True for a real, finite number (not a bool, not NaN/inf) -- the guard for an
    untrusted hotspot coordinate before it reaches coordinate math."""
    import math
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

def _crop_to_overview_px(geo, crop):
    """A CRS crop window -> an ordered overview-px rect (x0,y0,x1,y1), the same
    convention starter_crop returns (image y flips: max_y is the top edge)."""
    px0, py0 = crs_to_overview_px(geo, crop[0], crop[3])   # top-left  (min_x, max_y)
    px1, py1 = crs_to_overview_px(geo, crop[2], crop[1])   # bot-right (max_x, min_y)
    return [min(px0, px1), min(py0, py1), max(px0, px1), max(py0, py1)]

def _match_wallpaper_preset(spec):
    """The preset id whose native pixels + density match a wallpaper spec, or None (a
    custom device we can't offer as a preset). px = round(print_in * screen_ppi)."""
    if spec.output_kind != "wallpaper" or spec.screen_ppi <= 0:
        return None
    pw = round(spec.print_w_in * spec.screen_ppi)
    ph = round(spec.print_h_in * spec.screen_ppi)
    for p in wallpaper.PRESETS.values():
        if p.px_w == pw and p.px_h == ph and abs(p.ppi - spec.screen_ppi) < 1.0:
            return p.id
    return None

@app.post("/api/continue")
async def continue_poster(file: UploadFile = File(...)):
    """Open a TrailPrint PNG for its next edition. Reads the embedded spec, rebuilds a
    live session (tracks, hotspots, style, title, crop, sources), bumps the edition and
    extends the lineage chain, and returns the /api/upload response shape plus prefill
    hints so the wizard lands with everything restored. The client then adds this year's
    GPX (/api/upload), re-frames if needed, and renders -- one clean proof stamps the
    new edition (invariant 1 holds: still one spec per accepted proof)."""
    data = await _read_capped(file)
    manifest = _manifest_or_422(data)
    try:
        spec = provenance.manifest_to_spec(manifest)
    except Exception:
        raise HTTPException(422, "This file's TrailPrint manifest is malformed.")
    region = REGIONS.get(spec.region_id)
    if region is None:
        raise HTTPException(422, f"Region {spec.region_id!r} isn't built on this server, "
                                 "so this poster can't be continued here.")
    # untrusted-manifest hardening (mirrors /api/reprint): drop any photo path that
    # escapes the uploads dir, then drop any that no longer resolves to a real file
    # (the TTL usually evicts a prior session's photos within a day) so a stale path
    # can't fail a later final. Label + icon always survive.
    provenance.sanitize_photos(spec, UPLOADS_DIR)
    for hs in spec.hotspots:
        if isinstance(hs, dict) and hs.get("photo") and not os.path.isfile(hs["photo"]):
            hs.pop("photo", None)
    try:
        provenance.bound_geometry(spec)             # refuse a geometry-bomb manifest
        spec.validate(spec.final_dpi())             # re-gate the untrusted geometry
    except SpecError as e:
        raise HTTPException(422, str(e))

    # rebuild live Track objects from the spec (tracks ride the spec, exactly the
    # property reprint relies on). track_days is parallel to tracks; normalize its
    # length rather than trust a crafted mismatch. Track ids only need uniqueness --
    # density keys on day-or-index, not the id string.
    import numpy as np
    days = list(spec.track_days or [])
    days = (days + [None] * len(spec.tracks))[:len(spec.tracks)]
    tracks = [Track(track_id=f"edition-{i}", coords=np.asarray(c, dtype=float), day=d)
              for i, (c, d) in enumerate(zip(spec.tracks, days))]
    # mutable hotspot copies for the session; drop any crafted entry without finite
    # x/y so it can't 500 the projection here or a later proof/final render.
    spots = [dict(s) for s in spec.hotspots
             if isinstance(s, dict) and _finite_num(s.get("x")) and _finite_num(s.get("y"))]

    # edition + lineage from the UNTRUSTED manifest: parse defensively (a crafted file
    # can carry a non-int edition or a non-list lineage) -> clamp, drop garbage, never
    # 500. The top-level `edition` is the parent's number; the child is one past it,
    # capped at the ceiling (a millennium of yearly editions never reaches it).
    try:
        parent_edition = int(manifest.get("edition", 1))
    except (TypeError, ValueError):
        parent_edition = 1
    parent_edition = min(max(parent_edition, 1), EDITION_MAX)
    raw_lineage = manifest.get("lineage", [])
    lineage = [e for e in raw_lineage if isinstance(e, dict)] if isinstance(raw_lineage, list) else []
    lineage = (lineage + [{"sha256": hashlib.sha256(data).hexdigest(),
                           "edition": parent_edition}])[-provenance.LINEAGE_MAX:]
    edition = min(parent_edition + 1, EDITION_MAX)
    raw_sources = manifest.get("sources", [])
    sources = [s for s in raw_sources if isinstance(s, dict)] if isinstance(raw_sources, list) else []

    sid = session.create({"tracks": tracks, "hotspots": spots, "region_id": region.id,
                          "sources": sources, "edition": edition, "lineage": lineage})

    tpx = [[crs_to_overview_px(region.geo, x, y) for x, y in t.coords] for t in tracks]
    hpx = [{"px": crs_to_overview_px(region.geo, s["x"], s["y"]),
            "weight": s.get("weight", 1), "label": s.get("label", ""),
            "icon": s.get("icon", ""), "photo": bool(s.get("photo"))} for s in spots]
    r, g, b = (int(c) for c in spec.track_rgb)
    output = spec.output_kind
    matched = _match_wallpaper_preset(spec)
    if output == "wallpaper" and matched is None:
        output = "print"                            # custom device -> continue as a print
    prefill = {
        # a title-less poster carries title_text="" (the "-" choice at proof time). Send
        # it back as "-" so the edition-2 proof stays title-less: an empty title would
        # otherwise re-resolve to the region name in _build_spec and regrow a title block.
        "title": spec.title_text or "-", "print_w_in": spec.print_w_in,
        "print_h_in": spec.print_h_in, "output": output, "wallpaper_preset": matched,
        "contours": spec.contours, "compass": spec.compass, "biome": spec.biome,
        "labels": spec.labels, "edition": edition, "lineage": lineage,
        "style": {"width": spec.track_width_pt, "halo": spec.track_halo,
                  "color": f"#{r:02x}{g:02x}{b:02x}", "marker": spec.marker_diameter_in,
                  "ring": spec.marker_ring, "photoStyle": spec.photo_frame_style,
                  "furniture": spec.furniture_scale, "terrain": spec.terrain_depth,
                  "shadow": spec.shadow_strength},
    }
    log.info("event=continue session=%s region=%s edition=%d tracks=%d hotspots=%d",
             sid, region.id, edition, len(tracks), len(spots))
    return {"session": sid, "region": region.id, "name": region.name,
            "overview": f"/regions/{region.id}/overview.png",
            "overview_size": region.cfg["overview_size"], "tracks": tpx,
            "hotspots": hpx, "starter_crop": _crop_to_overview_px(region.geo, spec.crop),
            "recovered": False, "skipped_duplicates": [],
            "edition": edition, "files": [s.get("filename", "track.gpx") for s in sources],
            "prefill": prefill}

app.mount("/regions", StaticFiles(directory=REGIONS_ROOT), name="regions")
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
