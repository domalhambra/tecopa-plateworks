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
from app.ingest import load_tracks, load_waypoints, Track
from app.density import hotspots
from app.spec import (CompositionSpec, SpecError, FINAL_DPI, EDITION_MAX,
                      CREDIT_MAX_CHARS, year_span)
from app import session, render, regions, blobs, jobs, logconfig, provenance, wallpaper, timelapse, solar

logconfig.setup_logging()
log = logging.getLogger("tecopa.api")

# The registry replaces the old single hardcoded region: every regions/<id> built
# by region_prep.py is now selectable. Discovered once at import. The root is
# env-overridable (TECOPA_REGIONS) so a deploy or the test harness can point
# the app at a different region tree without editing code.
REGIONS_ROOT = os.environ.get("TECOPA_REGIONS", "regions")
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
TTL_SECONDS = float(os.environ.get("TECOPA_TTL_SECONDS", 86400))

# server foundation (v1.3): outputs go to a blob store, finals render off the
# request thread via a job queue. Both are local impls behind interfaces that a
# networked store / broker drops into later (see blobs.py, jobs.py).
BLOBS = blobs.LocalBlobs(os.environ.get("TECOPA_BLOBS", "blobs"), ttl_seconds=TTL_SECONDS)
# one render at a time by default: a 300-dpi final peaks at ~5 GB RSS, so unbounded
# concurrency could OOM the operator's machine on double-click (red-team).
QUEUE = jobs.ThreadJobQueue(
    ttl_seconds=TTL_SECONDS,
    max_concurrency=int(os.environ.get("TECOPA_RENDER_CONCURRENCY", 1)))

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

def _embed_photos(spec, dpi):
    """Canonicalize a spec's hotspot photos to embedded JPEG bytes at the render box for
    `dpi` (photo_box_in * dpi, matching render._draw_photos), returning a copy. Feeding
    the SAME embedded spec to the render and the manifest makes the deliverable and its
    reprint pixel-identical, and frees the reprint from the uploads dir -- the photo now
    lives inside the file ("the file is the whole record")."""
    box_px = max(24, round(spec.photo_box_in * dpi))
    return provenance.build_final_spec(spec, box_px)

def _render_to_blob(spec, region_dir, key, fmt="png", manifest=None):
    """The render worker: rasterize the stamped spec at ITS final resolution (print
    dpi, or the device's ppi for a wallpaper) and store the encoded output. Runs on a
    queue thread, so it touches only its arguments."""
    dpi = spec.final_dpi()
    img = render.rasterize(spec, dpi=dpi, region_dir=region_dir, watermark=False)
    BLOBS.put(key, _encode_final(img, fmt, manifest, dpi=dpi))
    return key                                         # job result = the blob key

def _render_timelapse_to_blob(spec, region_dir, key, dpi, pacing, sources, embed_spec,
                              lineage=None, region_pack=None, fmt="apng",
                              light_motion="none", track_times=None, anchor=None,
                              default_image=False):
    """The time-lapse worker: paint the base once and stream the day-ordered journey
    prefixes into one film. `fmt` picks the container: "apng" (archival -- the manifest
    with the `animation` block rides the file, so it re-renders from itself) or a share
    twin, "webp" (ICC, no manifest) / "mp4" (neither). The twins carry nothing by
    construction: their branches never touch build_manifest / manifest_pnginfo at all.

    light_motion (Journey Light, v1.9): "none" is the archival journey-reveal film above;
    "diurnal"/"seasonal"/"auto" render the moving-sun Journey Light film (share twins only,
    gated at submit), where the base is REPAINTED per frame as the sun travels with the
    hike. Runs on a queue thread, touching only its arguments."""
    # honor the pacing max_frames that the ceiling was CHECKED against (same spec, same
    # max_frames): render_frames' default plan is DEFAULT_MAX_FRAMES, so omitting the
    # plan here would render more frames than the ceiling validated -> a bypass/OOM.
    spec = _embed_photos(spec, dpi)              # photos ride the film, not the uploads dir
    if light_motion != "none":
        frames = timelapse.journey_light_frames(
            spec, track_times, anchor, dpi=dpi, region_dir=region_dir,
            motion=light_motion, n_frames=pacing["max_frames"])
    else:
        plan = timelapse.frame_plan(spec, pacing["max_frames"])
        frames = timelapse.render_frames(spec, dpi=dpi, region_dir=region_dir, plan=plan)
    pace = dict(step_ms=pacing["step_ms"], hold_ms=pacing["hold_ms"],
                leader_ms=pacing["leader_ms"])
    if fmt == "webp":
        BLOBS.put(key, timelapse.encode_webp(frames, icc_profile=SRGB_PROFILE, **pace))
        return key
    if fmt == "mp4":
        BLOBS.put(key, timelapse.encode_mp4(frames, **pace))
        return key
    manifest = None
    if embed_spec:
        # default_image rides the block so the file re-encodes ITSELF faithfully:
        # a reprint reads the flag back and takes the same encoder branch.
        anim = timelapse.animation_meta(dpi=dpi, default_image=default_image, **pacing)
        manifest = provenance.build_manifest(spec, sources, lineage, animation=anim,
                                             region_pack=region_pack)
    BLOBS.put(key, timelapse.encode_apng(
        frames, manifest=manifest, icc_profile=SRGB_PROFILE,
        default_image=default_image, **pace))
    return key                                         # job result = the blob key

def _render_mockups_to_blob(data, variants, sizes, video, caption, key):
    """The wall-art mockup worker: stage a final's own pixels as photographed objects
    (embossed Plate / matted Frame) and store one zip of the JPEGs (and MP4s). Stateless
    — the artwork rides the uploaded bytes, no session or region data — so it works on any
    old final from the Library. Deterministic; touches only its arguments (queue thread)."""
    from app import mockups                              # lazy: pulls the imaging core
    BLOBS.put(key, mockups.build_zip(data, variants, sizes, video=video, caption=caption))
    return key                                           # job result = the blob key

