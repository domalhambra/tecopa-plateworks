# app/main.py
import io, json, os
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
from app import session, render, regions, blobs, jobs

# The registry replaces the old single hardcoded region: every regions/<id> built
# by region_prep.py is now selectable. Discovered once at import. The root is
# env-overridable (TRAILPRINT_REGIONS) so a deploy or the test harness can point
# the app at a different region tree without editing code.
REGIONS_ROOT = os.environ.get("TRAILPRINT_REGIONS", "regions")
REGIONS = regions.discover(REGIONS_ROOT)

PROOF_DPI = 96    # cheap mid-fidelity preview
FINAL_DPI = 300   # print resolution -- the zoom cap is judged against THIS

# server foundation (v1.3): outputs go to a blob store, finals render off the
# request thread via a job queue. Both are local impls behind interfaces that a
# networked store / broker drops into later (see blobs.py, jobs.py).
BLOBS = blobs.LocalBlobs(os.environ.get("TRAILPRINT_BLOBS", "blobs"))
QUEUE = jobs.ThreadJobQueue()

app = FastAPI()

def _render_to_blob(spec, region_dir, key):
    """The render worker: rasterize the stamped spec at print DPI and store the PNG.
    Runs on a queue thread, so it touches only its arguments -- no request state."""
    img = render.rasterize(spec, dpi=FINAL_DPI, region_dir=region_dir, watermark=False)
    buf = io.BytesIO()
    img.save(buf, "PNG", dpi=(FINAL_DPI, FINAL_DPI))   # embed DPI like save_print
    BLOBS.put(key, buf.getvalue())
    return key                                         # job result = the blob key

def _region_or_404(rid):
    if rid not in REGIONS:
        raise HTTPException(404, f"Unknown region {rid!r}")
    return REGIONS[rid]

def _load_all(blobs, region):
    """Parse every uploaded blob into tracks for one region; skip unparseable ones
    rather than 500 the batch (matches the per-file tolerance the UI relies on)."""
    out = []
    for data, fn in blobs:
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

def _best_region(blobs):
    """The region holding the most track points (None if the tracks land nowhere)."""
    best, best_tracks, best_n = None, [], 0
    for r in REGIONS.values():
        tracks = _load_all(blobs, r)
        n = _count_in_bounds(tracks, r)
        if n > best_n:
            best, best_tracks, best_n = r, tracks, n
    return best, best_tracks


def _resolve_region(blobs, session_id, region_id):
    """Decide which region an upload belongs to and return (region, parsed_tracks).
    Order: an existing session is already bound; else an explicit region_id (with
    cross-region auto-recovery if the tracks don't fall in it); else the sole region;
    else auto-detect the region holding the most track points."""
    if session_id and session.has(session_id):
        region = _region_or_404(session.get(session_id)["region_id"])
        return region, _load_all(blobs, region)
    if region_id:
        region = _region_or_404(region_id)
        tracks = _load_all(blobs, region)
        # Auto-recovery: the operator pre-picked a region, but if the tracks land
        # nowhere inside it and another built region actually holds them, switch --
        # a forgiving "you dropped the wrong region's tracks" fix (v1.2).
        if _count_in_bounds(tracks, region) == 0:
            alt, alt_tracks = _best_region(blobs)
            if alt is not None:
                return alt, alt_tracks
            # tracks land in NO built region -> clean 422 (same as auto-detect),
            # rather than rendering a garbage poster for out-of-bounds tracks.
            raise HTTPException(422, "Tracks don't fall within any available region")
        return region, tracks
    if len(REGIONS) == 1:
        region = next(iter(REGIONS.values()))
        return region, _load_all(blobs, region)
    best, best_tracks = _best_region(blobs)
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

@app.post("/api/upload")
async def upload(files: List[UploadFile] = File(...),
                 session_id: Optional[str] = Form(None),
                 region_id: Optional[str] = Form(None)):
    blobs = [(await f.read(), f.filename) for f in files]
    region, new = _resolve_region(blobs, session_id, region_id)
    # recovery = the operator's explicit region was overridden because the tracks
    # actually belong to a different built region (not a plain auto-detect).
    recovered = bool(region_id and region.id != region_id
                     and not (session_id and session.has(session_id)))
    if session_id and session.has(session_id):
        tracks = session.get(session_id)["tracks"] + new               # accumulate
        sid = session_id
    else:
        tracks, sid = new, None
    if not tracks:
        raise HTTPException(400, "No usable tracks in file(s)")
    spots = hotspots(tracks, region_bounds=region.cfg["bounds"])
    if sid is None:
        sid = session.create({"tracks": tracks, "hotspots": spots, "region_id": region.id})
    else:
        # invalidate any stamped spec: the track set changed, so /api/final must
        # not render a stale proof (it re-enforces "approve a proof first").
        session.update(sid, tracks=tracks, hotspots=spots, spec=None)
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
    return {"session": sid, "region": region.id, "name": region.name,
            "overview": f"/regions/{region.id}/overview.png",
            "overview_size": region.cfg["overview_size"], "tracks": tpx,
            "hotspots": hpx, "starter_crop": list(start), "recovered": recovered}

VALID_ICONS = {"", "dot", "peak", "camp", "water", "flag", "camera", "star"}
UPLOADS_DIR = "uploads"

