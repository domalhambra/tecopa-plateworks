# app/mockups.py — in-app access to the wall-art mockup renderer, for POST /api/mockups.
#
# The deterministic render core (the embossed Plate, the matted Frame, the yaw-loop MP4)
# lives in scripts/render_mockups.py — a standalone, dependency-light module already used
# by the marketing asset farm and pinned by tests/test_mockups.py. Rather than move those
# ~600 lines (which would churn that frozen test) or duplicate them, this module re-uses
# that core and adds only what the API needs: a bytes-in loader and a one-call zip builder
# that the queue worker stores. Same determinism, same honesty (only crop/resize of the
# engine's own pixels — if the product didn't render it, a mockup can't show it), same
# MockupError refusals; these are share-class assets (no manifest aboard, by construction).
from __future__ import annotations
import io
import zipfile

from PIL import Image

from app import provenance
from scripts.render_mockups import (  # the deterministic core
    render_mockup, render_mockup_video, caption_text, MockupError,
    SIZES, VARIANTS, JPEG_QUALITY, JPEG_SUBSAMPLING, PNG_MAGIC,
)

MAX_COMBOS = 4          # variants x sizes ceiling: a share kit is a handful, not a farm
MAX_DIM = 2160          # per-side pixel cap (2x a 1080 social asset)


def parse_sizes(s: str):
    """"1080x1080,1080x1350" -> [(1080,1080),(1080,1350)]. Raises MockupError on a
    malformed token or an out-of-range dimension (the honest-422 posture)."""
    out = []
    for part in (s or "").split(","):
        part = part.strip()
        if not part:
            continue
        w, _, h = part.partition("x")
        try:
            wi, hi = int(w), int(h)
        except ValueError:
            raise MockupError(f"bad size {part!r} — use WIDTHxHEIGHT, e.g. 1080x1350")
        if not (1 <= wi <= MAX_DIM and 1 <= hi <= MAX_DIM):
            raise MockupError(f"size {wi}x{hi} out of range (1..{MAX_DIM})")
        out.append((wi, hi))
    if not out:
        raise MockupError("no sizes given")
    return out


def _load_frames(data: bytes):
    """(frames, durations_ms, manifest|None) from a Tecopa Plateworks final's bytes. Mirrors
    scripts.render_mockups.load_final, but from bytes (the upload) rather than a path.
    A still yields one frame; a film APNG yields its frames + durations (-> video)."""
    if not data.startswith(PNG_MAGIC):
        raise MockupError("not a PNG — mockups take a Tecopa Plateworks final (poster or film)")
    im = Image.open(io.BytesIO(data))
    n = getattr(im, "n_frames", 1)
    frames, durations = [], []
    for i in range(n):
        im.seek(i)
        im.load()                                   # duration fills on load, not seek
        durations.append(int(im.info.get("duration", 0)))
        frames.append(im.convert("RGB"))
    return frames, durations, provenance.extract(data)


def build_zip(data: bytes, variants, sizes, *, video: bool = False,
              caption: bool = True) -> bytes:
    """Render every (variant, size) mockup for a final and pack them into one zip.
    A still emits JPEGs (and MP4s too when video=True); a film APNG always emits MP4s
    (the journeys ink themselves as the object yaws). Deterministic — the same input
    yields byte-identical members. Raises MockupError on a bad variant/size or a
    non-PNG input (the caller maps it to a 422)."""
    variants = [v.strip() for v in variants if v and v.strip()]
    if not variants:
        raise MockupError("no variants given")
    for v in variants:
        if v not in VARIANTS:
            raise MockupError(f"unknown variant {v!r} — choose from {', '.join(VARIANTS)}")
    if len(variants) * len(sizes) > MAX_COMBOS:
        raise MockupError(f"too many mockups ({len(variants)}×{len(sizes)}) — "
                          f"keep variants×sizes ≤ {MAX_COMBOS}")
    frames, durations, manifest = _load_frames(data)
    animated = len(frames) > 1

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:   # jpeg/mp4 already compressed
        for variant in variants:
            for size in sizes:
                tag = f"mockup_{variant}_{size[0]}x{size[1]}"
                if animated or video:
                    z.writestr(tag + ".mp4", render_mockup_video(
                        frames, durations, manifest, variant, size, caption=caption))
                if not animated:
                    im = render_mockup(frames[0], manifest, variant, size, caption=caption)
                    jb = io.BytesIO()
                    im.convert("RGB").save(jb, "JPEG", quality=JPEG_QUALITY,
                                           subsampling=JPEG_SUBSAMPLING, optimize=True)
                    z.writestr(tag + ".jpg", jb.getvalue())
    return buf.getvalue()