def _render_bundle_to_blob(items, region_dir, key, cfg, sources, embed_spec, lineage=None,
                           region_pack=None):
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
            spec = _embed_photos(spec, dpi)      # photos ride each device file, per its ppi
            try:
                img = render.rasterize(spec, dpi=dpi, region_dir=region_dir,
                                       watermark=False, hydro=hydro, cfg=cfg,
                                       labels=labels)
            except SpecError as e:
                skipped.append(f"{arcname}: {e}")
                continue
            z.writestr(arcname,
                       _encode_final(img, "png",
                                     _final_manifest(spec, sources, embed_spec, lineage,
                                                     region_pack),
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

def _load_all(payloads, region, stats=None):
    """Parse every uploaded file into tracks for one region; skip unparseable ones
    rather than 500 the batch (matches the per-file tolerance the UI relies on).
    `stats` (optional) accumulates ingest counters (dropped_points) -- per file, so a
    file that fails to parse mid-way contributes nothing (it isn't on the poster)."""
    out = []
    for data, fn in payloads:
        s = {} if stats is not None else None
        try:
            out += load_tracks(data, region.geo, filename=fn, stats=s)  # GPX/KML/KMZ
        except Exception:
            continue
        if stats is not None:
            for k, v in s.items():
                stats[k] = stats.get(k, 0) + v
    return out

def _count_in_bounds(tracks, region):
    b = region.cfg["bounds"]
    n = 0
    for t in tracks:
        c = t.coords
        n += int(((c[:, 0] >= b[0]) & (c[:, 0] <= b[2]) &
                  (c[:, 1] >= b[1]) & (c[:, 1] <= b[3])).sum())
    return n

def _journeys_outside_plate(tracks, region):
    """How many tracks have ANY vertex outside the plate's bounds rect -- those
    journeys render truncated at the plate edge, and the wizard says so instead of
    letting the poster silently disagree with "everywhere you've been". Same
    vectorized 4-way compare as _count_in_bounds, inverted per track."""
    b = region.cfg["bounds"]
    n = 0
    for t in tracks:
        c = t.coords
        n += int(((c[:, 0] < b[0]) | (c[:, 0] > b[2]) |
                  (c[:, 1] < b[1]) | (c[:, 1] > b[3])).any())
    return n

def _best_region(payloads, stats=None):
    """The region holding the most track points (None if the tracks land nowhere).
    Only the WINNER's parse feeds `stats` -- the losing detection parses are probes
    against the wrong projection and would inflate the counters with drops the
    session never sees."""
    best, best_tracks, best_n, best_stats = None, [], 0, None
    for r in REGIONS.values():
        s = {} if stats is not None else None
        tracks = _load_all(payloads, r, stats=s)
        n = _count_in_bounds(tracks, r)
        if n > best_n:
            best, best_tracks, best_n, best_stats = r, tracks, n, s
    if stats is not None and best_stats:
        for k, v in best_stats.items():
            stats[k] = stats.get(k, 0) + v
    return best, best_tracks


def _resolve_region(payloads, session_id, region_id, stats=None):
    """Decide which region an upload belongs to and return (region, parsed_tracks).
    Order: an existing session is already bound; else an explicit region_id (with
    cross-region auto-recovery if the tracks don't fall in it); else the sole region;
    else auto-detect the region holding the most track points. EVERY branch enforces
    the in-bounds check -- the session and single-region paths used to skip it, so
    out-of-region tracks accumulated silently instead of a clean 422. `stats` only
    ever receives the parse whose tracks are RETURNED (the one the session keeps)."""
    if session_id and session.has(session_id):
        region = _region_or_404(session.get(session_id)["region_id"])
        tracks = _load_all(payloads, region, stats=stats)
        if tracks and _count_in_bounds(tracks, region) == 0:
            raise HTTPException(
                422, f"Tracks don't fall within this session's region ({region.name})")
        return region, tracks
    if region_id:
        region = _region_or_404(region_id)
        # parse into a LOCAL stats dict: if auto-recovery switches regions below,
        # this parse's drops belong to the wrong projection and must not leak.
        own = {} if stats is not None else None
        tracks = _load_all(payloads, region, stats=own)
        # Auto-recovery: the operator pre-picked a region, but if the tracks land
        # nowhere inside it and another built region actually holds them, switch --
        # a forgiving "you dropped the wrong region's tracks" fix (v1.2).
        if _count_in_bounds(tracks, region) == 0:
            alt, alt_tracks = _best_region(payloads, stats=stats)
            if alt is not None:
                return alt, alt_tracks
            # tracks land in NO built region -> clean 422 (same as auto-detect),
            # rather than rendering a garbage poster for out-of-bounds tracks.
            raise HTTPException(422, "Tracks don't fall within any available region")
        if stats is not None:                        # kept this parse -> merge
            for k, v in own.items():
                stats[k] = stats.get(k, 0) + v
        return region, tracks
    if len(REGIONS) == 1:
        region = next(iter(REGIONS.values()))
        tracks = _load_all(payloads, region, stats=stats)
        if tracks and _count_in_bounds(tracks, region) == 0:
            raise HTTPException(422, "Tracks don't fall within any available region")
        return region, tracks
    best, best_tracks = _best_region(payloads, stats=stats)
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

def _track_key(t) -> str:
    """A content hash identifying one recording: its day plus its (N,2) float64
    coordinates. The ingest pipeline (parse -> reproject -> simplify) is deterministic,
    day is a normalized ISO date string (or None), and coords round-trip float64
    losslessly through the spec/manifest JSON -- so the SAME recording hashes identically
    whether it arrives in a fresh file or is rebuilt from a continued poster. The DAY is
    part of the key on purpose: re-walking the same trail on another day is a distinct
    journey that must still earn its worn-path weight, while a re-exported copy of one
    recording (same day, same track) dedups. Distinct recordings of a trail on the same
    day differ in coords anyway (GPS noise), so they are never wrongly merged."""
    import numpy as np
    a = np.ascontiguousarray(t.coords, dtype=np.float64)
    return hashlib.sha256(str(t.day or "").encode() + b"|" + a.tobytes()).hexdigest()

def _dedup_new_tracks(existing, parsed):
    """Drop any parsed track whose geometry already backs the poster (or repeats earlier
    in this same batch), keyed by _track_key. Returns (kept, skipped_count). The
    track-level twin of the file-level (sha256-of-bytes) dedup in upload(): a re-exported
    folder that overlaps last year's tracks is a DIFFERENT file -- file-dedup can't catch
    it -- but its already-present tracks must not double-count into the worn-width pass.
    First occurrence of a geometry always wins, so this only ever drops true repeats."""
    seen = {_track_key(t) for t in existing}
    kept, skipped = [], 0
    for t in parsed:
        k = _track_key(t)
        if k in seen:
            skipped += 1
            continue
        seen.add(k)
        kept.append(t)
    return kept, skipped

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
    # loud boundaries: count what ingest drops (non-finite reprojection) for THIS
    # request's kept files, so the wizard can say it instead of the void swallowing it.
    stats = {}
    region, parsed = _resolve_region(payloads, session_id, region_id, stats=stats)
    # recovery = the operator's explicit region was overridden because the tracks
    # actually belong to a different built region (not a plain auto-detect).
    recovered = bool(region_id and region.id != region_id
                     and not (session_id and session.has(session_id)))
    # source-file hashes for the self-describing manifest (accumulate with the tracks).
    new_sources = [provenance.source_entry(data, fn) for data, fn in payloads]
    old_spots, old_sources = [], []
    if session_id and session.has(session_id):
        st = session.get(session_id)
        # track-level dedup: a re-exported folder (new file bytes, so file-dedup missed
        # it) that overlaps tracks already on the poster must not re-add them.
        new, skipped_track_dupes = _dedup_new_tracks(st["tracks"], parsed)
        tracks = st["tracks"] + new                                    # accumulate
        old_spots = st["hotspots"]
        old_sources = st.get("sources", [])
        sid = session_id
    else:
        # a fresh session still dedups WITHIN the batch (the same track dropped twice,
        # or a folder that carries a duplicate).
        new, skipped_track_dupes = _dedup_new_tracks([], parsed)
        tracks, sid = new, None
    if not tracks:
        raise HTTPException(400, "No usable tracks in file(s)")
    spots = _carry_annotations(old_spots,
                               hotspots(tracks, region_bounds=region.cfg["bounds"]))
    # GPX <wpt> / KML placemark POIs (v1.9): explicit named pins, merged into the marker
    # layer beside the visit-density hotspots. A parse failure never fails the upload.
    wpts = []
    for data, fn in payloads:
        try:
            wpts.extend(load_waypoints(data, region.geo, fn))
        except Exception:
            pass
    spots = _merge_waypoints(spots, wpts)
    sources = old_sources + new_sources
    if sid is None:
        sid = session.create({"tracks": tracks, "hotspots": spots,
                              "region_id": region.id, "sources": sources})
    else:
        # invalidate any stamped spec ONLY when the track set actually changed: a
        # re-drop of files/tracks already on the poster (`new` empty after both dedup
        # passes) is a no-op that must not force a needless re-proof. A real addition
        # re-gates "approve a proof first" so /api/final can't render a stale subset.
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
            # per-track day index (journey grouping) -- additive; lets the client read
            # the year/day span for the social caption helper without a spec.
            "track_days": [t.day for t in tracks],
            "hotspots": hpx, "starter_crop": list(start), "recovered": recovered,
            "skipped_duplicates": skipped_dupes,
            "skipped_duplicate_tracks": skipped_track_dupes,
            # loud boundaries: this request's non-finite reprojection drops, and how
            # many of the SESSION's journeys (the poster shows all of them) extend
            # past the plate's bounds -- named and counted, never silent.
            "dropped_points": int(stats.get("dropped_points", 0)),
            "journeys_outside_plate": _journeys_outside_plate(tracks, region),
            # Journey Light availability (v1.9): the wizard enables the toggle + defaults
            # the time-of-day scrubber from this. None when no track carries a timestamp.
            "journey_light": _journey_light_meta(tracks),
            # the print resolution the FINAL renders at: served so the client's zoom-
            # floor math keys on the server's truth instead of a hardcoded 300
            # (red-team 2026-07-17 -- the one dpi the client used to assume).
            "final_dpi": FINAL_DPI}

WAYPOINT_DEDUP_M = 400.0

def _merge_waypoints(spots, waypoints):
    """Append explicit waypoints not already covered by a nearby (density or waypoint)
    hotspot, so a marked point and the auto visit-density peak on it don't double up."""
    out = list(spots)
    for w in waypoints:
        if all(((w["x"] - s["x"]) ** 2 + (w["y"] - s["y"]) ** 2) ** 0.5 >= WAYPOINT_DEDUP_M
               for s in out):
            out.append(w)
    return out

def _journey_light_meta(tracks):
    """The upload/continue response's journey_light block, or None when no track is
    timestamped (Journey Light then stays disabled in the wizard)."""
    anchor = solar.track_anchor(tracks)
    if anchor is None:
        return {"available": False}
    js = solar.journey_sun(anchor)
    return {"available": True, "date": anchor["days"][-1], "sun": js}

VALID_ICONS = {"", "dot", "peak", "camp", "water", "flag", "camera", "star"}
# env-overridable so the test harness never writes into the operator's live dir
UPLOADS_DIR = os.environ.get("TECOPA_UPLOADS", "uploads")

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

def _final_manifest(spec, sources, embed_spec, lineage=None, region_pack=None):
    """Build the provenance manifest for a final, or None when the client opted out of
    embedding (a share copy: the manifest carries the exact track coordinates). The
    lineage (living editions) rides along; it is emitted only from the 2nd edition on.
    The region_pack block (the plate's hash identity) rides the same way -- omitted
    when the region has no sources.json to name it from."""
    return (provenance.build_manifest(spec, sources, lineage, region_pack=region_pack)
            if embed_spec else None)

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

# The cartouche's data-credit line, mapped from the dataset strings region_prep
# records in sources.json. Substring match, so a wording tweak ("USGS 3DEP 10 m DEM"
# vs "3DEP 1/3 arc-second") still lands on the canonical short credit.
CREDIT_DATASETS = (("3DEP", "Terrain USGS 3DEP"),
                   ("NHD", "Water USGS NHD"),
                   ("NLCD", "Land cover NLCD 2021"),
                   ("GNIS", "Names USGS GNIS"))

def credit_line(region) -> str:
    """The attribution sentence for spec.credit_text, derived from the region's
    sources.json at proof time -- derived truth, not a client style knob. Known USGS
    datasets map to short credits; an UNRECOGNIZED dataset passes through verbatim,
    so a future non-public-domain plate automatically carries its *required* credit
    instead of relying on memory (courtesy today, load-bearing later). Joined with an
    ASCII " - " -- validate() gates credit_text to printable ASCII, and the gate and
    this builder decide the charset once. Clamped to that same gate by construction
    (drop non-ASCII, cap the length) so a plate's own metadata can never 422 a proof.
    No sources.json, or none that name datasets -> "" (no credit row painted)."""
    try:
        with open(os.path.join(region.dir, "sources.json")) as f:
            sources = json.load(f).get("sources", [])
    except Exception:
        return ""
    parts = []
    for s in sources if isinstance(sources, list) else []:
        ds = s.get("dataset") if isinstance(s, dict) else None
        if not (isinstance(ds, str) and ds.strip()):
            continue
        for token, credit in CREDIT_DATASETS:
            if token in ds:
                parts.append(credit)
                break
        else:
            parts.append(ds.strip())
    line = "".join(c for c in " - ".join(parts) if " " <= c <= "~")
    return line[:CREDIT_MAX_CHARS]


def download_name(spec, kind: str = "", fmt: str = "png") -> str:
    """A self-documenting filename for a deliverable, a pure function of the spec:
    tecopa_<region_id>[_edition-<n>][_<yearspan>]<kind>.<fmt>. The edition suffix
    appears from the second edition on (matching the cartouche); the year span comes
    from the spec's track_days (the same year_span the cartouche prints, en dash
    flattened to a filename-safe hyphen). `kind` is "" for prints, "_film" for
    time-lapses, "_wallpapers" for the bundle zip. Charset stays [a-z0-9._-] by
    construction: region ids are ^[a-z0-9_]+$ and years are digits. A reprint names
    the file from the REPRINTED spec (its edition, its years -- there is no clock)."""
    name = f"tecopa_{spec.region_id}"
    if getattr(spec, "edition", 1) >= 2:
        name += f"_edition-{spec.edition}"
    span = year_span(spec.track_days).replace("–", "-")
    if span:
        name += f"_{span}"
    return f"{name}{kind}.{fmt}"


def _parse_hex_rgb(s: str):
    """'#rrggbb' -> (r, g, b), or a clean 422 -- the track-color swatch value."""
    s = (s or "").strip().lstrip("#")
    if len(s) != 6:
        raise HTTPException(422, "track_color must be #rrggbb")
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        raise HTTPException(422, "track_color must be #rrggbb")

def _resolve_journey_sun(st, style, sun_hour, sun_azimuth, sun_altitude):
    """Journey Light (v1.9): resolve the poster's sun and stamp it into `style`. Explicit
    az+alt (the /api/continue restore path) win; otherwise the sun is derived from the
    session's timestamped tracks (summit light, or the UI scrubber's local hour). No
    timestamps -> an honest 422. The resolved angles ride the spec; the GPX times never do."""
    style["light_mode"] = "journey"
    if sun_azimuth is not None and sun_altitude is not None:
        style["sun_azimuth_deg"], style["sun_altitude_deg"] = sun_azimuth, sun_altitude
        return
    anchor = solar.track_anchor(st["tracks"])
    if anchor is None:
        raise HTTPException(422, "Journey light needs timestamped tracks "
                                 "(a GPX with <time>). Upload a recorded track, or "
                                 "switch the light back to Archival.")
    js = solar.journey_sun(anchor, sun_hour)
    style["sun_azimuth_deg"] = js["azimuth_deg"]
    style["sun_altitude_deg"] = js["altitude_deg"]

def _build_spec(sid, crop_px, print_w, print_h, title="", contours=False, compass=True,
                style=None, biome=False, labels=False, preset=None,
                light_mode="archival", sun_hour=None, sun_azimuth=None, sun_altitude=None):
    st = _require_session(sid)
    region = _region_or_404(st["region_id"])
    crop = crop_px_to_crs_window(region.geo, *crop_px)
    # Journey Light: resolve the sun from the session's tracks (or the explicit restore
    # values) into the style dict before the spec is built; archival leaves style alone.
    style = dict(style or {})
    if light_mode == "journey":
        _resolve_journey_sun(st, style, sun_hour, sun_azimuth, sun_altitude)
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
        credit_text=credit_line(region),            # data credit: derived, never a form field
        contours=contours, biome=biome, labels=labels, **kw, **(style or {}))
    spec.validate(spec.final_dpi())   # gate on the resolution the FINAL uses, not the proof's
    # NB: not stamped here -- the caller stamps only after a clean proof render, so a
    # proof that 422s (e.g. off-DEM) leaves no stamped spec for the async final to enqueue.
    return spec, region

