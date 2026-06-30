# app/main.py
import io, json, os
from typing import List, Optional
import numpy as np
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from app.geo import RegionGeo, crs_to_overview_px, crop_px_to_crs_window
from app.ingest import load_tracks
from app.density import hotspots
from app.spec import CompositionSpec, ZoomTooTightError
from app import session, render

REGION_ID = "lassen_ca"
REGION_DIR = os.path.join("regions", REGION_ID)
CFG = json.load(open(os.path.join(REGION_DIR, "region.json")))
GEO = RegionGeo(crs=CFG["crs"], bounds=tuple(CFG["bounds"]),
                overview_size=tuple(CFG["overview_size"]))

PROOF_DPI = 96    # cheap mid-fidelity preview
FINAL_DPI = 300   # print resolution -- the zoom cap is judged against THIS

app = FastAPI()

@app.post("/api/upload")
async def upload(files: List[UploadFile] = File(...), session_id: Optional[str] = Form(None)):
    new = []
    for f in files:
        try:
            new += load_tracks(await f.read(), GEO, filename=f.filename)   # GPX / KML / KMZ
        except Exception:
            continue   # skip one unparseable file rather than 500 the whole batch
    if session_id and session.has(session_id):
        tracks = session.get(session_id)["tracks"] + new               # accumulate
        sid = session_id
    else:
        tracks, sid = new, None
    if not tracks:
        raise HTTPException(400, "No usable tracks in file(s)")
    spots = hotspots(tracks, region_bounds=CFG["bounds"])
    if sid is None:
        sid = session.create({"tracks": tracks, "hotspots": spots})
    else:
        # invalidate any stamped spec: the track set changed, so /api/final must
        # not render a stale proof (it re-enforces "approve a proof first").
        session.update(sid, tracks=tracks, hotspots=spots, spec=None)
    # project to overview pixels for the aim canvas
    tpx = [[crs_to_overview_px(GEO, x, y) for x, y in t.coords] for t in tracks]
    hpx = [{"px": crs_to_overview_px(GEO, s["x"], s["y"]), "weight": s["weight"]} for s in spots]
    return {"session": sid, "overview": f"/regions/{REGION_ID}/overview.png",
            "overview_size": CFG["overview_size"], "tracks": tpx, "hotspots": hpx}

def _build_spec(sid, crop_px, print_w, print_h, title=""):
    st = session.get(sid)   # KeyError on unknown sid -> caller maps to 404
    crop = crop_px_to_crs_window(GEO, *crop_px)
    spec = CompositionSpec(
        region_id=REGION_ID, crs=CFG["crs"], crop=crop,
        print_w_in=print_w, print_h_in=print_h,
        native_resolution_m=CFG["native_resolution_m"],
        tracks=[t.coords for t in st["tracks"]],
        hotspots=st["hotspots"], seed=7, title_text=title)
    spec.validate(FINAL_DPI)   # gate on the resolution the PRINT uses, not the proof's
    session.update(sid, spec=spec)   # stamp it (invariant 1): final renders from this
    return spec

@app.post("/api/proof")
async def proof(session_id: str = Form(...),
                x0: float = Form(...), y0: float = Form(...),
                x1: float = Form(...), y1: float = Form(...),
                print_w: float = Form(18.0), print_h: float = Form(24.0)):
    try:
        spec = _build_spec(session_id, (x0, y0, x1, y1), print_w, print_h)
    except KeyError:
        raise HTTPException(404, "Unknown or expired session")
    except ZoomTooTightError as e:
        raise HTTPException(422, str(e))
    img = render.rasterize(spec, dpi=PROOF_DPI, region_dir=REGION_DIR, watermark=True)
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")

@app.post("/api/final")
async def final(session_id: str = Form(...)):
    try:
        spec = session.get(session_id).get("spec")
    except KeyError:
        raise HTTPException(404, "Unknown or expired session")
    if spec is None:
        raise HTTPException(400, "Approve a proof first")
    try:
        img = render.rasterize(spec, dpi=FINAL_DPI, region_dir=REGION_DIR, watermark=False)
    except ZoomTooTightError as e:
        raise HTTPException(422, str(e))
    out = os.path.join(REGION_DIR, f"final_{session_id}.png")
    render.save_print(img, out, dpi=FINAL_DPI)
    return FileResponse(out, media_type="image/png", filename="trailprint.png")

app.mount("/regions", StaticFiles(directory="regions"), name="regions")
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
