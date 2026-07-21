#!/usr/bin/env python3
"""Instagram-ready physical mockups of a finished final -- the Plate and the Frame.

Takes ANY Tecopa Plateworks final PNG and stages its pixels as a photographed object on the
landing page's gallery wall: a circular embossed terrain *plate* (the signature
Tecopa Plateworks shot) and a matted, framed print. A still final emits JPEGs
(1080x1080 and 1080x1350); a film APNG emits MP4s in which the journeys ink
themselves in day order while the object performs a subtle horizontal yaw -- the
"it's a physical thing" read, in-feed.

HONESTY (the branding plan's rule, reconciled): the artwork pixels in every output
are the engine's OWN final, untouched except crop/resize -- this script only stages
them. If the product didn't render it, a mockup can't show it.

DETERMINISM (the pack_region posture): no wall clock, no RNG -- the same input file
yields byte-identical outputs on a given host. JPEGs pin quality/subsampling (the
provenance._encode_photo precedent); MP4s ride timelapse._mp4_stream's bitexact
invocation. The caption placard uses the engine's own font chain (render._font), so
it reads in the poster's face and shares the poster's one cross-host caveat -- the
installed display face -- and nothing more. These are share-class assets: no manifest
aboard, by construction.

Stills need only Pillow+numpy (works on any customer PNG, no region data). Video
additionally needs the share extra (imageio-ffmpeg, requirements-share.txt) and the
app's timelapse module, imported lazily so still-mode stays bare.
"""
from __future__ import annotations
import argparse
import io
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import provenance  # noqa: E402  (manifest read only -- never decodes pixels)

# ---- scene: the landing page's light gallery wall (marketing/landing.html:15-22) ----
WALL        = (233, 228, 214)   # #e9e4d6  --ground (light theme)
WALL_LIT    = (244, 240, 230)   # #f4f0e6  --ground-2, upper-left where the light falls
PAPER       = (242, 239, 230)   # #f2efe6  --paper (the mat)
PAPER_EDGE  = (200, 194, 176)   # #c8c2b0  --paper-edge (light theme)
CAPTION_INK = (107, 101, 82)    # #6b6552  the landing .frame caption ink
SHADOW_RGB  = (40, 44, 28)      # the light-theme --shadow hue: rgba(40,44,28,.45)

SIZES    = ((1080, 1080), (1080, 1350))         # Instagram square + 4:5 portrait
VARIANTS = ("plate", "frame")
JPEG_QUALITY, JPEG_SUBSAMPLING = 90, 0          # fixed; 4:4:4 keeps 1px keylines clean

# ---- light: soft directional, upper-left, y-down screen coords ----
_L = np.array([-0.45, -0.60, 0.66]); LIGHT_DIR = _L / np.linalg.norm(_L)
_H = LIGHT_DIR + np.array([0.0, 0.0, 1.0]); HALF_DIR = _H / np.linalg.norm(_H)
AMBIENT = 0.58                                  # shading floor -- never crush the art

# ---- the Plate (px values are FINAL-CANVAS px: one 1080-class target, no dpi story) ----
PLATE_DIAM_FRAC   = 0.62        # of min(canvas w, h)
EMBOSS_DEPTH_PX   = 10.0        # apparent relief of the artwork's luminance
EMBOSS_STRENGTH   = 0.45        # hard cap on the shading swing (over-darkening guard)
EMBOSS_BLUR_SIGMA = 1.6         # px; pre-gradient smoothing so contours don't razor
LUM_PCTL          = (2.0, 98.0) # percentile normalization: dark posters still span
DOME_DEPTH_PX     = 7.0         # slight center-out convexity
BEVEL_W_FRAC      = 0.035       # rim bevel width, fraction of disc radius
BEVEL_DEPTH_PX    = 6.0         # rim shoulder drop -> the struck-medallion edge
SPEC_STRENGTH     = 0.16        # Blinn specular kick, the "struck metal" glint
SPEC_POWER        = 26
SPEC_TINT         = np.array([1.0, 0.97, 0.90])  # warm paper-light, not blue-white
MASK_SS           = 4           # supersample factor for the rim's anti-aliasing

