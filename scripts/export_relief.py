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

A plate with a story in marketing/stories.toml (the five showcase plates) also gets one
image per story section, from the farm's `stories`, `journey`, `editions` and `film`
tiers (`story_images`):

  story-<n>.webp        1200 px long edge, WebP q84   story_<n>.png, a 1:1 crop
  journey-before.webp   1200 px long edge, WebP q84   story_<n>_before.png (Journey Light
  journey-after.webp    1200 px long edge, WebP q84   section: the plain poster's crop,
                                                      then the lit poster's)
  edition-<n>.webp      840 px long edge, WebP q80    edition_<n>.png, n = 1, 2, 3
  film.mp4              copied, not re-encoded        film.mp4

A plate with no story writes the six above and nothing else.

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
from scripts.story_config import story_for  # noqa: E402
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
STORY_PX = 1200                 # a story crop's long edge, like detail.webp
STORY_QUALITY = 84
EDITION_PX = 840                # an edition at wall size, like wall.webp
EDITION_QUALITY = 80
EDITIONS = (1, 2, 3)

# WebP outputs and their quality, from the spec's section 5 table
OUTPUTS = {"coin.webp": 82, "poster-relief.webp": 84, "wall.webp": 80, "detail.webp": 84}
# libwebp's slowest, smallest setting. Pinned: the default can change between Pillow
# releases, and a different method is a different byte stream.
WEBP_METHOD = 6


class ReliefError(ValueError):
    """The region cannot be exported: a source render is missing or unreadable."""


class StorySourceError(ReliefError):
    """A plate's story cannot export: a section's source image or the film is missing, or
    is smaller than the image made from it. The farm counts it as a failure of the run
    (a story the page shows must export whole), not a skipped tier."""


class ReliefRefused(ReliefError):
    """The terrain gate refused the region: no real terrain record in the index."""


def load_index(assets_dir: str) -> dict:
    """`<assets_dir>/index.json`, or {} when absent or malformed.

    Any farm output root, not only the repo's `assets/`. {} vouches for nothing,
    so the gate refuses.
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


def _story_source(src_dir: str, name: str, region_id: str) -> str:
    path = os.path.join(src_dir, name)
    if not os.path.isfile(path):
        raise StorySourceError(f"{region_id}: no {name} in {src_dir} -- render the farm's "
                               f"stories, journey, editions and film tiers first")
    return path


def story_images(src_dir: str, story: dict | None, region_id: str = "") -> dict[str, bytes]:
    """The web images of a plate's story, encoded, keyed by output name. {} for a plate
    with no story. Reads the farm's own files from `src_dir`:

      a `poster` section          story_<n>.png                    -> story-<n>.webp
      a `poster_journey` section  story_<n>_before.png, story_<n>.png
                                                  -> journey-before.webp, journey-after.webp
      an `editions` section       edition_1..3.png                 -> edition-<n>.webp
      a `film` section            film.mp4                         -> film.mp4, as is

    A missing source raises ReliefError naming it: the page shows every one of these,
    so a story that cannot export all of them exports none. So does a source whose long
    edge is under its output's size: the images are print pixels, never upscaled. (The
    six images above keep their old resize either way.)"""
    if not story:
        return {}
    out: dict[str, bytes] = {}

    def crop(src_name: str, out_name: str, px: int, quality: int) -> None:
        img = Image.open(_story_source(src_dir, src_name, region_id)).convert("RGB")
        if max(img.size) < px:
            # a story image is print pixels, scaled down or taken as they are, never up
            raise StorySourceError(
                f"{region_id}: {src_name} is {img.size[0]} x {img.size[1]} px, under the "
                f"{px} px {out_name} needs -- widen the section's crop_in or render the "
                f"farm at full dpi, not --quick")
        out[out_name] = _webp(_long_edge(img, px), quality)

    for n, section in enumerate(story.get("sections", []), start=1):
        variant = section.get("variant")
        if variant == "poster":
            crop(f"story_{n}.png", f"story-{n}.webp", STORY_PX, STORY_QUALITY)
        elif variant == "poster_journey":
            crop(f"story_{n}_before.png", "journey-before.webp", STORY_PX, STORY_QUALITY)
            crop(f"story_{n}.png", "journey-after.webp", STORY_PX, STORY_QUALITY)
        elif variant == "editions":
            for ed in EDITIONS:
                crop(f"edition_{ed}.png", f"edition-{ed}.webp", EDITION_PX, EDITION_QUALITY)
        elif variant == "film":
            path = _story_source(src_dir, "film.mp4", region_id)
            with open(path, "rb") as f:
                out["film.mp4"] = f.read()
    return out


def export_region(src_dir: str, out_dir: str, region_id: str, index: dict,
                  story: dict | None = None) -> list[str]:
    """Gate, read, encode, then write. Returns the written paths.

    `story` is the plate's table from marketing/stories.toml, or None for a plate with
    none; it adds the story's images (`story_images`) to the six.

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
    encoded.update(story_images(src_dir, story, region_id))
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
            made = export_region(os.path.join(args.assets, rid), dest, rid, index,
                                 story=story_for(rid))
        except ReliefError as ex:
            print(f"! {ex}", file=sys.stderr)
            status = 1
            continue
        for path in made:
            print(path)
    return status


if __name__ == "__main__":
    sys.exit(main())
