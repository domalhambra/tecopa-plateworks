#!/usr/bin/env python3
"""Assemble the deployable landing-page root from the repo + a rendered asset farm.

The published site is `landing.html` with its asset paths rewritten and the
farm's print-resolution renders downscaled to web weights. See DEPLOY.md for
why this is a manual deploy rather than a git-connected build.

    python3 marketing/build_deploy.py [--out DIR] [--region lassen_ca]

Every image it writes is the engine's own render, resized only. Nothing here
composites, retouches, or substitutes a mockup — the marketing-honesty rule in
CLAUDE.md applies to this script as much as to the farm that feeds it.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import sys

from PIL import Image

REPO = pathlib.Path(__file__).resolve().parent.parent

# (source, published name, max width, JPEG quality) — widths follow how the
# page displays each: the poster is the hero, the editions are a triptych.
DERIVATIVES = [
    ("poster.png", "poster.jpg", 2000, 84),
    ("edition_1.png", "edition_1.jpg", 1100, 82),
    ("edition_2.png", "edition_2.jpg", 1100, 82),
    ("edition_3.png", "edition_3.jpg", 1100, 82),
    ("wallpaper_iphone.png", "wallpaper_iphone.jpg", 760, 84),
    # the 1:1 crop ships at FULL resolution -- its entire point is unscaled pixels
    ("detail.png", "detail.jpg", 10_000, 86),
]
# Copied as-is: the farm's own share twin, the 3D plate, and the og:image
# (which no src attribute references, so it has to be named explicitly).
VERBATIM = ["film.webp", "mockup_plate.glb", "mockup_plate_1080x1080.jpg"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "dist" / "landing"))
    ap.add_argument("--region", default="lassen_ca")
    args = ap.parse_args()

    src_assets = REPO / "assets" / args.region
    if not src_assets.is_dir():
        print(f"error: {src_assets} does not exist — render the asset farm first:", file=sys.stderr)
        print(f"  ./.venv/bin/python scripts/render_asset_farm.py --regions {args.region}", file=sys.stderr)
        return 1

    out = pathlib.Path(args.out)
    out_assets = out / "assets" / args.region
    if out.exists():
        shutil.rmtree(out)
    out_assets.mkdir(parents=True)

    total = 0
    for name, published, maxw, quality in DERIVATIVES:
        im = Image.open(src_assets / name)
        if im.mode in ("RGBA", "P", "LA"):
            flat = Image.new("RGB", im.size, (12, 12, 12))
            im = im.convert("RGBA")
            flat.paste(im, mask=im.split()[-1])
            im = flat
        else:
            im = im.convert("RGB")
        width, height = im.size
        if width > maxw:
            im = im.resize((maxw, round(height * maxw / width)), Image.LANCZOS)
        im.save(out_assets / published, "JPEG", quality=quality, optimize=True, progressive=True)
        size = (out_assets / published).stat().st_size
        total += size
        print(f"  {name:24s} -> {published:24s} {size/1048576:5.2f} MB  ({width} -> {im.size[0]}px)")

    for name in VERBATIM:
        shutil.copy2(src_assets / name, out_assets / name)
        size = (out_assets / name).stat().st_size
        total += size
        print(f"  {name:24s} -> {name:24s} {size/1048576:5.2f} MB  (verbatim)")

    shutil.copytree(REPO / "marketing" / "vendor", out / "vendor")
    shutil.copy2(REPO / "marketing" / "favicon.svg", out / "favicon.svg")

    html = (REPO / "marketing" / "landing.html").read_text(encoding="utf-8")
    html = html.replace("../assets/", "/assets/")
    for name, published, _, _ in DERIVATIVES:
        html = html.replace(f"/assets/{args.region}/{name}", f"/assets/{args.region}/{published}")
    html = html.replace(f"/assets/{args.region}/film.png", f"/assets/{args.region}/film.webp")

    # Every plate card carries its own orbitable coin. Copy each card's GLB when the
    # farm has rendered it; when it hasn't (the coin needs a real-DEM poster), strip
    # that card's <model-viewer> instead of publishing a broken fetch -- the card
    # degrades to the text it always was.
    for rid in set(re.findall(r'data-plate="([^"]+)"', html)):
        glb = REPO / "assets" / rid / "mockup_plate.glb"
        ref = f"/assets/{rid}/mockup_plate.glb"
        if glb.is_file():
            dest = out / "assets" / rid
            dest.mkdir(parents=True, exist_ok=True)
            if not (dest / "mockup_plate.glb").exists():
                shutil.copy2(glb, dest / "mockup_plate.glb")
                size = (dest / "mockup_plate.glb").stat().st_size
                total += size
                print(f"  {rid + '/mockup_plate.glb':38s} {size/1048576:5.2f} MB  (verbatim)")
        elif ref in html:
            html = re.sub(
                r'<model-viewer(?:(?!</model-viewer>).)*?src="' + re.escape(ref)
                + r'"(?:(?!</model-viewer>).)*?</model-viewer>',
                "", html, flags=re.S)
            print(f"  ! {rid}: no mockup_plate.glb rendered — its coin was stripped "
                  f"from the page (render the farm's model tier for it)", file=sys.stderr)
    (out / "index.html").write_text(html, encoding="utf-8")

    missing = [
        ref for ref in re.findall(r'src="/([^"]+)"', html)
        if not (out / ref).is_file()
    ]
    if missing:
        print("\nerror: published page references files not in the deploy root:", file=sys.stderr)
        for ref in missing:
            print(f"  {ref}", file=sys.stderr)
        return 1

    print(f"\n{out}  —  {total/1048576:.1f} MB, all references resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