# ---- the Frame (echoes the landing .frame, landing.html:63-69) ----
FRAME_MAX_W_FRAC = 0.72
FRAME_MAX_H_FRAC = 0.66
MAT_FRAC         = 0.045        # of the print's long edge (min 22 px)
FRAME_ROT_DEG    = -1.1         # the landing's exact tilt
FRAME_RADIUS_PX  = 4
SHEEN_PEAK_ALPHA = 16           # glass-adjacent diagonal sheen (subtle)

# ---- shadows (the landing --shadow "0 20px 50px -22px rgba(40,44,28,.45)", translated) ----
DROP_OFFSET_FRAC = (0.006, 0.024)
DROP_SIGMA_FRAC  = 0.020
DROP_ALPHA       = 115
DROP_SPREAD_PX   = 12           # CSS negative spread: erode silhouette before blur
CONTACT_OFFSET   = (2, 6)
CONTACT_SIGMA, CONTACT_ALPHA = 6.0, 70

ANCHOR_Y = {(1080, 1080): 0.46, (1080, 1350): 0.43}
# Caption size sits at the subtitle tier of the broadcast "safe text" rule -- readable
# text runs ~1/25-1/33 of frame height, and Instagram downscales a 1080 asset to ~430 px
# in-feed (x0.4), so anything smaller vanishes. 0.030 -> ~32 px font (~22 px cap height,
# ~1/49 of frame), which survives that downscale and reads comfortably in Stories/Reels.
# _draw_caption shrinks it to fit a long region name rather than overflow.
CAPTION_GAP_FRAC, CAPTION_SIZE_FRAC, CAPTION_TRACK_EM = 0.046, 0.030, 0.12

# ---- video: 25 fps ticks; yaw is a pure function of the tick index ----
YAW_MAX_DEG   = 2.5             # the subtle horizontal oscillation
YAW_PERIOD_S  = 4.0
LOOP_SECONDS  = 4.0             # still + --video: one full period = a seamless loop
PERSP_K       = 0.04           # trapezoid strength: edge heights scale 1 -/+ k*sin(yaw)
VIDEO_FPS     = 25              # matches timelapse.MP4_BASE_FPS (asserted in tests)

# ---- the smooth "trip draws itself" motion (farm-driven, needs the terrain) ----
# Smoothness is one tick PER reveal step (no hold-then-jump), so the line grows a little
# every frame instead of snapping a chunk and freezing. Slowness then comes from MANY
# steps, never from longer holds (holds are what read as chunky). ~180 steps at 25 fps
# is a ~7 s continuous draw. TECOPA_MOCKUP_FRAMES overrides the count (tests use a
# handful; an operator can trade smoothness for render time).
MOCKUP_MOTION_PX = 1100         # long-edge px to render the progressive reveal at
MOCKUP_FRAMES    = 180          # reveal steps -- fine enough that the pen never snaps
MOCKUP_STEP_MS   = 40           # one 25 fps tick per step: continuous, not stop-motion
MOCKUP_HOLD_MS   = 2200         # the hold on the finished map before the loop

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class MockupError(ValueError):
    """An input this script honestly refuses (not a PNG, MP4 extra missing).
    The CLI maps it to a sentence on stderr and exit code 2."""


# ---------------------------------------------------------------- input handling

def load_final(path: str):
    """(frames, durations_ms, manifest|None) from any Tecopa Plateworks final.

    A still yields one frame with duration 0; an animated APNG (the film) yields its
    frames + per-frame durations -- read back with load() per frame, the way the film
    tests do -- and routes the caller to video mode. The manifest is read from the
    file's text chunks only (provenance.extract never decodes pixels), and None (a
    share copy, a foreign PNG) is fine: the caption just goes away."""
    with open(path, "rb") as f:
        data = f.read()
    if not data.startswith(PNG_MAGIC):
        raise MockupError(f"not a PNG: {os.path.basename(path)} — mockups take a "
                          "Tecopa Plateworks final (poster or film)")
    im = Image.open(io.BytesIO(data))
    n = getattr(im, "n_frames", 1)
    frames, durations = [], []
    for i in range(n):
        im.seek(i)
        im.load()                                   # duration fills on load, not seek
        durations.append(int(im.info.get("duration", 0)))
        frames.append(im.convert("RGB"))
    return frames, durations, provenance.extract(data)


