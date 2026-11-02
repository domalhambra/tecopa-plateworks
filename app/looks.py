# app/looks.py
"""The relief extension seam's first shipped module: the two depth-pass techniques
exposed as deliberate spec knobs (v1.13, approved by Dom 2026-08-10).

soft_light -- the USGS MDOW multi-directional blend `multidirectional_hillshade`
already implements, reachable today only through the scale-keyed depth ramp (zero at
county scale, where most posters live). The pass applies it as an exact multiplicative
correction on the "light" plane: light = f(hs)*S where f(h) = SHADOW_FLOOR +
(1-SHADOW_FLOOR)*h and S is the (multiplicative) valley/cast/AO factor, so swapping
hs for the blend is exactly light *= f(hs_new)/f(hs_cur). The knob COMPOSES with any
weight the depth ramp already blended (w = 1-(1-w_depth)(1-knob)) so corridor-scale
sheets never double-apply. The one approximation: the core clamps to CAST_LIGHT_FLOOR
before this stage runs, so pixels sitting exactly at the floor take the correction
from the clamped value; the pass re-clamps after, and the deviation is bounded,
deterministic, and dark-end only.

haze_strength -- the Imhof aerial perspective `_depth_atmosphere` already applies at
corridor scale, as a deliberate knob at any scale: low ground sinks toward the cool
HAZE colour by HAZE_KNOB_MAX * knob * (1-norm)**HAZE_GAMMA, stacking additively with
the depth pass's own AERIAL term when both run.

Both passes are gated `enabled` on knob > 0 -- a zero knob never runs, so the
shipped-registry state is a strict no-op at the spec defaults and every pre-feature
manifest renders byte-identically (tests/test_looks.py holds this line).

viewshed -- the wash (docs/superpowers/specs/2026-11-01-viewshed-wash-design.md,
decisions 7 and 8): ground the poster's marks cannot see loses colour and falls in value,
and seen ground stays exactly as it is. `render` reads the plate and hands over a
`SeenField` in `frame.extras["seen"]`, its mask on a coarse grid of the plate (rule 4 of
docs/relief-passes.md); this pass only samples it, a band at a time, by ground position.
So the pass cannot change with the dpi. With no field there is no pass: no mark on the
plate means nothing to say, not that nothing is seen (tests/test_viewshed_render.py)."""
from __future__ import annotations
import numpy as np

from . import relief
from .relief import (CAST_LIGHT_FLOOR, HAZE, HILLSHADE_GAMMA, MULTIDIR_MAX,
                     SHADOW_FLOOR, register_relief_pass, shade_from)
from .render import relief_extra

HAZE_KNOB_MAX = 0.30      # haze on the lowest ground at knob 1.0 (deliberate, so it
                          # reaches past the depth ramp's automatic 0.18)
HAZE_GAMMA = 1.5          # the depth pass's own falloff curve, kept identical
SEEN_VALUE_FALL = 0.128   # unseen ground at knob 1.0. Decision 7's limit is 15% on the
                          # print; the tonal curve after this stage steepens midtones
                          # by up to 1.17 times, so 12.8% here is at most 15% there.
SEEN_CHROMA_FALL = 0.50   # the share of its colour unseen ground gives up at knob 1.0
SEEN_LUMA = np.array([0.299, 0.587, 0.114], np.float32)   # Rec. 601, as _tonal_finish


@relief_extra("soft_light")
def _soft_light_knob(spec):
    return spec.soft_light


@relief_extra("haze")
def _haze_knob(spec):
    return spec.haze_strength


@relief_extra("viewshed")
def _viewshed_knob(spec):
    return spec.viewshed


