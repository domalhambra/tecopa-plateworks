#!/usr/bin/env python3
"""The coin spin -- the plate as a social-feed film: a slow full turn under a spotlight.

Feeds can't embed the landing page's orbitable GLB, so this renders the SAME object
(scripts.render_model.plate_mesh -- identical vertices, identical emboss height field)
as a looping video: the plate faces the viewer, turns once about the vertical axis,
and a single soft key light pools on it so the mountains and valleys carry real depth.

A pure-numpy software rasterizer -- z-buffered, per-triangle, textured with the
final's own pixels -- so the marketing-honesty rule holds: every frame is the
engine's render restaged, never an artist's impression. Share-class like the mockup
MP4s: no manifest aboard. Deterministic: fixed mesh, fixed camera, fixed light,
no clock -- same input PNG, byte-identical frames.

Usage:
    ./.venv/bin/python scripts/render_coinspin.py assets/lassen_ca/poster.png
"""
from __future__ import annotations
import argparse
import io
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.render_mockups import PNG_MAGIC                              # noqa: E402
from scripts.render_model import DISC_RADIUS, DISC_THICKNESS, DISPLACE_MAX, \
    TEXTURE_PX, _centered_square, plate_mesh                              # noqa: E402
from app import timelapse                                                 # noqa: E402

COIN_FRAMES  = 48          # one full turn; override with TECOPA_COIN_FRAMES
COIN_PX      = 900         # square canvas (1080 social crops keep headroom)
COIN_STEP_MS = 90          # ~4.3 s per revolution -- "slowly rotating"
TILT_DEG     = -16.0       # top tips back a touch so the relief reads obliquely
FILL         = 0.74        # plate diameter as a fraction of the canvas

AMBIENT   = 0.30
KEY_DIR   = (-0.42, 0.52, 0.74)      # upper-left, in front -- the key light
SPEC_POW  = 42.0
SPEC_GAIN = 0.16
SPOT_XY   = (-0.06, -0.14)           # spotlight pool center, canvas fractions off-center
SPOT_R    = 0.62                     # pool radius, canvas fraction
SPOT_FLOOR = 0.52                    # light level far outside the pool
BG_RGB    = (17, 20, 13)             # the landing page's studio dark (--ground family)
BG_GLOW   = (16, 15, 10)             # additive pool glow behind the plate
BACK_RGB  = (46, 44, 38)             # the plate's plain back and rim faces