def caption_text(manifest) -> str | None:
    """The gallery placard: "LASSEN VOLCANIC — EDITION 2". Title from the spec (a
    wallpaper's empty title falls back to the region id); edition always included --
    it is the brand's recurring motif. None when nothing is derivable -- and the
    manifest is untrusted input (any crafted PNG reaches here), so a field of the
    wrong type drops the caption the same way, never a traceback."""
    if not isinstance(manifest, dict):
        return None
    spec = manifest.get("spec")
    if not isinstance(spec, dict):
        spec = {}
    title = spec.get("title_text")
    region = manifest.get("region_id")
    name = ((title if isinstance(title, str) else "").strip()
            or (region if isinstance(region, str) else ""))
    if not name:
        return None
    edition = spec.get("edition", 1)
    if edition in (None, "", 0):                    # absent/null: the default edition
        edition = 1
    try:
        edition = int(edition)
    except (TypeError, ValueError):
        return None
    return f"{name.upper().replace('_', ' ')} — EDITION {edition}"


# ---------------------------------------------------------------- imaging primitives

def _gauss_blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Separable float Gaussian (edge-padded, 3-sigma kernel) for the HEIGHT field --
    PIL's 8-bit blur would band the relief; PIL still blurs the 8-bit shadow masks."""
    if sigma <= 0:
        return a
    r = max(1, int(3 * sigma))
    x = np.arange(-r, r + 1, dtype=np.float64)
    k = np.exp(-(x * x) / (2 * sigma * sigma)); k /= k.sum()
    p = np.pad(a, ((r, r), (0, 0)), mode="edge")
    a = np.apply_along_axis(lambda m: np.convolve(m, k, mode="valid"), 0, p)
    p = np.pad(a, ((0, 0), (r, r)), mode="edge")
    return np.apply_along_axis(lambda m: np.convolve(m, k, mode="valid"), 1, p)


def _relight(art: np.ndarray, height_px: np.ndarray) -> np.ndarray:
    """The emboss core: normals from the height field, fixed directional light,
    shading normalized so a FLAT pixel shades to exactly 1.0 (global exposure is
    preserved; only slopes move), clipped to +/-EMBOSS_STRENGTH, plus a Blinn
    specular for the struck-metal glint. art float32 [0,1] HxWx3."""
    h = _gauss_blur(height_px, EMBOSS_BLUR_SIGMA)
    gy, gx = np.gradient(h)
    inv = 1.0 / np.sqrt(gx * gx + gy * gy + 1.0)
    nx, ny, nz = -gx * inv, -gy * inv, inv
    lx, ly, lz = LIGHT_DIR
    lamb = np.clip(nx * lx + ny * ly + nz * lz, 0.0, None)
    shade = (AMBIENT + (1 - AMBIENT) * lamb) / (AMBIENT + (1 - AMBIENT) * lz)
    shade = np.clip(shade, 1.0 - EMBOSS_STRENGTH, 1.0 + EMBOSS_STRENGTH)
    hx, hy, hz = HALF_DIR
    spec = np.clip(nx * hx + ny * hy + nz * hz, 0.0, 1.0) ** SPEC_POWER
    out = art * shade[..., None] + SPEC_STRENGTH * spec[..., None] * SPEC_TINT
    return np.clip(out, 0.0, 1.0)


def _height_field(art: np.ndarray) -> np.ndarray:
    """Luminance (the render.py formula: 0.2126R+0.7152G+0.0722B), percentile-
    normalized so dark or low-contrast posters still span the relief range."""
    L = 0.2126 * art[..., 0] + 0.7152 * art[..., 1] + 0.0722 * art[..., 2]
    lo, hi = np.percentile(L, LUM_PCTL)
    return np.clip((L - lo) / max(hi - lo, 1e-6), 0.0, 1.0)


