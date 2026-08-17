#!/usr/bin/env python3
"""Assemble the deployable landing-page root from the repo + a rendered asset farm.

The published site is `landing.html` with its asset paths rewritten and the
farm's print-resolution renders downscaled to web weights. See DEPLOY.md for
why this is a manual deploy rather than a git-connected build.

    python3 marketing/build_deploy.py [--out DIR] [--region lassen_ca]

Every image it writes is the engine's own render, resized only. Nothing here
composites, retouches, or substitutes a mockup — the marketing-honesty rule in
CLAUDE.md applies to this script as much as to the farm that feeds it. That rule
is enforced, not just stated: the terrain guard below refuses to publish a region
whose assets were rendered from a synthetic stand-in DEM, or whose terrain the
farm never recorded.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import sys

from PIL import Image

REPO = pathlib.Path(__file__).resolve().parent.parent
FARM_CMD = "./.venv/bin/python scripts/render_asset_farm.py --regions"

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


def load_index(repo: pathlib.Path) -> dict:
    """The asset farm's `assets/index.json`, or {} if it is absent or unreadable.

    Read with the stdlib on purpose: this script stays dependency-light (PIL and
    nothing else), and in particular does NOT import rasterio to go look at the
    DEM itself. Reading the DEM here would answer the wrong question — see
    `render_asset_farm._terrain_record`. The index is the record; trust it or
    refuse.
    """
    try:
        with open(repo / "assets" / "index.json") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def terrain_guard(index: dict, regions, allow_synthetic: bool = False,
                  allow_unverified: bool = False) -> int:
    """Refuse (1) to publish regions the farm's index does not vouch for; else 0.

    The page's footer promises every image on it is the engine's own render. A
    synthetic stand-in DEM renders *cleanly* — correct hillshade, palette, place
    labels, route ink — so the picture itself never gives it away. Without this
    check a container that could not download 700 MB of real terrain would deploy
    successfully and publish pictures of country that does not exist.

    Fail-closed, and per region: the deploy publishes `--region`'s derivatives AND
    a plate-card coin for every other region whose GLB the farm has rendered, and
    those coins are marketing images too.
    """
    def record(rid):
        entry = index.get(rid)
        rec = entry.get("terrain") if isinstance(entry, dict) else None
        return rec if isinstance(rec, dict) else None      # malformed reads as absent

    synthetic = sorted(r for r in regions if (record(r) or {}).get("synthetic"))
    unrecorded = sorted(r for r in regions if record(r) is None)

    if synthetic and not allow_synthetic:
        print("\nerror: SYNTHETIC terrain — these regions' images were rendered from a "
              "test stand-in DEM,\n       not real 3DEP terrain, so their landforms are "
              "invented:", file=sys.stderr)
        for rid in synthetic:
            print(f"  {rid}", file=sys.stderr)
        print("The page promises every image is the engine's own render. Rebuild the "
              "plate from real\nterrain (see CLAUDE.md, \"Known local failures\"), then "
              "re-render:", file=sys.stderr)
        print(f"  {FARM_CMD} {' '.join(synthetic)}", file=sys.stderr)
        print("To publish them anyway: --allow-synthetic", file=sys.stderr)
        return 1
    if unrecorded and not allow_unverified:
        print("\nerror: UNVERIFIED terrain — assets/index.json carries no terrain record "
              "for these\n       regions, so what their images were rendered from is "
              "unknown:", file=sys.stderr)
        for rid in unrecorded:
            print(f"  {rid}", file=sys.stderr)
        print("The record is stamped when the farm opens a DEM; a restage-only run "
              "(--only\ndetail/model/mockups/coin) opens none and stamps nothing. "
              "Re-render:", file=sys.stderr)
        print(f"  {FARM_CMD} {' '.join(unrecorded)}", file=sys.stderr)
        print("To publish them anyway: --allow-unverified-terrain", file=sys.stderr)
        return 1

    if synthetic:
        print(f"\nWARNING: --allow-synthetic — publishing INVENTED landforms as the "
              f"engine's own\n         render of real country: {', '.join(synthetic)}",
              file=sys.stderr)
    if unrecorded:
        print(f"\nWARNING: --allow-unverified-terrain — publishing images whose source "
              f"terrain is\n         unrecorded; they may not be real country: "
              f"{', '.join(unrecorded)}", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "dist" / "landing"))
    ap.add_argument("--region", default="lassen_ca")
    ap.add_argument("--allow-synthetic", action="store_true",
                    help="publish even where the farm rendered from a stand-in DEM")
    ap.add_argument("--allow-unverified-terrain", action="store_true",
                    help="publish even where the farm recorded no terrain at all")
    args = ap.parse_args()

    src_assets = REPO / "assets" / args.region
    if not src_assets.is_dir():
        print(f"error: {src_assets} does not exist — render the asset farm first:", file=sys.stderr)
        print(f"  {FARM_CMD} {args.region}", file=sys.stderr)
        return 1

    html = (REPO / "marketing" / "landing.html").read_text(encoding="utf-8")

    # Every region this deploy publishes anything for — the --region derivatives plus
    # each plate card whose coin the farm has actually rendered (a card with no GLB is
    # stripped below, so nothing of that region ships and nothing of it is guarded).
    published_regions = {args.region} | {
        rid for rid in set(re.findall(r'data-plate="([^"]+)"', html))
        if (REPO / "assets" / rid / "mockup_plate.glb").is_file()}
    if terrain_guard(load_index(REPO), published_regions,
                     args.allow_synthetic, args.allow_unverified_terrain):
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