def _preset_or_422(preset_id: str, custom_px_w: int = 0, custom_px_h: int = 0,
                   custom_ppi: float = 0.0):
    pid = (preset_id or "").strip()
    if pid == "custom":
        # the escape hatch (red-team 2026-07-17): a device the table doesn't carry.
        # Only the proof form carries the three custom fields; the bundle/film target
        # lists stay table-only (their arcnames/keys name table ids), so those call
        # sites reach this branch with zeros and get the honest sentence below.
        if not (custom_px_w and custom_px_h and custom_ppi):
            raise HTTPException(422, "a custom device needs custom_px_w, custom_px_h "
                                     "and custom_ppi (set them on the Frame step)")
        try:
            return wallpaper.custom_preset(custom_px_w, custom_px_h, custom_ppi)
        except ValueError as e:
            raise HTTPException(422, str(e))
    p = wallpaper.PRESETS.get(pid)
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
                shadow_strength: float = Form(0.5), oblique: float = Form(0.0),
                light_mode: str = Form("archival"), sun_hour: Optional[float] = Form(None),
                sun_azimuth_deg: Optional[float] = Form(None),
                sun_altitude_deg: Optional[float] = Form(None),
                golden_strength: float = Form(0.7), profile: bool = Form(False),
                profile_height_in: float = Form(0.9), profile_rev: int = Form(2),
                track_color_by: str = Form("none"),
                label_place: str = Form("smart"), track_weave: bool = Form(True),
                output: str = Form("print"), wallpaper_preset: str = Form(""),
                custom_px_w: int = Form(0), custom_px_h: int = Form(0),
                custom_ppi: float = Form(0.0), bleed: float = Form(0.0)):
    # the Style panel's knobs: all picture decisions, so they ride the spec and the
    # final renders exactly the styled proof. Out-of-range values 422 via validate().
    style = {"track_width_pt": track_width_pt, "track_halo": track_halo,
             "marker_diameter_in": marker_size_in, "marker_ring": marker_ring,
             "photo_frame_style": photo_style, "furniture_scale": furniture_scale,
             "terrain_depth": terrain_depth, "shadow_strength": shadow_strength,
             "oblique": oblique,
             # Journey Light picture decisions (the resolved sun is injected in _build_spec):
             "golden_strength": golden_strength, "profile": profile,
             "profile_height_in": profile_height_in, "profile_rev": profile_rev,
             "bleed_in": bleed, "track_color_by": track_color_by,
             # smart label placement + chronological weave (v1.10) + profile_rev (v1.12):
             # NEW posters default to the enhanced look (the Form defaults above), while the
             # spec/manifest still omit these at their pre-feature default so OLD posters
             # reprint byte-identically.
             "label_place": label_place, "track_weave": track_weave}
    if track_color.strip():
        style["track_rgb"] = _parse_hex_rgb(track_color)
    if light_mode not in ("archival", "journey"):
        raise HTTPException(422, "light_mode must be 'archival' or 'journey'")
    # an unknown output must 422, not silently build a print (same honest-422 pattern
    # as photo_style / track_color / the preset id itself)
    if output not in ("print", "wallpaper"):
        raise HTTPException(422, "output must be 'print' or 'wallpaper'")
    # wallpaper mode: the preset (not the print_w/print_h form fields) sets the sheet;
    # "custom" builds a one-off device from the three custom_* fields (the escape hatch)
    preset = (_preset_or_422(wallpaper_preset, custom_px_w, custom_px_h, custom_ppi)
              if output == "wallpaper" else None)
    try:
        spec, region = _build_spec(session_id, (x0, y0, x1, y1), print_w, print_h,
                                   title, contours, compass, style, biome, labels,
                                   preset=preset, light_mode=light_mode, sun_hour=sun_hour,
                                   sun_azimuth=sun_azimuth_deg, sun_altitude=sun_altitude_deg)
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
    # A proof is the picture you judge AT THE TRIM LINE: crop the bleed band off the
    # PREVIEW (never the stamped spec -- the FINAL carries the bleed) so the wizard's
    # crop/marker registration (proof px == spec.crop) keeps holding exactly, with no
    # client math. The proof stays a faithful scale of the final's trim box -- which
    # is what the lab's cut produces. (±1 px vs round(trim*dpi) from double rounding:
    # a fit-to-screen preview, fractional registration -- recorded in the plan.)
    if spec.bleed_in:
        b = round(spec.bleed_in * _proof_dpi(spec))
        w, h = img.size
        img = img.crop((b, b, w - b, h - b))
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
    spec = _embed_photos(spec, dpi)    # canonicalize photos -> the render + manifest share them
    t0 = time.time()
    try:
        img = render.rasterize(spec, dpi=dpi, region_dir=region.dir,
                               watermark=False, cfg=region.cfg)
    except SpecError as e:
        log.info("event=final.reject session=%s reason=%s", session_id, e)
        raise HTTPException(422, str(e))
    # Route the final through the blob seam (V1-8): stop littering region.dir with
    # final_*.png. Same key + encoding as the async path, so both serve identically.
    # The KEY carries the self-documenting name, so every serving path (this
    # FileResponse, /api/jobs/{jid}/result) says what the file is for free.
    key = f"{session_id}/{download_name(spec, fmt=fmt)}"
    # the file names its plate: hashed from the assets once per final, never cached.
    # spec.labels/biome ride along so the block covers exactly the assets these pixels read.
    rp = provenance.region_pack_block(region.dir, labels=spec.labels, biome=spec.biome)
    BLOBS.put(key, _encode_final(img, fmt,
                                 _final_manifest(spec, sources, embed_spec, lineage,
                                                 region_pack=rp), dpi=dpi))
    log.info("event=final session=%s region=%s dpi=%.0f fmt=%s embed=%s ms=%d",
             session_id, region.id, dpi, fmt, embed_spec, int((time.time() - t0) * 1000))
    return FileResponse(BLOBS.path(key), media_type=FINAL_FORMATS[fmt][1],
                        filename=download_name(spec, fmt=fmt))