def _disc_mask(d: int) -> Image.Image:
    """Anti-aliased circular alpha: drawn at MASK_SS x and LANCZOS-downscaled."""
    big = Image.new("L", (d * MASK_SS, d * MASK_SS), 0)
    ImageDraw.Draw(big).ellipse((0, 0, d * MASK_SS - 1, d * MASK_SS - 1), fill=255)
    return big.resize((d, d), Image.LANCZOS)


def make_plate_art(img: Image.Image, diam: int) -> Image.Image:
    """The embossed disc: centered-square crop of the final (the terrain subject is
    mid-sheet; the cartouche lives bottom-left and correctly falls away -- its title
    moves to the caption placard), relit as physical relief with a center dome and a
    rounded rim bevel in ONE height field, so the rim catches highlight upper-left
    and shadow lower-right exactly like the drop shadow says it should."""
    w, h = img.size
    s = min(w, h)
    art_img = img.crop(((w - s) // 2, (h - s) // 2,
                        (w - s) // 2 + s, (h - s) // 2 + s)).resize((diam, diam),
                                                                    Image.LANCZOS)
    art = np.asarray(art_img, dtype=np.float32) / 255.0
    height = _height_field(art) * EMBOSS_DEPTH_PX
    c = (diam - 1) / 2.0
    yy, xx = np.mgrid[0:diam, 0:diam]
    r = np.hypot(xx - c, yy - c) / (diam / 2.0)
    height += DOME_DEPTH_PX * np.sqrt(np.clip(1 - r * r, 0.0, 1.0))
    t = np.clip((r - (1 - BEVEL_W_FRAC)) / BEVEL_W_FRAC, 0.0, 1.0)
    height += -BEVEL_DEPTH_PX * (1 - np.cos(t * np.pi)) / 2.0
    lit = (_relight(art, height) * 255.0 + 0.5).astype(np.uint8)
    out = Image.fromarray(lit, "RGB").convert("RGBA")
    out.putalpha(_disc_mask(diam))
    ring = Image.new("RGBA", (diam * MASK_SS, diam * MASK_SS), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((MASK_SS // 2, MASK_SS // 2,
                                  diam * MASK_SS - 1 - MASK_SS // 2,
                                  diam * MASK_SS - 1 - MASK_SS // 2),
                                 outline=PAPER_EDGE + (200,), width=MASK_SS)
    return Image.alpha_composite(out, ring.resize((diam, diam), Image.LANCZOS))


def make_frame_art(img: Image.Image, max_w: int, max_h: int,
                   sheen: bool = True) -> Image.Image:
    """The matted print, straight from the landing .frame: PAPER mat, 1px PAPER_EDGE
    outer border, a hairline keyline hugging the artwork, rounded corners, an
    optional diagonal sheen, and the site's exact -1.1 degree tilt. Shadows are
    derived later from THIS rotated alpha, so silhouette and shadow cannot disagree."""
    w, h = img.size
    probe_mat = max(22, round(MAT_FRAC * max(max_w, max_h)))    # sizing estimate
    avail_w, avail_h = max_w - 2 * (probe_mat + 1), max_h - 2 * (probe_mat + 1)
    scale = min(avail_w / w, avail_h / h)
    aw, ah = max(1, round(w * scale)), max(1, round(h * scale))
    art = img.resize((aw, ah), Image.LANCZOS)
    mat = max(22, round(MAT_FRAC * max(aw, ah)))
    fw, fh = aw + 2 * (mat + 1), ah + 2 * (mat + 1)
    face = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    d = ImageDraw.Draw(face)
    d.rounded_rectangle((0, 0, fw - 1, fh - 1), radius=FRAME_RADIUS_PX,
                        fill=PAPER + (255,), outline=PAPER_EDGE + (255,), width=1)
    face.paste(art, (mat + 1, mat + 1))
    d.rectangle((mat, mat, mat + aw + 1, mat + ah + 1),
                outline=PAPER_EDGE + (255,), width=1)           # hairline keyline
    if sheen:
        yy, xx = np.mgrid[0:fh, 0:fw].astype(np.float64)
        diag = (xx / fw + yy / fh) / 2.0                        # 0 at UL, 1 at LR
        band = np.exp(-((diag - 0.38) ** 2) / (2 * 0.10 ** 2))
        alpha = (band * SHEEN_PEAK_ALPHA).astype(np.uint8)
        gloss = Image.new("RGBA", (fw, fh), (255, 255, 255, 0))
        gloss.putalpha(Image.fromarray(alpha, "L"))
        mask = Image.new("L", (fw, fh), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, fw - 1, fh - 1),
                                               radius=FRAME_RADIUS_PX, fill=255)
        face = Image.composite(Image.alpha_composite(face, gloss), face, mask)
    return face.rotate(FRAME_ROT_DEG, expand=True, resample=Image.BICUBIC)


# ---------------------------------------------------------------- the scene

def _wall(size) -> Image.Image:
    """The gallery wall: WALL_LIT falling to WALL along the light's diagonal, with a
    little extra settling in the lower-right -- the same asymmetry the object's
    shading and shadows obey."""
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    t = np.clip((xx / w + yy / h) / 2.0 * 1.25, 0.0, 1.0)
    lit, base = np.array(WALL_LIT, float), np.array(WALL, float)
    grad = lit[None, None, :] * (1 - t[..., None]) + base[None, None, :] * t[..., None]
    return Image.fromarray((grad + 0.5).astype(np.uint8), "RGB")


def _shadow_reach(sigma, spread_px, offset) -> int:
    """How far a shadow spreads past its silhouette: 3 sigma of blur, the spread
    erosion undone, plus the drop offset. Callers size their canvas by this so the
    shadow never hard-crops (a disc fills its own box edge to edge)."""
    return int(3 * sigma + spread_px + max(abs(offset[0]), abs(offset[1])) + 8)


def _shadow_layer(canvas, alpha: Image.Image, pos, offset, sigma, strength,
                  spread_px: int = 0) -> Image.Image:
    """One shadow pass: the object's own alpha, optionally eroded (the CSS negative
    spread), blurred, tinted SHADOW_RGB, placed at pos+offset on a transparent canvas.
    The alpha is PADDED before the blur so the shadow can bleed past the silhouette --
    a disc fills its diam x diam box edge to edge, so an unpadded blur hard-crops the
    shadow along the tangents (the visible 'flat cut' on the circular preview)."""
    m = _shadow_reach(sigma, spread_px, (0, 0))         # room for the blur to spread
    sil = Image.new("L", (alpha.width + 2 * m, alpha.height + 2 * m), 0)
    sil.paste(alpha, (m, m))
    if spread_px > 0:
        sil = sil.filter(ImageFilter.MinFilter(2 * spread_px + 1))
    sil = sil.filter(ImageFilter.GaussianBlur(sigma))
    layer = Image.new("RGBA", canvas, (0, 0, 0, 0))
    tint = Image.new("RGBA", sil.size, SHADOW_RGB + (0,))
    tint.putalpha(sil.point(lambda v: v * strength // 255))
    layer.alpha_composite(tint, (pos[0] + offset[0] - m, pos[1] + offset[1] - m))
    return layer


def _caption_font(px: int):
    # The engine's OWN font chain (render._font), replicated here so the placard reads
    # in the same face as the poster's cartouche beside it -- and carries the glyphs the
    # cartouche does (the edition line's em-dash; Pillow's bundled face renders it as
    # tofu). Same cross-host caveat the engine itself accepts and documents: the face
    # follows TECOPA_FONT / the installed serif, byte-identical within a host (the
    # farm's own machine), and no worse cross-host than the poster it stages. Kept a
    # local copy of the chain so still-mode stays a bare Pillow+numpy dependency.
    names = [os.environ["TECOPA_FONT"]] if os.environ.get("TECOPA_FONT") else []
    names += ["Georgia.ttf", "DejaVuSerif.ttf", "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    try:
        return ImageFont.load_default(px)
    except TypeError:                               # Pillow < 10.1: no sized default
        return ImageFont.load_default()


def _draw_caption(scene: Image.Image, text: str, top_y: int) -> None:
    """Tracked small caps under the object, gallery-placard style, sized for social
    legibility (see CAPTION_SIZE_FRAC). PIL has no letter-spacing, so glyphs are placed
    by hand; the line auto-shrinks to fit ~88% of the frame width, so a long region name
    stays on one readable line instead of overflowing. No test asserts glyph pixels
    (that would pin a Pillow release, not a behavior)."""
    d = ImageDraw.Draw(scene)
    max_w = 0.88 * scene.size[0]
    px = max(20, round(CAPTION_SIZE_FRAC * scene.size[1]))
    for _ in range(6):                                   # shrink to fit a long title
        font = _caption_font(px)
        track = CAPTION_TRACK_EM * px
        widths = [d.textlength(ch, font=font) for ch in text]
        total = sum(widths) + track * (len(text) - 1)
        if total <= max_w or px <= 16:
            break
        px = max(16, int(px * max_w / total))            # scale to fit, then re-measure
    x = (scene.size[0] - total) / 2.0
    for ch, cw in zip(text, widths):
        d.text((x, top_y), ch, fill=CAPTION_INK, font=font)
        x += cw + track


def _scene_base(size, caption: str | None, obj_bottom_y: int) -> Image.Image:
    base = _wall(size).convert("RGBA")
    if caption:
        _draw_caption(base, caption,
                      obj_bottom_y + round(CAPTION_GAP_FRAC * size[1]))
    return base


def _object_pos(size, art: Image.Image):
    w, h = size
    ax, ay = art.size
    cy = round(ANCHOR_Y.get(tuple(size), 0.46) * h)     # unknown sizes: sane default
    return (w - ax) // 2, cy - ay // 2


def _compose(art: Image.Image, size, caption: str | None) -> Image.Image:
    pos = _object_pos(size, art)
    base = _scene_base(size, caption, pos[1] + art.size[1])
    drop_off = (round(DROP_OFFSET_FRAC[0] * size[1]), round(DROP_OFFSET_FRAC[1] * size[1]))
    base.alpha_composite(_shadow_layer(size, art.getchannel("A"), pos, drop_off,
                                       DROP_SIGMA_FRAC * size[1], DROP_ALPHA,
                                       DROP_SPREAD_PX))
    base.alpha_composite(_shadow_layer(size, art.getchannel("A"), pos, CONTACT_OFFSET,
                                       CONTACT_SIGMA, CONTACT_ALPHA))
    base.alpha_composite(art, pos)
    return base.convert("RGB")


def _staged_art(frame: Image.Image, variant: str, size, sheen: bool) -> Image.Image:
    if variant == "plate":
        return make_plate_art(frame, round(PLATE_DIAM_FRAC * min(size)))
    if variant == "frame":
        return make_frame_art(frame, round(FRAME_MAX_W_FRAC * size[0]),
                              round(FRAME_MAX_H_FRAC * size[1]), sheen=sheen)
    raise MockupError(f"unknown variant {variant!r} — choose from {', '.join(VARIANTS)}")


def render_mockup(img: Image.Image, manifest, variant: str, size, *,
                  caption: bool = True, sheen: bool = True) -> Image.Image:
    """One still mockup: the final's pixels staged as a physical object on the wall."""
    text = caption_text(manifest) if caption else None
    return _compose(_staged_art(img, variant, size, sheen), tuple(size), text)


def write_jpeg(img: Image.Image, path: str) -> None:
    img.convert("RGB").save(path, "JPEG", quality=JPEG_QUALITY,
                            subsampling=JPEG_SUBSAMPLING, optimize=True)


# ---------------------------------------------------------------- video mode

def _yaw_quad(w: int, h: int, yaw_deg: float):
    """Destination corners for a subtle horizontal yaw: width forshortens by cos,
    left/right edge heights scale 1 -/+ PERSP_K*sin -- a trapezoid, enough at 2.5
    degrees to read as a turning object without ellipsing the disc."""
    s = math.sin(math.radians(yaw_deg))
    half = w * math.cos(math.radians(yaw_deg)) / 2.0
    cx, cy = w / 2.0, h / 2.0
    hl = h * (1 - PERSP_K * s) / 2.0                    # left edge half-height
    hr = h * (1 + PERSP_K * s) / 2.0                    # right edge half-height
    return [(cx - half, cy - hl), (cx + half, cy - hr),
            (cx + half, cy + hr), (cx - half, cy + hl)]


def _persp_coeffs(src, dst):
    """The 8 PERSPECTIVE coefficients mapping OUTPUT pixels back to SOURCE pixels
    (PIL's convention), solved from 4 point pairs."""
    a = []
    b = []
    for (sx, sy), (dx, dy) in zip(src, dst):
        a.append([dx, dy, 1, 0, 0, 0, -sx * dx, -sx * dy]); b.append(sx)
        a.append([0, 0, 0, dx, dy, 1, -sy * dx, -sy * dy]); b.append(sy)
    return np.linalg.solve(np.array(a, dtype=np.float64),
                           np.array(b, dtype=np.float64)).tolist()


def _warp(img: Image.Image, yaw_deg: float) -> Image.Image:
    w, h = img.size
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    return img.transform((w, h), Image.PERSPECTIVE,
                         _persp_coeffs(src, _yaw_quad(w, h, yaw_deg)),
                         resample=Image.BICUBIC)


def yaw_at_tick(tick: int) -> float:
    """Pure function of the tick index -- the whole of video determinism."""
    return YAW_MAX_DEG * math.sin(2 * math.pi * tick /
                                  round(YAW_PERIOD_S * VIDEO_FPS))


def render_mockup_video(frames, durations_ms, manifest, variant: str, size, *,
                        caption: bool = True, sheen: bool = True) -> bytes:
    """The motion mockup: journeys ink themselves (the film's own pacing) while the
    object yaws +/-YAW_MAX_DEG on a YAW_PERIOD_S sine. Staged art is built once per
    unique film frame (fixed light -- the warp and moving shadows sell the depth);
    per 25 fps tick the art AND its precomputed shadows warp with the same quad, so
    they can never disagree. A still input loops one full period, seamlessly."""
    from app import timelapse                       # lazy: pulls the render stack
    exe = timelapse.require_ffmpeg()
    if timelapse.MP4_BASE_FPS != VIDEO_FPS:         # one clock, never two
        raise MockupError("VIDEO_FPS drifted from timelapse.MP4_BASE_FPS")
    size = tuple(size)
    text = caption_text(manifest) if caption else None
    staged = [_staged_art(f, variant, size, sheen) for f in frames]
    pos = _object_pos(size, staged[0])
    drop_off = (round(DROP_OFFSET_FRAC[0] * size[1]), round(DROP_OFFSET_FRAC[1] * size[1]))
    # the canvas must hold the object AND its full drop shadow, or the warp clips the
    # shadow at the canvas edge (the 'hard crop' below the disc)
    pad = max(24, _shadow_reach(DROP_SIGMA_FRAC * size[1], DROP_SPREAD_PX, drop_off) + 12)
    canvas_sz = (staged[0].size[0] + 2 * pad, staged[0].size[1] + 2 * pad)
    opos = (pos[0] - pad, pos[1] - pad)

    def _padded(im):
        c = Image.new("RGBA", canvas_sz, (0, 0, 0, 0))
        c.alpha_composite(im, (pad, pad))
        return c

    arts = [_padded(a) for a in staged]
    alpha = arts[0].getchannel("A")                 # silhouette is journey-invariant
    drop = _shadow_layer(canvas_sz, alpha, (0, 0), drop_off,
                         DROP_SIGMA_FRAC * size[1], DROP_ALPHA, DROP_SPREAD_PX)
    contact = _shadow_layer(canvas_sz, alpha, (0, 0), CONTACT_OFFSET,
                            CONTACT_SIGMA, CONTACT_ALPHA)
    base = _scene_base(size, text, pos[1] + staged[0].size[1])

    if len(frames) == 1:
        ticks_per_frame = [round(LOOP_SECONDS * VIDEO_FPS)]
    else:
        tick_ms = 1000 // VIDEO_FPS
        ticks_per_frame = [max(1, round(d / tick_ms)) for d in durations_ms]

    def _ticks():
        tick = 0
        for art, n in zip(arts, ticks_per_frame):
            for _ in range(n):
                yaw = yaw_at_tick(tick)
                scene = base.copy()
                scene.alpha_composite(_warp(drop, yaw), opos)
                scene.alpha_composite(_warp(contact, yaw), opos)
                scene.alpha_composite(_warp(art, yaw), opos)
                yield scene.convert("RGB"), 1
                tick += 1

    return timelapse._mp4_stream(exe, size, _ticks())


def expected_video_ticks(n_frames: int, durations_ms) -> int:
    """The tick count render_mockup_video will emit -- exposed for tests."""
    if n_frames == 1:
        return round(LOOP_SECONDS * VIDEO_FPS)
    tick_ms = 1000 // VIDEO_FPS
    return sum(max(1, round(d / tick_ms)) for d in durations_ms)


# ---------------------------------------------------------------- depth-map sidecar

def write_depth_map(img: Image.Image, path: str) -> None:
    """A 16-bit grayscale height map of the final (the emboss height field, full
    frame) for manual Facebook RGB+depth "3D photo" experiments -- same aspect as the
    poster, deterministic."""
    art = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    h = _height_field(art)
    Image.fromarray((h * 65535.0 + 0.5).astype(np.uint16)).save(path, "PNG")


# ---------------------------------------------------------------- CLI

def _parse_sizes(s: str):
    out = []
    for part in s.split(","):
        w, _, h = part.strip().partition("x")
        out.append((int(w), int(h)))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("final", help="a Tecopa Plateworks final PNG (poster or film APNG)")
    ap.add_argument("-o", "--out", default=None, help="output dir (default: beside the input)")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--sizes", default=",".join(f"{w}x{h}" for w, h in SIZES))
    ap.add_argument("--no-caption", dest="caption", action="store_false")
    ap.add_argument("--no-sheen", dest="sheen", action="store_false")
    ap.add_argument("--video", action="store_true",
                    help="also emit the rotation-loop MP4 for a still input")
    ap.add_argument("--depth-map", action="store_true",
                    help="also emit a 16-bit height map PNG (FB 3D-photo experiments)")
    args = ap.parse_args(argv)
    try:
        frames, durations, manifest = load_final(args.final)
        out_dir = args.out or (os.path.dirname(os.path.abspath(args.final)) or ".")
        os.makedirs(out_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(args.final))[0]
        variants = [v.strip() for v in args.variants.split(",") if v.strip()]
        sizes = _parse_sizes(args.sizes)
        animated = len(frames) > 1
        made = []
        for variant in variants:
            for size in sizes:
                tag = f"{stem}_mockup_{variant}_{size[0]}x{size[1]}"
                if animated or args.video:
                    data = render_mockup_video(frames, durations, manifest, variant,
                                               size, caption=args.caption,
                                               sheen=args.sheen)
                    path = os.path.join(out_dir, tag + ".mp4")
                    with open(path, "wb") as f:
                        f.write(data)
                    made.append(path)
                if not animated:
                    path = os.path.join(out_dir, tag + ".jpg")
                    write_jpeg(render_mockup(frames[0], manifest, variant, size,
                                             caption=args.caption, sheen=args.sheen),
                               path)
                    made.append(path)
        if args.depth_map:
            path = os.path.join(out_dir, f"{stem}_depth.png")
            write_depth_map(frames[-1], path)
            made.append(path)
        for p in made:
            print(p)
        return 0
    except (MockupError, RuntimeError) as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
