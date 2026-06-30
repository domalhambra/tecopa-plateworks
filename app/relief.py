# app/relief.py
from __future__ import annotations
import numpy as np
from scipy.ndimage import gaussian_filter

# ---- tuning surface: edit these by eye against the reference maps ----
HYPSO_STOPS = [
    # (normalized_elevation 0..1, (r, g, b))  -- earthy, basin-to-peak
    (0.00, (171, 168, 140)),   # low salt/sage
    (0.25, (142, 150, 110)),   # green valley
    (0.50, (150, 134,  96)),   # tan slope
    (0.75, (120,  98,  74)),   # brown ridge
    (1.00, (236, 232, 220)),   # high near-white
]
TEXTURE_STRENGTH = 0.35        # ridge crispness (high-pass blend)
TEXTURE_RADIUS_PX = 6
VALLEY_STRENGTH = 0.30         # soft darkening in deep valleys
VALLEY_RADIUS_PX = 40
# TODO (Phase 5 / render.py wiring): these blur radii are in PIXELS, so the same
# spec yields a different relative texture/valley scale at proof (96 dpi) vs final
# (300 dpi) -- a soft break of "one spec, painted at many sizes". When render.py
# paints a spec at two DPIs, derive these from a physical length (ground metres /
# res_m, or print inches * dpi) passed in at paint time, the way grain_cell_in does.
HILLSHADE_GAMMA = 1.1          # contrast of the light
# ---------------------------------------------------------------------

def _fill_nan(elev):
    if not np.isnan(elev).any():
        return elev
    m = np.nanmean(elev)
    return np.where(np.isnan(elev), m, elev)

def hillshade(elev, res_m, azimuth=315, altitude=45, z_factor=1.0):
    # `aspect` below (arctan2(-dx, dy)) is the compass bearing of the downhill
    # direction (0=N, 90=E, 180=S, 270=W), so the light bearing must be the sun
    # azimuth in the same frame. The plain `radians(azimuth)` lights each slope
    # from the requested direction; `radians(360 - azimuth + 90)` would rotate the
    # light 90 deg off (an east-facing slope brightest under a north sun).
    az = np.radians(azimuth)
    alt = np.radians(altitude)
    dy, dx = np.gradient(elev * z_factor, res_m)
    slope = np.pi/2 - np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)
    shaded = (np.sin(alt) * np.sin(slope)
              + np.cos(alt) * np.cos(slope) * np.cos(az - aspect))
    return np.clip(shaded, 0, 1)

def hypsometric(elev, elev_min, elev_max):
    norm = np.clip((elev - elev_min) / (elev_max - elev_min + 1e-9), 0, 1)
    stops = HYPSO_STOPS
    xs = np.array([s[0] for s in stops])
    rgb = np.zeros(elev.shape + (3,), dtype="float32")
    for ch in range(3):
        ys = np.array([s[1][ch] for s in stops], dtype="float32")
        rgb[..., ch] = np.interp(norm, xs, ys)
    return rgb / 255.0

def texture_pass(elev):
    # high-pass: sharpen ridges and drainages (a cheap stand-in for true texture shading)
    blur = gaussian_filter(elev, TEXTURE_RADIUS_PX)
    hp = elev - blur
    s = np.std(hp) + 1e-9
    return np.clip(0.5 + (hp / (4 * s)), 0, 1)   # 0..1, centered

def valley_pass(elev):
    # darken places that sit well below their surroundings
    big = gaussian_filter(elev, VALLEY_RADIUS_PX)
    depth = np.clip(big - elev, 0, None)
    s = np.percentile(depth, 99) + 1e-9
    return np.clip(depth / s, 0, 1)              # 0..1, 1 = deep valley

def grain(shape, cell_px, strength, seed):
    rng = np.random.default_rng(seed)
    h, w = shape
    small = rng.standard_normal((max(1, round(h / cell_px)),
                                 max(1, round(w / cell_px)))).astype("float32")
    # nearest-neighbor upscale to a paper-grain cell size
    ys = (np.linspace(0, small.shape[0] - 1, h)).astype(int)
    xs = (np.linspace(0, small.shape[1] - 1, w)).astype(int)
    g = small[np.ix_(ys, xs)]
    return 1.0 + strength * np.clip(g, -3, 3) / 3.0

def shaded_relief(elev, res_m, elev_min, elev_max,
                  azimuth=315, altitude=45, z_factor=1.0, seed=7,
                  grain_cell_px=2.0, grain_strength=0.05):
    elev = _fill_nan(elev.astype("float32"))
    base = hypsometric(elev, elev_min, elev_max)                  # color
    hs = hillshade(elev, res_m, azimuth, altitude, z_factor) ** HILLSHADE_GAMMA
    tex = texture_pass(elev)
    val = valley_pass(elev)

    light = (0.45 + 0.55 * hs)                                    # never fully black
    light = light * (1.0 - VALLEY_STRENGTH * val)                # sink the valleys
    light = light[..., None]

    img = base * light
    # blend texture as a soft dodge/burn around mid-gray
    img = img * (1.0 + TEXTURE_STRENGTH * (tex[..., None] - 0.5))
    img = img * grain(elev.shape, grain_cell_px, grain_strength, seed)[..., None]
    return (np.clip(img, 0, 1) * 255).astype("uint8")