@app.post("/api/final/submit")
async def final_submit(session_id: str = Form(...), format: str = Form("png"),
                       embed_spec: bool = Form(True)):
    """Async final: enqueue the render at the compose->rasterize boundary and return
    a job id, so the request thread doesn't block on a full-resolution paint. Same
    gate as the sync path (a proof must be stamped first)."""
    fmt = _require_format(format)
    spec, region, sources, lineage = _require_stamped(session_id)
    _require_format(fmt, spec)
    # embed photos NOW (sync), so the manifest built here and the worker's render below
    # paint the identical bytes -- the async final and its reprint stay pixel-identical.
    spec = _embed_photos(spec, spec.final_dpi())
    rp = provenance.region_pack_block(region.dir, labels=spec.labels, biome=spec.biome)
    jid = QUEUE.submit(_render_to_blob, spec, region.dir,
                       f"{session_id}/{download_name(spec, fmt=fmt)}", fmt,
                       _final_manifest(spec, sources, embed_spec, lineage, region_pack=rp))
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
    items, skipped, fitted = [], [], []
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
        nan_frac = render._offdem_fraction(
            region.dir, region.cfg, pspec.crop,
            south_extend_m=render.oblique_south_extend_m(region.dir, region.cfg, pspec))
        if nan_frac > render.MAX_OFFDEM_NAN_FRAC:
            skipped.append({"preset": pid, "reason":
                            f"the re-fit frame extends past the region's elevation "
                            f"data ({nan_frac * 100:.0f}% has no DEM coverage)"})
            continue
        # loud boundaries: the re-fit is center-preserving but grows the frame to the
        # device's aspect + zoom floor, and nobody proofed the result -- report how far
        # each rendered device drifted from the accepted frame (area ratio; 1.0 = the
        # proofed picture, 2.0 = twice the ground). The UI names growth, never hides it.
        pa = (spec.crop[2] - spec.crop[0]) * (spec.crop[3] - spec.crop[1])
        na = (pspec.crop[2] - pspec.crop[0]) * (pspec.crop[3] - pspec.crop[1])
        fitted.append({"preset": pid, "crop_growth": round(na / pa, 2)})
        items.append((pspec, f"tecopa_{region.id}_{p.id}_{p.px_w}x{p.px_h}.png"))
    if not items:
        raise HTTPException(422, "No requested device fits this region: "
                            + "; ".join(s["reason"] for s in skipped))
    jid = QUEUE.submit(_render_bundle_to_blob, items, region.dir,
                       f"{session_id}/{download_name(spec, '_wallpapers', 'zip')}",
                       region.cfg, sources, embed_spec,
                       lineage, provenance.region_pack_block(
                           region.dir, labels=spec.labels, biome=spec.biome))
    log.info("event=wallpapers.submit session=%s region=%s n=%d skipped=%d",
             session_id, region.id, len(items), len(skipped))
    return {"job": jid, "count": len(items), "skipped": skipped, "fitted": fitted}