def _soft_light(light, frame):
    k = float(np.clip(frame.extras.get("soft_light", 0.0), 0.0, 1.0))
    slope, aspect = frame.terrain()                 # shared -- never re-gradient
    d = float(np.clip(frame.depth, 0.0, 1.5))
    w_cur = MULTIDIR_MAX * min(d, 1.0)              # what the core already blended
    w_new = 1.0 - (1.0 - w_cur) * (1.0 - k)         # compose, never subtract
    if w_new <= w_cur:
        return light
    # Every plane below is a full render window -- 155 MB apiece on an 18x24 at 300 dpi
    # -- and this pass is default-on (0.35) for new posters, so it composites in place
    # like the rest of the engine. The naive form
    #     f_cur = hs1 * (1 - w_cur) + hsm * w_cur      # 3 transient planes
    #     f_new = hs1 * (1 - w_new) + hsm * w_new      # 3 more, with hs1/hsm still live
    # peaked at six; consuming hs1/hsm for f_new (they are ours, and dead after it)
    # holds it to four. Every IEEE operation and its order is unchanged -- a*x + b*y
    # computed into a's buffer is the same addition of the same two products -- so the
    # correction stays float-for-float the blend the core would have built itself
    # (test_soft_light_full_knob_matches_the_core_blend holds that line).
    hs1 = shade_from(slope, aspect, frame.azimuth, frame.altitude)
    np.power(hs1, HILLSHADE_GAMMA, out=hs1)         # ours since shade_from clipped
    hsm = relief.multidirectional_hillshade(
        frame.elev, frame.res_m, frame.azimuth, frame.altitude, frame.z_factor,
        terrain=(slope, aspect))
    np.power(hsm, HILLSHADE_GAMMA, out=hsm)
    # f_cur: the light the core actually built, from a scratch buffer + one temporary
    f_cur = hs1 * (1.0 - w_cur)
    tmp = hsm * w_cur
    f_cur += tmp
    del tmp
    f_cur *= (1.0 - SHADOW_FLOOR)
    f_cur += SHADOW_FLOOR
    # f_new: the same construction, consuming hs1 and hsm rather than reading them
    hs1 *= (1.0 - w_new)
    hsm *= w_new
    hs1 += hsm
    del hsm
    f_new = hs1
    f_new *= (1.0 - SHADOW_FLOOR)
    f_new += SHADOW_FLOOR
    f_new /= f_cur                                  # the exact correction, in place
    del f_cur
    light *= f_new
    if frame.shadow > 0:                            # restore the core's floor clamp
        np.maximum(light, CAST_LIGHT_FLOOR, out=light)
    return light


def _haze(img, frame):
    k = float(np.clip(frame.extras.get("haze", 0.0), 0.0, 1.0))
    w = (HAZE_KNOB_MAX * k
         * np.clip(1.0 - frame.norm, 0.0, 1.0) ** HAZE_GAMMA)[..., None]
    haze_rgb = np.array(HAZE, np.float32)[None, None, :] / 255.0
    img *= (1.0 - w)
    img += haze_rgb * w
    return img


def _viewshed(img, frame):
    """Quiet the ground the marks cannot see. Each row of the sheet reads two rows of the
    coarse mask and each column two of its columns, by the pixel's ground position, so
    a band's temporaries are band-sized and no full-sheet plane is built. Both blends are
    written so a cell that says "seen" adds exactly nothing, and seen ground keeps its
    bytes."""
    k = float(np.clip(frame.extras.get("viewshed", 0.0), 0.0, 1.0))
    field = frame.extras["seen"]
    mask, t = field.mask, field.transform
    grid_h, grid_w = mask.shape
    left, bottom, right, top = field.bounds
    h, w = img.shape[:2]
    x = left + (np.arange(w) + 0.5) * ((right - left) / w)
    col = np.clip((x - t.c) / t.a - 0.5, 0.0, grid_w - 1.0)
    col0 = col.astype(np.int32)
    col1 = np.minimum(col0 + 1, grid_w - 1)
    across = (col - col0).astype(np.float32)
    y = top - (np.arange(h) + 0.5) * ((top - bottom) / h)
    row = np.clip((y - t.f) / t.e - 0.5, 0.0, grid_h - 1.0)
    row0 = row.astype(np.int32)
    row1 = np.minimum(row0 + 1, grid_h - 1)
    down = (row - row0).astype(np.float32)
    for rows in relief._bands(h):
        near = mask[row0[rows]]
        strip = near + (mask[row1[rows]] - near) * down[rows][:, None]
        near = strip[:, col0]
        seen = near + (strip[:, col1] - near) * across
        quiet = k * (1.0 - seen)
        ib = img[rows]
        lum = (ib * SEEN_LUMA).sum(axis=2, keepdims=True)
        ib += (lum - ib) * (SEEN_CHROMA_FALL * quiet)[..., None]
        ib *= (1.0 - SEEN_VALUE_FALL * quiet)[..., None]
    return img


def register():
    """Idempotent (register replaces by name): the import-time call below sets the
    shipped state; tests that empty the registry call this to restore it."""
    register_relief_pass("light", "soft-light", _soft_light,
                         enabled=lambda f: f.extras.get("soft_light", 0.0) > 0)
    register_relief_pass("finish", "haze", _haze,
                         enabled=lambda f: f.extras.get("haze", 0.0) > 0)
    register_relief_pass("finish", "viewshed", _viewshed,
                         enabled=lambda f: (f.extras.get("viewshed", 0.0) > 0
                                            and f.extras.get("seen") is not None))


register()
