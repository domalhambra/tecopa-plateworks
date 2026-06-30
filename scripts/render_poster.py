# scripts/render_poster.py
"""Render a region's poster from a GPX for by-eye judging. Multi-region aware:
frames the crop to the track and derives a print size that lands exactly on the
10 m/px zoom-cap floor at 300 dpi, so any region/track renders without fuss.

    ./.venv/bin/python scripts/render_poster.py                       # lassen + synthetic
    ./.venv/bin/python scripts/render_poster.py --region susanville_reno --gpx /path/to.gpx
"""
import argparse, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.regions import Region
from app.ingest import load_tracks
from app.density import hotspots
from app.spec import CompositionSpec
from app.render import rasterize

NATIVE_FLOOR_DPI = 300        # the cap is judged at the print DPI; 10 m/px at 300

def _frame_crop(region):
    """Frame the whole curated region as the poster (the track sits inside it), with
    a print size that lands the crop exactly on the data floor: 300 dpi == 10 m/px."""
    rb = region.cfg["bounds"]; floor = region.cfg["native_resolution_m"]
    crop = (rb[0], rb[1], rb[2], rb[3])
    pw = (rb[2] - rb[0]) / (floor * NATIVE_FLOOR_DPI)
    ph = (rb[3] - rb[1]) / (floor * NATIVE_FLOOR_DPI)
    return crop, pw, ph

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", default="lassen_ca")
    ap.add_argument("--gpx", default="tests/fixtures/sample.gpx")
    args = ap.parse_args()

    region = Region(args.region)
    out_dir = region.dir
    data = open(args.gpx, "rb").read()
    tracks = load_tracks(data, region.geo, filename=os.path.basename(args.gpx))
    if not tracks:
        sys.exit(f"no tracks in {args.gpx} fall within region {args.region}")
    print(f"region {args.region}  tracks: {len(tracks)}  days: {sorted({t.day for t in tracks})}")
    track_arrays = [t.coords for t in tracks]
    spots = hotspots(tracks, tuple(region.cfg["bounds"]))
    print(f"hotspots: {len(spots)}")

    # v1.1 demo: name + icon each hotspot, pin a synthetic photo on the first
    labels = ["Base Camp", "The Notch", "Eagle Lake", "South Shore", "Marina", "Trailhead", "Overlook"]
    icons = ["camp", "peak", "water", "flag", "camera", "star", "dot"]
    for k, s in enumerate(spots):
        s["label"] = labels[k % len(labels)]; s["icon"] = icons[k % len(icons)]
    if spots:
        from PIL import Image as _Img
        demo = _Img.new("RGB", (240, 180)); px = demo.load()
        for yy in range(180):
            for xx in range(240):
                t = yy / 180
                px[xx, yy] = (int(150 + 60*t), int(170 - 40*t), int(190 - 120*t))
        photo_path = os.path.join(out_dir, "demo_photo.png"); demo.save(photo_path)
        spots[0]["photo"] = photo_path

    crop, pw, ph = _frame_crop(region)
    print(f"crop {tuple(round(c) for c in crop)}  print {pw:.1f} x {ph:.1f} in")
    spec = CompositionSpec(
        region_id=region.id, crs=region.cfg["crs"], crop=crop,
        print_w_in=pw, print_h_in=ph, native_resolution_m=region.cfg["native_resolution_m"],
        tracks=track_arrays, hotspots=spots, seed=7,
        title_text=region.name.upper())

    proof = rasterize(spec, dpi=96, region_dir=out_dir, watermark=False)
    proof_path = os.path.join(out_dir, "poster_proof.png"); proof.save(proof_path)
    print(f"wrote {proof_path}  {proof.size}")

    hx, hy = (spots[0]["x"], spots[0]["y"]) if spots else ((crop[0]+crop[2])/2, (crop[1]+crop[3])/2)
    dw, dh = 6000, 8000
    detail_crop = (hx - dw/2, hy - dh/2, hx + dw/2, hy + dh/2)
    detail = CompositionSpec(
        region_id=region.id, crs=region.cfg["crs"], crop=detail_crop,
        print_w_in=2.0, print_h_in=2.6667, native_resolution_m=region.cfg["native_resolution_m"],
        tracks=track_arrays, hotspots=spots, seed=7, title_text="")
    detail_img = rasterize(detail, dpi=300, region_dir=out_dir, watermark=False)
    detail_path = os.path.join(out_dir, "poster_detail_300dpi.png"); detail_img.save(detail_path)
    print(f"wrote {detail_path}  {detail_img.size}")

if __name__ == "__main__":
    main()