# ---- time-lapse: the poster as a film ----

# The film's containers: the archival APNG (manifest + ICC, the default) and its share
# twins -- WebP (ICC only) and MP4 (nothing) -- lossy, manifest-less, for posting on
# the surfaces that flatten an APNG. Values are the blob-key/file extension (the apng
# IS a PNG, so it keeps .png and the image/png mapping below).
TIMELAPSE_FORMATS = {"apng": "png", "webp": "webp", "mp4": "mp4"}

def _timelapse_format_or_422(fmt: str) -> str:
    """Membership + availability, the _require_format posture: an unknown format and a
    missing optional encoder are both an honest 422 up front, never a worker error."""
    fmt = (fmt or "apng").lower()
    if fmt not in TIMELAPSE_FORMATS:
        raise HTTPException(422, f"format must be one of {sorted(TIMELAPSE_FORMATS)}")
    if fmt == "mp4" and not timelapse.MP4_AVAILABLE:
        raise HTTPException(422, "MP4 export needs the share extra — "
                                 "pip install -r requirements-share.txt")
    return fmt

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
        nan_frac = render._offdem_fraction(
            region.dir, region.cfg, tspec.crop,
            south_extend_m=render.oblique_south_extend_m(region.dir, region.cfg, tspec))
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
    # flatten-safe encoding flag (v1.11): strictly `is True` -- a crafted value
    # degrades to the legacy encode, and a pre-feature film (no key) re-encodes
    # byte-identically. The one place the untrusted block chooses an encoder branch.
    return pacing, dpi, anim.get("default_image") is True

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
                           embed_spec: bool = Form(True),
                           format: str = Form("apng"),
                           light_motion: str = Form("none")):
    """Render an accepted composition as a time-lapse film: the day-ordered journeys
    accumulate over a static terrain base to the complete poster (the last frame IS the
    still final -- invariant 1). `format` picks the container: `apng` (default) is the
    archival film, self-describing and reprintable; `webp` and `mp4` are share twins --
    lossy, for posting -- which carry NO manifest by construction, so `embed_spec` is
    IGNORED for them (there is nothing they could embed; the privacy posture is that of
    an embed_spec=false share copy, always). MP4 needs the optional share extra (an
    honest 422 when absent). Same stamped-spec gate as a final. Enqueues ONE job ->
    the existing /api/jobs/{id} -> /result flow (the key's extension maps the media
    type). The target is the accepted sheet (bounded, screen-default dpi) or a
    wallpaper preset (exact device pixels)."""
    fmt = _timelapse_format_or_422(format)   # cheap membership first, like the finals
    if light_motion not in ("none", "diurnal", "seasonal", "auto"):
        raise HTTPException(422, "light_motion must be none, diurnal, seasonal, or auto")
    spec, region, sources, lineage = _require_stamped(session_id)
    pacing = _timelapse_pacing_or_422(max_frames, step_ms, hold_ms, leader_ms)
    tspec, target_dpi = _timelapse_target(spec, region, wallpaper_preset, dpi)
    frames = _animation_ceiling_or_422(tspec, target_dpi, pacing["max_frames"])
    # Journey Light film (v1.9): the moving sun repaints the base per frame, so it is a
    # share twin only (never the reprintable archival APNG) and needs timestamped tracks.
    track_times = anchor = None
    if light_motion != "none":
        if fmt == "apng":
            raise HTTPException(422, "A Journey Light film (the sun travels with the hike) "
                                     "is a share twin — choose the WebP or MP4 format.")
        st = session.get(session_id)
        anchor = solar.track_anchor(st["tracks"])
        if anchor is None:
            raise HTTPException(422, "A Journey Light film needs timestamped tracks "
                                     "(a GPX with <time>).")
        track_times = [t.coords_t for t in st["tracks"]]
    jid = QUEUE.submit(_render_timelapse_to_blob, tspec, region.dir,
                       f"{session_id}/{download_name(tspec, '_film', TIMELAPSE_FORMATS[fmt])}",
                       target_dpi,
                       pacing, sources, embed_spec, lineage,
                       provenance.region_pack_block(region.dir, labels=tspec.labels,
                                                    biome=tspec.biome), fmt,
                       light_motion, track_times, anchor,
                       # new films are flatten-safe (the complete poster as the APNG
                       # default image); the flag rides the manifest so the file
                       # reprints its own encoding. Pre-feature films keep theirs.
                       default_image=True)
    log.info("event=timelapse.submit session=%s region=%s frames=%d dpi=%.0f fmt=%s motion=%s",
             session_id, region.id, frames, target_dpi, fmt, light_motion)
    return {"job": jid, "frames": frames}

