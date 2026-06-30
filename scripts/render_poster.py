# scripts/render_poster.py
"""Render the finalized 18x24 Lassen poster from the synthetic GPX, for by-eye
style judgement. Writes a 96-dpi full-poster proof and a 300-dpi detail crop.

    ./.venv/bin/python scripts/render_poster.py
"""
import json, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.geo import RegionGeo
from app.ingest import load_tracks
from app.density import hotspots
from app.spec import CompositionSpec
from app.render import rasterize, save_print

REGION_DIR = "regions/lassen_ca"
OUT_DIR = os.path.join(REGION_DIR)

def main():
    cfg = json.load(open(os.path.join(REGION_DIR, "region.json")))
    bx = cfg["bounds"]
    cx = (bx[0] + bx[2]) / 2
    cy = (bx[1] + bx[3]) / 2

    region = RegionGeo(crs=cfg["crs"], bounds=tuple(bx),
                       overview_size=tuple(cfg["overview_size"]))

    # real track on the terrain (synthetic Susanville<->Eagle Lake fixture for now)
    data = open("tests/fixtures/sample.gpx", "rb").read()
    tracks = load_tracks(data, region, filename="sample.gpx")
    print(f"tracks: {len(tracks)}  days: {sorted({t.day for t in tracks})}")
    track_arrays = [t.coords for t in tracks]
    spots = hotspots(tracks, tuple(bx))
    print(f"hotspots: {len(spots)}")

    # v1.1 demo: name + icon each hotspot, and pin a (synthetic) photo on the first,
    # so the poster shows the rich-marker layer. Real labels/photos come from the UI.
    labels = ["Base Camp", "The Notch", "Eagle Lake", "South Shore", "Marina"]
    icons = ["camp", "peak", "water", "flag", "camera"]
    for k, s in enumerate(spots):
        s["label"] = labels[k % len(labels)]
        s["icon"] = icons[k % len(icons)]
    if spots:
        from PIL import Image as _Img
        demo = _Img.new("RGB", (240, 180))
        px = demo.load()
        for yy in range(180):                      # quick sky->ground gradient stand-in
            for xx in range(240):
                t = yy / 180
                px[xx, yy] = (int(150 + 60*t), int(170 - 40*t), int(190 - 120*t))
        photo_path = os.path.join(OUT_DIR, "demo_photo.png")
        demo.save(photo_path)
        spots[0]["photo"] = photo_path

    # finalized 18x24 crop: 54x72 km -> exactly 10 m/px at 18x24 in @ 300 dpi (zoom cap)
    crop = (cx - 27000, cy - 36000, cx + 27000, cy + 36000)
    spec = CompositionSpec(
        region_id=cfg["id"], crs=cfg["crs"], crop=crop,
        print_w_in=18, print_h_in=24, native_resolution_m=cfg["native_resolution_m"],
        tracks=track_arrays, hotspots=spots, seed=7,
        title_text="LASSEN COUNTY  ·  CALIFORNIA")

    # full-poster proof (96 dpi): the whole composition, fast to eyeball
    proof = rasterize(spec, dpi=96, region_dir=REGION_DIR, watermark=False)
    proof_path = os.path.join(OUT_DIR, "poster_proof.png")
    proof.save(proof_path)
    print(f"wrote {proof_path}  {proof.size}")

    # 300-dpi detail crop centered on the densest hotspot, to judge fine relief +
    # ink texture at true print fidelity (kept to ~2000 px so it's viewable)
    if spots:
        hx, hy = spots[0]["x"], spots[0]["y"]
    else:
        hx, hy = cx, cy
    # 6 km x 8 km window (0.75 aspect) at 300 dpi -> 6000/(W) ... keep >= 10 m/px:
    # 6 km on a print width that yields >=10 m/px -> use a 2.0x2.667 in print tile.
    dw, dh = 6000, 8000
    detail_crop = (hx - dw/2, hy - dh/2, hx + dw/2, hy + dh/2)
    # 2.0 in wide @ 300 = 600 px -> 6000/600 = 10 m/px exactly (passes the cap)
    detail = CompositionSpec(
        region_id=cfg["id"], crs=cfg["crs"], crop=detail_crop,
        print_w_in=2.0, print_h_in=2.6667, native_resolution_m=cfg["native_resolution_m"],
        tracks=track_arrays, hotspots=spots, seed=7, title_text="")
    detail_img = rasterize(detail, dpi=300, region_dir=REGION_DIR, watermark=False)
    detail_path = os.path.join(OUT_DIR, "poster_detail_300dpi.png")
    detail_img.save(detail_path)
    print(f"wrote {detail_path}  {detail_img.size}")

if __name__ == "__main__":
    main()