def _rx(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _background(px: int) -> np.ndarray:
    """The dark studio ground with the spotlight's pool glowing behind the plate."""
    yy, xx = np.mgrid[0:px, 0:px].astype(np.float64)
    cx = px * (0.5 + SPOT_XY[0]); cy = px * (0.5 + SPOT_XY[1])
    d2 = ((xx - cx) ** 2 + (yy - cy) ** 2) / (px * SPOT_R) ** 2
    glow = np.exp(-d2 * 1.6)[..., None]
    bg = np.asarray(BG_RGB, dtype=np.float64) + glow * np.asarray(BG_GLOW, dtype=np.float64)
    return bg


def _spot_gain(px: int) -> np.ndarray:
    """Screen-space spotlight attenuation: full strength in the pool, dimmer outside."""
    yy, xx = np.mgrid[0:px, 0:px].astype(np.float64)
    cx = px * (0.5 + SPOT_XY[0]); cy = px * (0.5 + SPOT_XY[1])
    d2 = ((xx - cx) ** 2 + (yy - cy) ** 2) / (px * SPOT_R) ** 2
    return SPOT_FLOOR + (1.0 - SPOT_FLOOR) * np.exp(-d2)


def render_coin_frames(img: Image.Image, n_frames: int = COIN_FRAMES,
                       px: int = COIN_PX) -> list:
    """One full turn of the plate, z-buffered and lit. Returns PIL RGB frames that
    loop seamlessly (frame n would equal frame 0)."""
    positions, normals, uvs, indices, top_count = plate_mesh(img)
    P0 = positions.astype(np.float64)
    P0[:, 2] -= (DISC_THICKNESS + DISPLACE_MAX) / 2.0        # spin about the mid-plane
    N0 = normals.astype(np.float64)
    UV = uvs.astype(np.float64)
    tris = indices.reshape(-1, 3).astype(np.int64)
    textured = np.arange(len(P0)) < top_count                # top face wears the map
    tex = np.asarray(_centered_square(img.convert("RGB"), TEXTURE_PX),
                     dtype=np.float64)

    scale = FILL * px / (2 * DISC_RADIUS)
    L = np.asarray(KEY_DIR, dtype=np.float64); L /= np.linalg.norm(L)
    H = L + np.array([0.0, 0.0, 1.0]); H /= np.linalg.norm(H)   # half vector (ortho view)
    bg = _background(px)
    spot = _spot_gain(px)
    tilt = _rx(np.deg2rad(TILT_DEG))

    frames = []
    for k in range(n_frames):
        theta = 2 * np.pi * k / n_frames
        M = tilt @ _ry(theta)
        P = P0 @ M.T
        N = N0 @ M.T
        sx = P[:, 0] * scale + px / 2.0
        sy = -P[:, 1] * scale + px / 2.0
        sz = P[:, 2] * scale

        canvas = bg.copy()
        zbuf = np.full((px, px), -np.inf)

        # cull triangles facing away (summed vertex normal points into the screen)
        vis = N[tris].sum(axis=1)[:, 2] > 0.0
        for i0, i1, i2 in tris[vis]:
            xs = np.array([sx[i0], sx[i1], sx[i2]])
            ys = np.array([sy[i0], sy[i1], sy[i2]])
            x0, x1 = int(np.floor(xs.min())), int(np.ceil(xs.max())) + 1
            y0, y1 = int(np.floor(ys.min())), int(np.ceil(ys.max())) + 1
            x0, y0 = max(x0, 0), max(y0, 0)
            x1, y1 = min(x1, px), min(y1, px)
            if x0 >= x1 or y0 >= y1:
                continue
            area = (xs[1] - xs[0]) * (ys[2] - ys[0]) - (xs[2] - xs[0]) * (ys[1] - ys[0])
            if abs(area) < 1e-9:
                continue
            gy, gx = np.mgrid[y0:y1, x0:x1]
            w0 = ((xs[1] - gx) * (ys[2] - gy) - (xs[2] - gx) * (ys[1] - gy)) / area
            w1 = ((xs[2] - gx) * (ys[0] - gy) - (xs[0] - gx) * (ys[2] - gy)) / area
            w2 = 1.0 - w0 - w1
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not inside.any():
                continue
            depth = w0 * sz[i0] + w1 * sz[i1] + w2 * sz[i2]
            zwin = zbuf[y0:y1, x0:x1]
            hit = inside & (depth > zwin)
            if not hit.any():
                continue
            n = (w0[..., None] * N[i0] + w1[..., None] * N[i1] + w2[..., None] * N[i2])
            n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-9)
            diff = np.clip(n @ L, 0.0, None)
            spec = np.clip(n @ H, 0.0, None) ** SPEC_POW * SPEC_GAIN
            if textured[i0]:
                u = w0 * UV[i0, 0] + w1 * UV[i1, 0] + w2 * UV[i2, 0]
                v = w0 * UV[i0, 1] + w1 * UV[i1, 1] + w2 * UV[i2, 1]
                ti = np.clip((u * (TEXTURE_PX - 1)).round().astype(np.int64), 0, TEXTURE_PX - 1)
                tj = np.clip((v * (TEXTURE_PX - 1)).round().astype(np.int64), 0, TEXTURE_PX - 1)
                base = tex[tj, ti]
            else:
                base = np.broadcast_to(np.asarray(BACK_RGB, dtype=np.float64),
                                       n.shape).copy()
            lit = base * (AMBIENT + (1.0 - AMBIENT) * diff)[..., None] + spec[..., None] * 255.0
            lit *= spot[y0:y1, x0:x1, None]
            patch = canvas[y0:y1, x0:x1]
            patch[hit] = lit[hit]
            zwin[hit] = depth[hit]

        frames.append(Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8), "RGB"))
    return frames


def coin_webp(img: Image.Image, n_frames: int = COIN_FRAMES, px: int = COIN_PX) -> bytes:
    """The always-available share twin: a seamlessly looping WebP of the turn."""
    frames = render_coin_frames(img, n_frames, px)
    return timelapse.encode_webp(frames, step_ms=COIN_STEP_MS,
                                 hold_ms=COIN_STEP_MS, leader_ms=COIN_STEP_MS)


def coin_mp4(img: Image.Image, n_frames: int = COIN_FRAMES, px: int = COIN_PX) -> bytes:
    """The MP4 twin for feeds that transcode WebP badly. Needs the share extra."""
    frames = render_coin_frames(img, n_frames, px)
    return timelapse.encode_mp4(frames, step_ms=COIN_STEP_MS,
                                hold_ms=COIN_STEP_MS, leader_ms=COIN_STEP_MS)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("final", help="a Tecopa Plateworks final PNG")
    ap.add_argument("-o", "--out", default=None, help="output .webp (default beside input)")
    ap.add_argument("--frames", type=int,
                    default=int(os.environ.get("TECOPA_COIN_FRAMES", COIN_FRAMES)))
    ap.add_argument("--px", type=int, default=COIN_PX)
    args = ap.parse_args(argv)
    with open(args.final, "rb") as f:
        data = f.read()
    if not data.startswith(PNG_MAGIC):
        print(f"not a PNG: {os.path.basename(args.final)}", file=sys.stderr)
        return 2
    img = Image.open(io.BytesIO(data)).convert("RGB")
    out = args.out or os.path.join(
        os.path.dirname(os.path.abspath(args.final)) or ".",
        os.path.splitext(os.path.basename(args.final))[0] + "_coin.webp")
    with open(out, "wb") as f:
        f.write(coin_webp(img, args.frames, args.px))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