@app.post("/api/mockups/submit")
async def mockups_submit(file: UploadFile = File(...),
                         variants: str = Form("plate,frame"),
                         sizes: str = Form("1080x1080,1080x1350"),
                         video: bool = Form(False),
                         caption: bool = Form(True)):
    """Stage a finished poster (or film) as photographed wall art for social — the
    embossed Plate and the matted Frame, straight from the file's own pixels. Stateless
    like /api/reprint: the artwork rides the upload, so any old final works, live session
    or not. Honest 422s up front (not a PNG, a bad variant/size, or the MP4 share extra
    missing) before enqueueing; the render (slow, and slower for the yaw-loop MP4) runs on
    the queue and returns a job whose result is one zip of JPEGs/MP4s. Share-class assets:
    no manifest aboard, by construction."""
    from app import mockups
    data = await _read_capped(file)
    if not data.startswith(mockups.PNG_MAGIC):
        raise HTTPException(422, "not a PNG — mockups take a Tecopa Printworks final (poster or film)")
    vs = [v.strip() for v in variants.split(",") if v.strip()]
    if not vs:
        raise HTTPException(422, "pick at least one variant (plate, frame)")
    for v in vs:
        if v not in mockups.VARIANTS:
            raise HTTPException(422, f"unknown variant {v!r} — choose from {', '.join(mockups.VARIANTS)}")
    try:
        szs = mockups.parse_sizes(sizes)
    except mockups.MockupError as e:
        raise HTTPException(422, str(e))
    if len(vs) * len(szs) > mockups.MAX_COMBOS:
        raise HTTPException(422, f"too many mockups ({len(vs)}×{len(szs)}) — keep variants×sizes ≤ {mockups.MAX_COMBOS}")
    # a film input (or an explicit video request) needs the MP4 share extra: 422 now,
    # never a worker error (the timelapse_format posture).
    animated = getattr(Image.open(io.BytesIO(data)), "n_frames", 1) > 1
    if (video or animated) and not timelapse.MP4_AVAILABLE:
        raise HTTPException(422, "MP4 mockups need the share extra — pip install -r requirements-share.txt")
    key = f"mockups/{hashlib.sha256(data).hexdigest()[:16]}/mockups.zip"
    jid = QUEUE.submit(_render_mockups_to_blob, data, vs, szs, video, caption, key)
    log.info("event=mockups.submit variants=%s sizes=%s video=%s", ",".join(vs), sizes, video)
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
    # the blob key carries both the format (its extension maps the media type;
    # FINAL_FORMATS stays the single source of truth for the formats it owns) and the
    # self-documenting download name (download_name built the key's basename at
    # submit time, from the spec that rendered these bytes).
    ext = key.rsplit(".", 1)[-1] if "." in key else "png"
    media = (FINAL_FORMATS[ext][1] if ext in FINAL_FORMATS
             else "application/zip" if ext == "zip"
             else "image/webp" if ext == "webp"
             else "video/mp4" if ext == "mp4" else "application/octet-stream")
    return FileResponse(BLOBS.path(key), media_type=media,
                        filename=os.path.basename(key))

# ---- self-describing posters: reprint from the file alone (no session, no DB) ----
# A Tecopa Printworks PNG carries its own spec (see provenance.py). These two endpoints read
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
        raise HTTPException(422, "This file carries no Tecopa Printworks manifest — it can't be reprinted. "
                                 "Only PNG finals exported with reprint data embedded are self-describing.")
    return m

