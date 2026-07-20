#!/usr/bin/env python3
"""Generate a macOS app icon (1024px, native rounded-rect) from a region overview.

Usage: python scripts/macos/make_icon.py <source.png> <out.png>
Default source is the Tushar Mountains relief overview. Swap the source (any
regions/<id>/overview.png) and rerun to rebrand the icon, then rebuild the app.
"""
import sys
from PIL import Image, ImageDraw

DEFAULT_SRC = "regions/tushar_beaver_ut/overview.png"
CANVAS = 1024
INSET = 100                        # transparent padding around the tile
TILE = CANVAS - 2 * INSET          # 824
RADIUS = round(TILE * 0.2237)      # Apple-ish continuous corner radius


def main() -> None:
    src_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    out_path = sys.argv[2] if len(sys.argv) > 2 else "scripts/macos/icon.png"

    src = Image.open(src_path).convert("RGB")
    w, h = src.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    src = src.crop((left, top, left + s, top + s)).resize((TILE, TILE), Image.LANCZOS)

    mask = Image.new("L", (TILE, TILE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, TILE - 1, TILE - 1], radius=RADIUS, fill=255)

    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas.paste(src, (INSET, INSET), mask)
    canvas.save(out_path)
    print("wrote", out_path, canvas.size)


if __name__ == "__main__":
    main()