# Photo upload guards (red-team V1-6): a small file can declare enormous dimensions
# (decompression bomb) or just be huge. Cap the raw bytes and the decoded pixel count.
PHOTO_MAX_BYTES = 20 * 1024 * 1024
PHOTO_MAX_PIXELS = 64_000_000
# Process-wide PIL backstop: sits above the render output ceiling (spec.MAX_OUTPUT_PIXELS
# = 120 MP), so it never trips a legitimate render (built via Image.new/fromarray, not
# decoded from a file) but still bombs out an absurdly large decoded upload.
Image.MAX_IMAGE_PIXELS = 200_000_000

def _require_session(session_id):
    if not session.has(session_id):
        raise HTTPException(404, "Unknown or expired session")
    return session.get(session_id)

@app.post("/api/markers")
async def set_markers(session_id: str = Form(...), markers: str = Form(...)):
    """Set per-hotspot label/icon. `markers` is a JSON list of {i, label, icon};
    editing markers invalidates any stamped spec so the final reflects the edits."""
    st = _require_session(session_id)
    try:
        edits = json.loads(markers)
    except Exception:
        raise HTTPException(422, "markers must be JSON")
    spots = st["hotspots"]
    for e in edits:
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
    region = _region_or_404(st["region_id"])                 # geo lives on the region
    x, y = overview_px_to_crs(region.geo, px, py)
    min_x, min_y, max_x, max_y = region.cfg["bounds"]
    x = min(max(x, min_x), max_x)                             # clamp, don't reject
    y = min(max(y, min_y), max_y)
    spots[i]["x"], spots[i]["y"] = x, y
    session.update(session_id, hotspots=spots, spec=None)     # re-proof to apply
    cpx, cpy = crs_to_overview_px(region.geo, x, y)           # snap-back position
    return {"ok": True, "px": cpx, "py": cpy}

def _build_spec(sid, crop_px, print_w, print_h, title=""):
    st = session.get(sid)   # KeyError on unknown sid -> caller maps to 404
    region = _region_or_404(st["region_id"])
    crop = crop_px_to_crs_window(region.geo, *crop_px)
    spec = CompositionSpec(
        region_id=region.id, crs=region.cfg["crs"], crop=crop,
        print_w_in=print_w, print_h_in=print_h,
        native_resolution_m=region.cfg["native_resolution_m"],
        tracks=[t.coords for t in st["tracks"]],
        hotspots=st["hotspots"], seed=7, title_text=title)
    spec.validate(FINAL_DPI)   # gate on the resolution the PRINT uses, not the proof's
    # NB: not stamped here -- the caller stamps only after a clean proof render, so a
    # proof that 422s (e.g. off-DEM) leaves no stamped spec for the async final to enqueue.
    return spec, region

@app.post("/api/proof")
async def proof(session_id: str = Form(...),
                x0: float = Form(...), y0: float = Form(...),
                x1: float = Form(...), y1: float = Form(...),
                print_w: float = Form(18.0), print_h: float = Form(24.0)):
    try:
        spec, region = _build_spec(session_id, (x0, y0, x1, y1), print_w, print_h)
    except KeyError:
        raise HTTPException(404, "Unknown or expired session")
    except SpecError as e:
        raise HTTPException(422, str(e))
    try:
        img = render.rasterize(spec, dpi=PROOF_DPI, region_dir=region.dir, watermark=True)
    except SpecError as e:
        raise HTTPException(422, str(e))
    # stamp only now (invariant 1): a clean proof means the final renders from this same
    # spec. The off-DEM verdict is DPI-independent, so a stamped spec always renders.
    session.update(session_id, spec=spec)
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")

@app.post("/api/final")
async def final(session_id: str = Form(...)):
    try:
        st = session.get(session_id)
    except KeyError:
        raise HTTPException(404, "Unknown or expired session")
    spec = st.get("spec")
    if spec is None:
        raise HTTPException(400, "Approve a proof first")
    region = _region_or_404(st["region_id"])
    try:
        img = render.rasterize(spec, dpi=FINAL_DPI, region_dir=region.dir, watermark=False)
    except SpecError as e:
        raise HTTPException(422, str(e))
    out = os.path.join(region.dir, f"final_{session_id}.png")
    render.save_print(img, out, dpi=FINAL_DPI)
    return FileResponse(out, media_type="image/png", filename="trailprint.png")

@app.post("/api/final/submit")
async def final_submit(session_id: str = Form(...)):
    """Async final: enqueue the render at the compose->rasterize boundary and return
    a job id, so the request thread doesn't block on a 300 dpi paint. Same gate as
    the sync path (a proof must be stamped first)."""
    try:
        st = session.get(session_id)
    except KeyError:
        raise HTTPException(404, "Unknown or expired session")
    spec = st.get("spec")
    if spec is None:
        raise HTTPException(400, "Approve a proof first")
    region = _region_or_404(st["region_id"])
    jid = QUEUE.submit(_render_to_blob, spec, region.dir, f"{session_id}/final.png")
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
    return FileResponse(BLOBS.path(key), media_type="image/png", filename="trailprint.png")

app.mount("/regions", StaticFiles(directory=REGIONS_ROOT), name="regions")
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