def _file_pack_version(manifest) -> str | None:
    """The manifest's region_pack.pack_version, but only when it can NAME a real plate:
    a 12-lowercase-hex string, the one shape the documented derivation ever produces.
    Anything else -- a non-string, an empty string, a crafted megabyte blob -- is
    treated as no pack at all: it can never match a plate, echoing it would reflect
    unbounded untrusted bytes into error bodies and the inspect report, and a falsy
    value would otherwise split the truthy verify gate from inspect's verdict."""
    rp = (manifest or {}).get("region_pack")
    pv = rp.get("pack_version") if isinstance(rp, dict) else None
    if isinstance(pv, str) and len(pv) == 12 and all(c in "0123456789abcdef" for c in pv):
        return pv
    return None

def _manifest_region_or_422(spec, verb: str, manifest=None):
    """The built region a manifest names, or a 422: a poster whose region isn't built on
    THIS server can't be reprinted/continued here. `verb` ("reprinted"/"continued") fills
    the message. When the manifest carries a region_pack block AND this server's plate
    is hash-manifested, the plate is VERIFIED against this server's own
    (region_pack_block, with the FILE's labels toggle so both sides hash the same asset
    set): a rebuilt plate would reprint the poster *differently*, silently -- honest
    refusal over silent wrongness. A manifest without the block (pre-pack poster, or
    manifest=None) skips verification, and so does a server plate without sources.json
    (MANIFEST.md's `absent` semantics: a hand-built plate stays printable) -- soft
    forever-compat, same stance as every other additive manifest key. Availability and
    plate identity are per-server capability checks, so they live here rather than in
    provenance.spec_from_manifest (which only hardens the untrusted spec itself)."""
    file_pv = _file_pack_version(manifest)
    region = REGIONS.get(spec.region_id)
    if region is None:
        painted = f" It was painted on plate {file_pv}." if file_pv else ""
        raise HTTPException(422, f"Region {spec.region_id!r} isn't built on this server, "
                                 f"so this poster can't be {verb} here.{painted}")
    if file_pv:
        server = provenance.region_pack_block(region.dir, labels=spec.labels,
                                              biome=spec.biome)
        if server is not None and server["pack_version"] != file_pv:
            # "reprinted" -> "reprint", "continued" -> "continue" (rstrip would eat
            # continue's own trailing e); an unknown future verb reads as-is.
            base = {"reprinted": "reprint", "continued": "continue"}.get(verb, verb)
            raise HTTPException(
                422, f"this poster was painted on the {spec.region_id} plate {file_pv}; "
                     f"this server has {server['pack_version']} — "
                     f"install the original plate to {base} it exactly.")
    return region

@app.post("/api/reprint/inspect")
async def reprint_inspect(file: UploadFile = File(...)):
    """Read a poster's provenance without rendering: which region, the source-file
    hashes, and a spec summary. Pure read of the embedded manifest -- never decodes the
    image, so it's cheap and safe on any uploaded PNG."""
    manifest = _manifest_or_422(await _read_capped(file))
    spec_d = manifest.get("spec", {})
    # resolve the region the way /api/reprint does: spec.region_id is what
    # spec_from_manifest renders against; the top-level duplicate is a cheap-inspection
    # convenience a crafted file can diverge -- the verdict must follow the verb.
    region_id = spec_d.get("region_id") or manifest.get("region_id")
    # plate verdict, straight off the manifest + the server's own block -- no spec is
    # built (inspect stays a pure, cheap read). Mirrors _manifest_region_or_422's
    # decision, as a report instead of a refusal: same pack_version predicate
    # (_file_pack_version), same region resolution, same labels toggle on both sides.
    file_pv = _file_pack_version(manifest)
    region = REGIONS.get(region_id)
    server_pv = None
    if region is None:
        plate = "region_missing"
    else:
        server = provenance.region_pack_block(
            region.dir, labels=bool(spec_d.get("labels", False)),
            biome=bool(spec_d.get("biome", False)))
        server_pv = server["pack_version"] if server else None
        if file_pv is None or server_pv is None:
            plate = "unverifiable"                # pre-pack file, or a hand-built plate
        else:
            plate = "verified" if file_pv == server_pv else "mismatch"
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
        # plate identity: can THIS server reproduce these exact pixels?
        "plate": plate,
        "plate_file": file_pv,
        "plate_server": server_pv,
    }

