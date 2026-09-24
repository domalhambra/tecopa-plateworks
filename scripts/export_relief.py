#!/usr/bin/env python3
"""Export a region's finished renders as the web images the relief viewer draws.

The Ghost landing page (docs/superpowers/specs/2026-09-24-ghost-landing-page-design.md,
section 5) shows each coin and the hero poster in relief, drawn in the browser from two
images: a surface image and an 8-bit height map. This script makes them from the farm's
own renders, resized only:

  coin.webp             1024 px, WebP q82   the GLB coin's texture (render_model)
  coin-h.png            256 px, grayscale   the GLB coin's height field
  poster-relief.webp    1400 px long edge, WebP q84   poster.png
  poster-relief-h.png   320 px long edge, grayscale   poster.png's height field
  wall.webp             840 px long edge, WebP q80    poster.png
  detail.webp           1200 px long edge, WebP q84   detail.png

SAME RELIEF AS THE GLB: the coin's surface is `render_model._centered_square`, the crop
`build_plate_glb` textures the disc with, and its height map is
`render_model._sample_height`, the grid the GLB's vertices are displaced by. The poster's
height map is the same luminance field (`render_mockups._height_field`) at 320 px. So
the web preview and the GLB coin show the same land.

HONESTY (invariant 11): a region is exported only when `assets/index.json` records it
as rendered from real terrain. The gate is `marketing.build_deploy.terrain_guard`
itself, not a copy, and there is no override flag here.

DETERMINISM: no clock, no metadata. WebP is encoded at a fixed `method` with empty
EXIF, XMP and ICC; PNG carries no text chunks. Same renders, same bytes.

    ./.venv/bin/python scripts/export_relief.py lassen_ca tecopa_ca
    ./.venv/bin/python scripts/export_relief.py --out /tmp/media lassen_ca

Default output: `<assets>/<region>/relief/`. It is a subfolder because the farm's
`coin.webp` (the coin-spin film) already sits in `<assets>/<region>/`.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from marketing.build_deploy import terrain_guard  # noqa: E402  (the one gate, reused)
from scripts.render_mockups import _height_field, load_final  # noqa: E402
from scripts.render_model import (HEIGHT_SAMPLE, TEXTURE_PX,  # noqa: E402
                                  _centered_square, _sample_height)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COIN_PX = TEXTURE_PX            # 1024: the GLB's own texture size
COIN_HEIGHT_PX = HEIGHT_SAMPLE  # 256: the GLB's own displacement grid
POSTER_PX = 1400
POSTER_HEIGHT_PX = 320
WALL_PX = 840
DETAIL_PX = 1200

# WebP outputs and their quality, from the spec's section 5 table
OUTPUTS = {"coin.webp": 82, "poster-relief.webp": 84, "wall.webp": 80, "detail.webp": 84}
# libwebp's slowest, smallest setting. Pinned: the default can change between Pillow
# releases, and a different method is a different byte stream.
WEBP_METHOD = 6


class ReliefError(ValueError):
    """The region cannot be exported: a source render is missing or unreadable."""


class ReliefRefused(ReliefError):
    """The terrain gate refused the region: no real terrain record in the index."""


def load_index(assets_dir: str) -> dict:
    """`<assets_dir>/index.json`, or {} when absent or malformed.

    The same reading as `build_deploy.load_index`, for any farm output root rather
    than only the repo's `assets/`. {} vouches for nothing, so the gate refuses.
    """
    try:
        with open(os.path.join(assets_dir, "index.json")) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _long_edge(img: Image.Image, px: int) -> Image.Image:
    w, h = img.size
    s = px / max(w, h)
    return img.resize((round(w * s), round(h * s)), Image.LANCZOS)


def _gray8(field: np.ndarray) -> Image.Image:
    """A [0,1] height field as an 8-bit grayscale image."""
    return Image.fromarray(np.round(field * 255.0).astype(np.uint8), "L")


def _webp(img: Image.Image, quality: int) -> bytes:
    b = io.BytesIO()
    img.save(b, "WEBP", quality=quality, method=WEBP_METHOD,
             exif=b"", xmp=b"", icc_profile=None)
    return b.getvalue()


def _png(img: Image.Image) -> bytes:
    b = io.BytesIO()
    img.save(b, "PNG", optimize=True)
    return b.getvalue()


def relief_images(poster: Image.Image, detail: Image.Image) -> dict[str, bytes]:
    """Every output, encoded, from an RGB poster and an RGB detail crop."""
    small = _long_edge(poster, POSTER_HEIGHT_PX)
    poster_h = _height_field(np.asarray(small, np.float32) / 255.0)
    return {
        "coin.webp": _webp(_centered_square(poster, COIN_PX), OUTPUTS["coin.webp"]),
        "coin-h.png": _png(_gray8(_sample_height(poster))),
        "poster-relief.webp": _webp(_long_edge(poster, POSTER_PX),
                                    OUTPUTS["poster-relief.webp"]),
        "poster-relief-h.png": _png(_gray8(poster_h)),
        "wall.webp": _webp(_long_edge(poster, WALL_PX), OUTPUTS["wall.webp"]),
        "detail.webp": _webp(_long_edge(detail, DETAIL_PX), OUTPUTS["detail.webp"]),
    }


def export_region(src_dir: str, out_dir: str, region_id: str, index: dict) -> list[str]:
    """Gate, read, encode, then write. Returns the written paths.

    Nothing is read before the gate passes, and nothing is written until every output
    has encoded, so a refusal or a failure leaves no partial set behind.
    """
    if terrain_guard(index, [region_id]):
        print(f"export_relief has no override: fix the terrain record for "
              f"{region_id}, then re-export.", file=sys.stderr)
        raise ReliefRefused(f"{region_id}: no real terrain record in the index")
    sources = {}
    for name in ("poster.png", "detail.png"):
        path = os.path.join(src_dir, name)
        if not os.path.isfile(path):
            raise ReliefError(f"{region_id}: no {name} in {src_dir} -- render the farm "
                              f"first")
        sources[name] = path
    # the texture render_asset_farm._model passes to build_plate_glb: load_final's
    # first frame, which is already RGB
    frames, _durations, _manifest = load_final(sources["poster.png"])
    poster = frames[0]
    detail = Image.open(sources["detail.png"]).convert("RGB")
    encoded = relief_images(poster, detail)
    os.makedirs(out_dir, exist_ok=True)
    made = []
    for name, data in encoded.items():
        path = os.path.join(out_dir, name)
        with open(path, "wb") as f:
            f.write(data)
        made.append(path)
    return made


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("regions", nargs="+", help="region ids")
    ap.add_argument("--assets", default=os.path.join(REPO, "assets"),
                    help="the farm's output root, holding index.json (default: assets/)")
    ap.add_argument("--out", default=None,
                    help="write to <out>/<region>/ (default: <assets>/<region>/relief/)")
    args = ap.parse_args(argv)

    index = load_index(args.assets)
    status = 0
    for rid in args.regions:
        dest = (os.path.join(args.out, rid) if args.out
                else os.path.join(args.assets, rid, "relief"))
        try:
            made = export_region(os.path.join(args.assets, rid), dest, rid, index)
        except ReliefError as ex:
            print(f"! {ex}", file=sys.stderr)
            status = 1
            continue
        for path in made:
            print(path)
    return status


if __name__ == "__main__":
    sys.exit(main())