@app.post("/api/reprint")
async def reprint(file: UploadFile = File(...), format: str = Form("png"),
                  embed_spec: bool = Form(True)):
    """Re-render a Tecopa Printworks PNG at print resolution from the file alone. Stateless:
    the spec rides the file, so no session or DB row is needed -- a printed poster is
    reproducible forever, photos included (they ride the manifest as embedded bytes).
    The embedded spec is UNTRUSTED input: it passes through provenance.spec_from_manifest
    (the single untrusted-manifest door -- parse, drop non-embedded photos, bound the
    geometry, validate aspect / the 120 MP ceiling / the zoom cap) before any pixels are
    made, so a crafted file can neither read server files nor request a gigapixel."""
    fmt = _require_format(format)      # cheap membership check BEFORE reading the file
    data = await _read_capped(file)
    manifest = _manifest_or_422(data)
    try:
        spec = provenance.spec_from_manifest(manifest)   # the one untrusted-manifest door
    except SpecError as e:
        raise HTTPException(422, str(e))
    _require_format(fmt, spec)                       # a wallpaper reprints as PNG only
    # plate verification runs HERE, before the animated/still branch: a mismatched
    # film must refuse up front, never enqueue a render against the wrong terrain.
    region = _manifest_region_or_422(spec, "reprinted", manifest)
    # an animated file re-renders the FILM (the file promises "the file is the artwork",
    # so honor it for films too). A film render is slow -> through the queue, returning a
    # job like the other async paths, not a synchronous stream. Stills keep today's
    # synchronous contract below.
    anim = manifest.get("animation")
    if isinstance(anim, dict):
        # a reprint reproduces the ARCHIVAL artifact, so a film reprints as APNG only:
        # webp/mp4 share twins come from a live session (/api/timelapse/submit) and
        # already 422 at _require_format above (they are not FINAL_FORMATS); pdf is
        # refused here.
        if fmt != "png":
            raise HTTPException(422, "a time-lapse is PNG-only")
        pacing, tl_dpi, tl_default = _animation_from_manifest_or_422(anim, spec)
        frames = _animation_ceiling_or_422(spec, tl_dpi, pacing["max_frames"])
        # the name comes from the REPRINTED spec -- its edition, its years (no clock)
        key = (f"reprint/{hashlib.sha256(data).hexdigest()[:16]}/"
               f"{download_name(spec, '_film', 'png')}")
        jid = QUEUE.submit(_render_timelapse_to_blob, spec, region.dir, key, tl_dpi,
                           pacing, manifest.get("sources", []), embed_spec,
                           manifest.get("lineage", []),
                           provenance.region_pack_block(region.dir, labels=spec.labels,
                                                        biome=spec.biome),
                           # the film's own encoding flag: a pre-v1.11 file carries
                           # none -> the legacy branch -> byte-identical reprint.
                           default_image=tl_default)
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
    # manifest's own lineage are re-embedded verbatim (never incremented here). The
    # region_pack is re-stamped from the CURRENT server's plate -- these pixels came
    # from THIS plate, and a pre-pack poster is truthfully upgraded on reprint.
    out = _encode_final(img, fmt,
                        _final_manifest(spec, manifest.get("sources", []), embed_spec,
                                        manifest.get("lineage", []),
                                        region_pack=provenance.region_pack_block(
                                            region.dir, labels=spec.labels,
                                            biome=spec.biome)),
                        dpi=spec.final_dpi())
    log.info("event=reprint region=%s fmt=%s embed=%s ms=%d",
             spec.region_id, fmt, embed_spec, int((time.time() - t0) * 1000))
    # named from the REPRINTED spec: its edition and years, not the server's clock
    # (there is no clock) -- the copy self-documents exactly like the original did.
    return StreamingResponse(io.BytesIO(out), media_type=FINAL_FORMATS[fmt][1],
                             headers={"Content-Disposition":
                                      f'attachment; filename="{download_name(spec, fmt=fmt)}"'})


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
    """Open a Tecopa Printworks PNG for its next edition. Reads the embedded spec, rebuilds a
    live session (tracks, hotspots, style, title, crop, sources), bumps the edition and
    extends the lineage chain, and returns the /api/upload response shape plus prefill
    hints so the wizard lands with everything restored. The client then adds this year's
    GPX (/api/upload), re-frames if needed, and renders -- one clean proof stamps the
    new edition (invariant 1 holds: still one spec per accepted proof)."""
    data = await _read_capped(file)
    manifest = _manifest_or_422(data)
    # same untrusted-manifest door as /api/reprint: parse, keep only size-bounded embedded
    # photos (so last year's pinned photos ride forward from inside the file, with no
    # uploads dir), bound the geometry, and validate -- one audited guard chain, so a new
    # verb can't drift from reprint's hardening. Label + icon always survive.
    try:
        spec = provenance.spec_from_manifest(manifest)   # the one untrusted-manifest door
    except SpecError as e:
        raise HTTPException(422, str(e))
    region = _manifest_region_or_422(spec, "continued", manifest)

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
    custom_device = None
    if output == "wallpaper" and matched is None:
        # a device the table doesn't carry continues as the SAME custom device: the
        # prefill hands back its pixels + ppi so the wizard restores the Frame step's
        # Custom fields. (This used to silently fall back to a print -- a custom
        # wallpaper's edition lost its output kind on the way through /api/continue.)
        matched = "custom"
        custom_device = {"px": [round(spec.print_w_in * spec.screen_ppi),
                                round(spec.print_h_in * spec.screen_ppi)],
                         "ppi": spec.screen_ppi}
    prefill = {
        # a title-less poster carries title_text="" (the "-" choice at proof time). Send
        # it back as "-" so the edition-2 proof stays title-less: an empty title would
        # otherwise re-resolve to the region name in _build_spec and regrow a title block.
        "title": spec.title_text or "-", "print_w_in": spec.print_w_in,
        "print_h_in": spec.print_h_in, "output": output, "wallpaper_preset": matched,
        "custom_device": custom_device,
        "contours": spec.contours, "compass": spec.compass, "biome": spec.biome,
        "labels": spec.labels, "edition": edition, "lineage": lineage,
        "style": {"width": spec.track_width_pt, "halo": spec.track_halo,
                  "color": f"#{r:02x}{g:02x}{b:02x}", "marker": spec.marker_diameter_in,
                  "ring": spec.marker_ring, "photoStyle": spec.photo_frame_style,
                  "furniture": spec.furniture_scale, "terrain": spec.terrain_depth,
                  "shadow": spec.shadow_strength, "oblique": spec.oblique,
                  # Journey Light restore: the resurrected file carries the RESOLVED sun
                  # (not the timestamps), so the edition keeps its light via explicit
                  # az/alt at re-proof; profile + coloring restore straight from the spec.
                  "lightMode": spec.light_mode, "sunAzimuth": spec.sun_azimuth_deg,
                  "sunAltitude": spec.sun_altitude_deg, "golden": spec.golden_strength,
                  "profile": spec.profile, "profileHeight": spec.profile_height_in,
                  # profile_rev restore: a pre-rev-2 poster continues as rev 1 -- its
                  # strip layout is the poster's own, not the current server default.
                  "profileRev": spec.profile_rev,
                  # bleed restore: a continued print keeps its trim + bleed exactly
                  # (print_w_in/print_h_in above are the TRIM size; bleed rides separately).
                  "bleed": spec.bleed_in,
                  "trackColorBy": spec.track_color_by,
                  # smart label placement + chronological weave restore from the spec
                  "labelPlace": spec.label_place, "trackWeave": spec.track_weave},
    }
    log.info("event=continue session=%s region=%s edition=%d tracks=%d hotspots=%d",
             sid, region.id, edition, len(tracks), len(spots))
    return {"session": sid, "region": region.id, "name": region.name,
            "overview": f"/regions/{region.id}/overview.png",
            "overview_size": region.cfg["overview_size"], "tracks": tpx,
            # additive: journey day grouping (caption span). spec.track_days is
            # attacker-controlled on this path (a crafted manifest can make it a
            # non-list / None), so guard the iteration the way year_span does above --
            # a bad shape becomes [], never a 500.
            "track_days": list(spec.track_days) if isinstance(spec.track_days, (list, tuple)) else [],
            "hotspots": hpx, "starter_crop": _crop_to_overview_px(region.geo, spec.crop),
            "recovered": False, "skipped_duplicates": [],
            "edition": edition, "files": [s.get("filename", "track.gpx") for s in sources],
            # the echo: what the resurrected file holds, so the wizard can say
            # "Edition 2 · Lassen · 2023–2024" back to the user. Same year_span the
            # cartouche prints and the download name carries; "" when no track is dated.
            "year_span": year_span(spec.track_days),
            # rebuilt tracks carry no timestamps (the manifest never stores them), so live
            # sun derivation is unavailable -- the prefill's resolved sun restores the light.
            "journey_light": _journey_light_meta(tracks),
            "final_dpi": FINAL_DPI,        # same client-truth contract as /api/upload
            "prefill": prefill}

app.mount("/regions", StaticFiles(directory=REGIONS_ROOT), name="regions")
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
