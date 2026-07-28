# app/relief.py
from __future__ import annotations
from dataclasses import dataclass, field
import math as _m
import numpy as np
from scipy.ndimage import gaussian_filter, distance_transform_edt, rotate, zoom

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
VALLEY_STRENGTH = 0.30         # soft darkening in deep valleys
HILLSHADE_GAMMA = 1.1          # contrast of the light
# Tonal range + finish (the "punch" pass). The old relief floored every shaded slope
# at 0.45 brightness -- a compressed mid-tone band that reads muddy, especially on a
# mountain sheet where the whole story is light vs. shadow. SHADOW_FLOOR deepens the
# darkest slope; the finishing curve + saturation are the cartographer's "levels +
# curves + vibrance" (Tom Patterson's relief workflow, Swiss-style), applied per pixel
# so they're DPI-invariant (proof == final, invariant 1).
SHADOW_FLOOR = 0.26            # light kept on the deepest-shaded slope (was 0.45)
RELIEF_CONTRAST = 0.30        # S-curve strength around mid; 0 = linear, 1 = full smoothstep
RELIEF_SATURATION = 1.20      # mid-tone chroma lift -- pulls the muddy olive/tan apart
# Figure-ground (V1-10, approved by Dom): lift the terrain slightly toward paper so
# the route/markers own the contrast budget -- the terrain stays the beauty, the
# journey becomes the subject. Applied after the stop interpolation in hypsometric()
# (equivalent to lifting every stop, but keeps the by-eye stop values intact above).
PAPER = (243, 237, 223)
PAPER_LIFT = 0.06
# Biome tint (v1.2, Dom): hue from NLCD land cover, lightness from elevation + shade
# (Imhof's naturalistic method), so forests read green and high desert reads sage-tan
# while the relief keeps its full tonal punch. The alpine fade returns the summits to
# the pure hypsometric near-white above ~70% of the region's elevation range.
BIOME_MIX = 0.55               # tint weight where land cover is known
ALPINE_FADE_START = 0.70       # normalized elevation where the tint starts fading
ALPINE_FADE_END = 0.88         # fully hypsometric above this
# curated NLCD class palette -- muted, earthy, sits with the paper-lift + gold track
BIOME_TINT = {
    41: (110, 125, 82),   # deciduous forest - soft leaf green
    42: (86, 106, 74),    # evergreen forest - deep sage
    43: (100, 116, 78),   # mixed forest
    52: (156, 143, 100),  # shrub/scrub - warm sage-tan (the high desert)
    71: (163, 158, 112),  # grassland - pale olive
    31: (190, 178, 148),  # barren - bone/sand
    81: (146, 152, 100),  # pasture/hay
    82: (140, 148, 96),   # cultivated crops
    90: (104, 122, 104),  # woody wetlands - slate green
    95: (112, 128, 108),  # herbaceous wetlands
    12: (232, 230, 222),  # perennial snow/ice
    21: (168, 156, 138),  # developed, open space -> warm grays
    22: (164, 150, 132),
    23: (158, 144, 126),
    24: (152, 138, 120),
}
# Blur radii are tied to a GROUND distance (metres), converted to pixels at paint
# time via res_m -- so the same crop yields the same relief at any DPI ("one spec,
# painted at many sizes"). render.py passes ground/res_m; the px fallbacks below
# are only for direct/synthetic callers that have no real ground resolution.
TEXTURE_RADIUS_M = 60.0         # ridge high-pass scale, ground metres
VALLEY_RADIUS_M = 400.0         # valley darkening scale, ground metres
TEXTURE_RADIUS_PX = 6          # fallback when no physical radius is supplied
VALLEY_RADIUS_PX = 40

# ---- terrain depth (v1.3, Dom): keep small-scale maps sculptural and give the flats
# life. Auto-keyed to MAP SCALE in render.py: `depth` is 0 at county scale (where the
# single-light look is already right and every existing test renders) and ramps to 1
# at corridor scale, where mountains shrink and basins go lifeless. Three industry
# moves -- multidirectional light (USGS MDOW / Esri), multiscale texture shading
# (Leland Brown / Tom Patterson), and aerial perspective (Imhof) -- plus a salt-pan
# treatment so playa reads as luminous salt rather than a beige void. Every blur,
# octave, and mottle below is sized in GROUND units, so proof == final (invariant 1).
HAZE = (176, 190, 206)          # COOL bluish atmosphere the low ground recedes into --
                                # warm sunlit peaks vs. cool distant valleys is the
                                # Imhof aerial-perspective punch (was a flat light grey
                                # that only muted the sheet)
SALT = (240, 236, 228)          # luminous warm-white for playa / salt flats
MULTIDIR_MAX = 0.55             # multidirectional light blended in at full depth
TEXTURE_DEPTH_MAX = 0.85        # extra multiscale-texture contrast at full depth
AERIAL_MAX = 0.18               # haze on the lowest ground at full depth (was 0.26 -- a
                                # lighter grey wash that flattened the mountain valleys)
SALT_MAX = 0.55                 # luminous lift on the flattest, lowest ground
SALT_LOW_NORM = 0.16            # 'low ground' = below this fraction of the elev range
MOTTLE_CELL_M = 240.0           # salt-mottle cell, ground metres (dpi-stable grid)
MOTTLE_STRENGTH = 0.06

# ---- cast shadows + sky occlusion (the "Blender relief" look, Dom): terrain
# occlusion along the sun direction -- a peak actually shades the valley beside it --
# plus a multi-scale sky-openness term, after Tom Patterson's Blender relief workflow.
# All lighting above is local-slope only; this is the pass that makes the sheet read
# three-dimensional. Shadows are COOL (blue skylight fills them -- Imhof) and never
# black. Every length is in GROUND METRES; render.py additionally pins the working
# grid to a spec-derived ground resolution so the proof and the final ray-march the
# same terrain (invariant 1). Gated on `shadow` (0 = strict no-op, the pre-shadow
# look) exactly like the depth pass.
SHADOW_RAMP_M = 40.0            # metres below the sun horizon -> full shadow
PENUMBRA_M = 120.0              # soft-shadow edge width, ground metres
SHADOW_PRESMOOTH_FRAC = 0.6     # pre-smooth sigma as a fraction of the working res
CAST_DARKEN = 0.45              # light removed in full shadow at knob 1.0
CAST_LIGHT_FLOOR = 0.12         # absolute floor: shadows stay luminous, never black
CAST_TINT = (0.86, 0.94, 1.10)  # per-channel skylight multiplier (cool blue fill)
CAST_TINT_MAX = 0.65            # how far full shadow moves toward the cool tint
AO_RADII_M = (200.0, 800.0, 3200.0)   # sky-occlusion neighbourhood scales
AO_WEIGHTS = (0.5, 0.3, 0.2)
AO_SLOPE = 0.15                 # horizon slope that counts as fully occluded
AO_MAX = 0.22                   # light removed in the deepest concavity at knob 1.0
# Journey Light (v1.9): the golden-hour split-tone. Sunlit faces (a hillshade from the
# journey sun, minus what the ray-marched cast shadow occludes) warm toward gold in the
# TRACK_INK family; shadowed / occluded ground cools toward a blue-violet that extends
# the CAST_TINT skylight. Per-channel multipliers (>1 warms, <1 cools), applied at 0..MAX
# weight scaled by the golden knob. Strict no-op when golden=0 or no journey sun is set.
GOLDEN_WARM = (1.14, 1.02, 0.82)   # sunlit -> warm gold
GOLDEN_COOL = (0.88, 0.94, 1.12)   # shadow -> cool blue-violet
GOLDEN_WARM_MAX = 0.50             # max warm weight at golden=1
GOLDEN_COOL_MAX = 0.45             # max cool weight at golden=1
GOLDEN_LIT_GAMMA = 1.4             # concentrate the warmth on the well-lit faces
# ---------------------------------------------------------------------
# ---- the extension seam: where the NEXT relief technique plugs in ----
#
# Every technique added so far (terrain depth, cast shadows + sky occlusion, Journey
# Light) arrived the same way: three or four new parameters on `shaded_relief`, a new
# `if knob > 0:` block wired into the middle of the composition chain, and a matching
# edit in `render._paint_base`. That works, but it means each new module edits the one
# function every existing poster's pixels come out of -- exactly the code the
# forever-contract says to leave alone.
#
# A pass registers instead. It receives a `ReliefFrame` carrying the terrain and every
# expensive intermediate the core already computed (slope/aspect, the texture and
# valley fields, the ray-marched cast shadow and sky-occlusion masks), so a new
# technique never re-derives a gradient or re-marches a shadow. Stages, in composition
# order:
#
#   "color"  (base RGB 0..1)   after the hypsometric ramp + biome tint, before light
#   "light"  (scalar plane)    after hillshade/valley/cast/AO, before it meets colour
#   "finish" (RGB 0..1)        after texture + atmosphere, before the tonal curve
#   "grade"  (RGB 0..1)        after the tonal curve, before the paper grain
#
# A pass is `fn(array, frame) -> array` and MAY write its argument in place. It runs
# only when its `enabled(frame)` predicate is true, and its knob rides `frame.extras`
# (see `render.relief_extra`), so nothing here needs a new parameter. The registry is
# EMPTY by default and an empty stage is a strict no-op -- the forever-contract's
# additive-default rule, applied to the extension mechanism itself.
#
# Adding a module is then: a spec field (omitted from the manifest at its pre-feature
# default), one `@relief_extra` reader, one `register_relief_pass` call. Nothing in
# this file's composition chain changes, so no shipped poster can move.
# See docs/relief-passes.md for a worked example.

RELIEF_STAGES = ("color", "light", "finish", "grade")
_RELIEF_PASSES = {stage: [] for stage in RELIEF_STAGES}

@dataclass
class ReliefFrame:
    """What a registered pass sees: the terrain, the knobs, and the intermediates the
    core already paid for. Fields are populated as the chain reaches them, so a pass
    only reads what its stage documents (`cast`/`ao` are None unless the shadow pass
    ran; `tex`/`val` are None at the "color" stage)."""
    elev: np.ndarray                 # NaN-repaired float32 elevation, padded window
    res_m: float                     # ground metres per pixel -- size everything in
    norm: np.ndarray                 # 0..1 elevation over the plate's range         [these]
    elev_min: float
    elev_max: float
    seed: int                        # any RNG a pass uses MUST derive from this
    azimuth: float                   # the plate's archival light
    altitude: float
    z_factor: float
    depth: float = 0.0               # the resolved scale-keyed terrain-depth strength
    shadow: float = 0.0
    golden: float = 0.0
    sun_azimuth: float | None = None  # the journey sun, when one is set
    sun_altitude: float | None = None
    extras: dict = field(default_factory=dict)   # module knobs (render.relief_extra)
    tex: np.ndarray | None = None    # the texture high-pass, 0..1
    val: np.ndarray | None = None    # the valley-depth field, 0..1
    cast: np.ndarray | None = None   # ray-marched cast shadow, 0 = lit
    ao: np.ndarray | None = None     # multi-scale sky occlusion, 0 = open
    _terrain: tuple | None = None

    def terrain(self):
        """(slope, aspect) for this frame, computed once and shared. A pass wanting
        its own light should use this rather than a fresh gradient pass."""
        if self._terrain is None:
            self._terrain = slope_aspect(self.elev, self.res_m, self.z_factor)
        return self._terrain

    def light_from(self, azimuth, altitude):
        """A hillshade of this frame's terrain from any bearing, on the shared
        slope/aspect field."""
        return shade_from(*self.terrain(), azimuth, altitude)

    def px(self, metres):
        """`metres` of GROUND as a pixel count on this frame's grid. Every length a
        pass uses must go through here, or it will change with the render dpi and
        break "one spec, painted at many sizes" (invariant 1/2)."""
        return metres / self.res_m


def register_relief_pass(stage, name, fn, enabled=None):
    """Register `fn(array, frame) -> array` at `stage`. `enabled(frame) -> bool`
    decides per render (default: always). Re-registering a name replaces it, so a
    module can be reloaded without stacking duplicates."""
    if stage not in _RELIEF_PASSES:
        raise ValueError(f"stage must be one of {RELIEF_STAGES}")
    passes = _RELIEF_PASSES[stage]
    for i, (existing, _, _) in enumerate(passes):
        if existing == name:
            passes[i] = (name, fn, enabled)
            return
    passes.append((name, fn, enabled))

def unregister_relief_pass(stage, name):
    """Drop a registered pass (used by tests to restore the empty default)."""
    _RELIEF_PASSES[stage] = [p for p in _RELIEF_PASSES[stage] if p[0] != name]

def registered_relief_passes(stage=None):
    """The registry, for introspection/tests. Empty is the shipped state."""
    if stage is None:
        return {s: [p[0] for p in v] for s, v in _RELIEF_PASSES.items()}
    return [p[0] for p in _RELIEF_PASSES[stage]]

def _run_stage(stage, arr, frame):
    """Apply the registered passes for `stage` in registration order. With an empty
    registry -- the shipped state -- this returns `arr` untouched, so the composition
    chain is byte-for-byte what it was before the seam existed."""
    for _name, fn, enabled in _RELIEF_PASSES[stage]:
        if enabled is None or enabled(frame):
            arr = fn(arr, frame)
    return arr

# ---------------------------------------------------------------------

def _fill_nan(elev):
    """Repair stray nodata pixels from the NEAREST finite neighbour -- NOT the crop
    mean, which invents a smooth plateau at the average elevation under any real
    tracks crossing it (red-team V1-1). render.py's off-DEM guard already refuses a
    crop with more than a sliver of nodata, so this only ever patches a few interior
    holes; nearest-neighbour keeps them locally honest instead of globally averaged."""
    mask = np.isnan(elev)
    if not mask.any():
        return elev
    if mask.all():
        return np.zeros_like(elev)   # crop entirely off the DEM: flat fallback, no crash
    idx = distance_transform_edt(mask, return_distances=False, return_indices=True)
    return elev[tuple(idx)]

def slope_aspect(elev, res_m, z_factor=1.0):
    """(slope, aspect) in radians -- the terrain half of a hillshade, which depends
    only on the GROUND, never on the light. Hoisted out of `hillshade` so a caller
    lighting the same terrain several times (the multidirectional blend, the Journey
    Light sun beside the archival one) pays for one gradient pass instead of N. The
    expressions are lifted verbatim, so every light computed from these is bit-
    identical to the pre-hoist single-shot version."""
    dy, dx = np.gradient(elev * z_factor, res_m)
    slope = np.pi/2 - np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)
    return slope, aspect

def shade_from(slope, aspect, azimuth=315, altitude=45):
    """One light on a precomputed (slope, aspect) field. See `hillshade` for why the
    azimuth enters the aspect frame unrotated.

    rev 1 keeps the shipped arithmetic verbatim, including its accident: `np.radians`
    returns a float64 SCALAR, which is strong under NEP 50, so shading float32 terrain
    produced a float64 plane -- and since that plane multiplies the base colour, the
    entire RGB composition downstream ran at double width for no precision anyone
    asked for. rev 2 converts the same angles to Python floats, which are weak, so the
    result keeps the terrain's own float32 (see RELIEF_REVS). The formula is
    character-for-character the same; only the scalar type differs."""
    az = float(np.radians(azimuth))
    alt = float(np.radians(altitude))
    shaded = (_m.sin(alt) * np.sin(slope)
              + _m.cos(alt) * np.cos(slope) * np.cos(az - aspect))
    return np.clip(shaded, 0, 1)

# ---- wide-kernel blurs (rev 2) ----------------------------------------------------
# scipy's gaussian_filter is separable but still O(sigma) taps per pixel per axis, and
# the relief leans on genuinely wide kernels: sky occlusion reaches 3200 GROUND metres,
# the valley pass 400, the multiscale texture up to 8x its base radius. On a flagship
# final those are hundreds of pixels wide and the blurs became the single largest cost
# in the engine (~11 s of a 24 s sheet, measured).
#
# A wide Gaussian is a low-pass, so it carries almost no information at the sampling
# rate it is being computed at -- the standard answer, in every renderer that does
# this, is to decimate, blur small, and resample back. That is what rev 2 does above a
# threshold. It is an APPROXIMATION of the exact kernel (hence the rev gate), but the
# error is confined to spatial frequencies the blur is discarding anyway.
#
# Why this is safe for "one spec, painted at many sizes" (invariant 1): every sigma
# here is a GROUND distance divided by the grid's resolution, so sigma_px scales as
# 1/res_m, and the decimation factor k = sigma_px / BLUR_PYRAMID_SIGMA_PX scales the
# same way. The decimated grid's resolution is therefore
#
#     res_m * k  =  radius_m / BLUR_PYRAMID_SIGMA_PX
#
# -- a CONSTANT ground resolution, independent of the render dpi. The proof and the
# final blur the same ground grid and only differ in the resample back, exactly like
# the cast-shadow working grid (render._shadow_res_m). A threshold in raw pixels would
# have made the final take the pyramid while the proof did not, and the preview would
# have stopped predicting the print.
BLUR_PYRAMID_SIGMA_PX = 16.0    # blurs wider than this run decimated

def _blur(a, sigma_px):
    """gaussian_filter, or its pyramid approximation for a wide kernel."""
    if sigma_px <= BLUR_PYRAMID_SIGMA_PX:
        return gaussian_filter(a, sigma_px)
    k = sigma_px / BLUR_PYRAMID_SIGMA_PX                  # decimation factor > 1
    small = zoom(a, 1.0 / k, order=1)
    if min(small.shape) < 2:                              # degenerate: blur in place
        return gaussian_filter(a, sigma_px)
    small = gaussian_filter(small, BLUR_PYRAMID_SIGMA_PX)
    return _resize_to(small, a.shape).astype(a.dtype, copy=False)

def hillshade(elev, res_m, azimuth=315, altitude=45, z_factor=1.0, terrain=None):
    # `aspect` below (arctan2(-dx, dy)) is the compass bearing of the downhill
    # direction (0=N, 90=E, 180=S, 270=W), so the light bearing must be the sun
    # azimuth in the same frame. The plain `radians(azimuth)` lights each slope
    # from the requested direction; `radians(360 - azimuth + 90)` would rotate the
    # light 90 deg off (an east-facing slope brightest under a north sun).
    # `terrain` is an already-computed slope_aspect() pair for this elev/res_m/
    # z_factor -- an optimization only; None recomputes it and is exactly equivalent.
    slope, aspect = slope_aspect(elev, res_m, z_factor) if terrain is None else terrain
    return shade_from(slope, aspect, azimuth, altitude)

def multidirectional_hillshade(elev, res_m, azimuth=315, altitude=45, z_factor=1.0,
                               terrain=None):
    """A weighted blend of hillshades from several light bearings around the principal
    azimuth (USGS MDOW / Esri's terrain default). One light leaves ranges that run
    parallel to it unmodelled -- they vanish when the map is zoomed far out; the
    flanking lights recover them, while the principal light stays dominant so the
    sheet keeps a single, compass-consistent sun direction. The five lights share ONE
    slope/aspect pass (see slope_aspect) -- bit-identical, five times less gradient."""
    offsets = ((0.0, 1.0), (-45.0, 0.5), (45.0, 0.5), (-90.0, 0.25), (90.0, 0.25))
    if terrain is None:
        terrain = slope_aspect(elev, res_m, z_factor)
    acc = np.zeros_like(elev, dtype="float32")
    wsum = 0.0
    for off, wt in offsets:
        acc += wt * shade_from(terrain[0], terrain[1], azimuth + off, altitude)
        wsum += wt
    return acc / wsum

def multiscale_texture(elev, base_radius_px):
    """Texture shading (Leland Brown / Tom Patterson): a single fine high-pass loses
    the major ridge/drainage structure when the map is zoomed out. Summing high-pass
    responses across octaves (2x/4x/8x the base radius) keeps that structure crisp at
    any scale -- the drainage 'grain' of the range is what still reads as mountains
    when each summit is only a few pixels. Ground-radius-derived, so DPI-stable."""
    acc = np.zeros_like(elev, dtype="float32")
    wsum = 0.0
    for mult, wt in ((2.0, 0.5), (4.0, 0.3), (8.0, 0.2)):
        blur = _blur(elev, base_radius_px * mult)
        hp = elev - blur
        s = np.std(hp) + 1e-9
        acc += wt * np.clip(0.5 + hp / (4 * s), 0, 1)
        wsum += wt
    return acc / wsum

def cast_shadow_mask(elev, res_m, azimuth=315, altitude=45, z_factor=1.0):
    """Terrain-occlusion shadow (0 = lit, 1 = fully shadowed): rotate the grid so the
    light travels along +columns, sweep a running sun-horizon down each row, rotate the
    bounded mask back, and soften the edge by a ground-metre penumbra.

    theta = azimuth + 90 maps the light's travel bearing (azimuth + 180) onto +columns;
    verified empirically on all four cardinal azimuths (a NW sun casts SE, etc.) --
    see test_cast_shadow_falls_on_the_far_side. cval=-1e9 marks off-array ground as
    infinitely deep, so the frame edge casts nothing; the mask is bounded to 0..1
    BEFORE the un-rotation so the cval=0 padding interpolates cleanly."""
    e = (elev * z_factor).astype("float32")
    theta = (azimuth + 90.0) % 360.0
    rot = rotate(e, theta, reshape=True, order=1, cval=-1e9)
    drop = np.tan(np.radians(altitude)) * res_m      # horizon fall per pixel step
    h = np.full(rot.shape[0], -np.inf, dtype="float32")
    depth = np.empty_like(rot)
    for j in range(rot.shape[1]):                    # vectorized over rows
        h = np.maximum(h - drop, rot[:, j])
        depth[:, j] = h - rot[:, j]
    depth[rot < -1e8] = 0.0                          # padding neither casts nor darkens
    m = np.clip(depth / SHADOW_RAMP_M, 0.0, 1.0)
    back = rotate(m, -theta, reshape=True, order=1, cval=0.0)
    r0 = (back.shape[0] - elev.shape[0]) // 2
    c0 = (back.shape[1] - elev.shape[1]) // 2
    m = back[r0:r0 + elev.shape[0], c0:c0 + elev.shape[1]]
    return _blur(m, max(0.6, PENUMBRA_M / res_m))

def sky_occlusion(elev, res_m):
    """Multi-scale sky-openness occlusion (0 = open, 1 = deep concavity): depth below
    the neighbourhood mean at several ground radii, each normalized by the horizon
    slope that radius implies (depth / (r * AO_SLOPE)) -- physical and content-
    independent, unlike valley_pass's percentile normalization (which stays untouched:
    it is part of the frozen shadow=0 base look)."""
    acc = np.zeros_like(elev, dtype="float32")
    for r_m, wt in zip(AO_RADII_M, AO_WEIGHTS):
        big = _blur(elev, max(1.0, r_m / res_m))
        acc += wt * np.clip((big - elev) / (r_m * AO_SLOPE), 0.0, 1.0)
    return acc / sum(AO_WEIGHTS)

def _resize_to(a, shape):
    """Bilinear-resize `a` to an exact 2-D shape (zoom rounds; guard the off-by-one)."""
    if a.shape == tuple(shape):
        return a
    out = zoom(a, (shape[0] / a.shape[0], shape[1] / a.shape[1]), order=1)
    if out.shape != tuple(shape):                     # pragma: no cover - zoom rounding
        out = out[:shape[0], :shape[1]]
        pad = ((0, shape[0] - out.shape[0]), (0, shape[1] - out.shape[1]))
        out = np.pad(out, pad, mode="edge")
    return out

def _shadow_terms(elev, res_m, azimuth=315, altitude=45, z_factor=1.0,
                  shadow_res_m=None):
    """(cast, ao) at elev's grid, computed on a fixed GROUND-resolution working grid
    (shadow_res_m, normally the proof's own pixel grid -- see render._shadow_res_m).
    The proof and the final thereby ray-march the same terrain, so the masks agree
    across DPIs by construction; the rotate+sweep also runs on the small grid (cheap).
    A ground-unit pre-smooth makes the native and decimated grids converge on the
    same smoothed field before any ray is cast."""
    work_res = float(max(res_m, shadow_res_m or 0.0))
    e = elev.astype("float32")
    sig_px = SHADOW_PRESMOOTH_FRAC * work_res / res_m
    if sig_px >= 0.3:
        e = gaussian_filter(e, sig_px)
    if work_res / res_m > 1.1:                        # work grid meaningfully coarser
        small = zoom(e, res_m / work_res, order=1)
        cast = cast_shadow_mask(small, work_res, azimuth, altitude, z_factor)
        ao = sky_occlusion(small, work_res)
        cast = np.clip(_resize_to(cast, elev.shape), 0.0, 1.0)
        ao = np.clip(_resize_to(ao, elev.shape), 0.0, 1.0)
    else:
        cast = cast_shadow_mask(e, res_m, azimuth, altitude, z_factor)
        ao = sky_occlusion(e, res_m)
    return cast.astype("float32"), ao.astype("float32")

def _depth_atmosphere(img, elev, norm, tex, res_m, seed, depth):
    """Aerial perspective + salt-pan, both scaled by `depth`. Low ground recedes into
    a faint haze while high ground stays crisp (Imhof), giving the sheet front-to-back
    depth; then the flattest, lowest ground -- the playa -- lifts toward a luminous
    salt-white with a fine mottle, so it reads as salt instead of a lifeless void.

    CONSUMES `img` (it is written in place). Every step below is the same IEEE
    operation in the same order as the allocating form it replaced -- only the
    destination changed -- so the pixels are bit-identical while the pass no longer
    builds five full-sheet RGB temporaries (invariant 1 / the forever-contract)."""
    # aerial perspective: haze rises the lower the ground sits
    aer = (AERIAL_MAX * depth * np.clip(1.0 - norm, 0, 1) ** 1.5)[..., None]
    haze = np.array(HAZE, np.float32)[None, None, :] / 255.0
    img *= (1.0 - aer)
    img += haze * aer
    # salt pan: low AND flat (near-zero local relief from the texture high-pass)
    low = np.clip((SALT_LOW_NORM - norm) / SALT_LOW_NORM, 0, 1)
    flat = np.clip(1.0 - np.abs(tex - 0.5) * 4.0, 0, 1)
    sw = (SALT_MAX * depth * low * flat)
    salt = np.array(SALT, np.float32)[None, None, :] / 255.0
    img *= (1.0 - sw[..., None])
    img += salt * sw[..., None]
    # a fine, dpi-stable mottle so the pan has grain -- only where it actually is salt
    mottle = grain(elev.shape, max(1.0, MOTTLE_CELL_M / res_m), MOTTLE_STRENGTH, seed + 1)
    img *= (1.0 + (mottle - 1.0)[..., None] * np.clip(sw * 3.0, 0, 1)[..., None])
    return img

def _tonal_finish(img):
    """The cartographer's finishing move: a gentle contrast S-curve + a mid-tone
    saturation lift, applied to the composed relief. This is what pulls a flat,
    muddy sheet into one with punch -- deeper shadows, cleaner highlights, and
    colours that separate instead of collapsing into olive-brown. Both are pure
    per-pixel functions, so the proof and the final transform identically (invariant
    1). Endpoints are fixed (0->0, 1->1), so nothing clips to black or blows out.

    This was the single heaviest allocator in the engine -- the naive form built ~10
    full-sheet RGB temporaries (a 300 dpi 18x24 sheet is ~260 MB each). The rewrite
    keeps every IEEE operation and its order (a*b and b*a, a+b and b+a are exact in
    IEEE), so it is bit-identical; only the destinations changed. `img` itself is
    never written -- the first stage clips into a fresh buffer and the rest composite
    into that -- so a direct caller's array is safe."""
    owned = False                    # True once `img` is a buffer this call created
    if RELIEF_CONTRAST > 0:
        x = np.clip(img, 0.0, 1.0)                        # our own buffer from here
        ramp = x * -2.0                                   # -(2x)
        ramp += 3.0                                       # (3 - 2x)
        curve = x * x                                     # multiplication is NOT
        curve *= ramp                                     # associative: keep (x*x)*(3-2x)
        del ramp
        curve *= RELIEF_CONTRAST
        x *= (1.0 - RELIEF_CONTRAST)
        x += curve
        del curve
        img, owned = x, True
    if RELIEF_SATURATION != 1.0:
        # luminance-preserving chroma scale (Rec. 601 weights); keeps the value the
        # contrast curve just set, only spreads the colour away from grey.
        lum = (img * np.array([0.299, 0.587, 0.114], np.float32)).sum(axis=2, keepdims=True)
        if not owned:                                     # never mutate a caller's array
            img, owned = img.copy(), True
        img -= lum
        img *= RELIEF_SATURATION
        img += lum
    return np.clip(img, 0.0, 1.0, out=img if owned else None)

def hypsometric(elev, elev_min, elev_max, norm=None):
    """The elevation colour ramp. `norm` is the already-clipped 0..1 elevation the
    caller may have computed with the identical expression (shaded_relief does) --
    an optimization only; None recomputes it and is exactly equivalent."""
    if norm is None:
        norm = np.clip((elev - elev_min) / (elev_max - elev_min + 1e-9), 0, 1)
    stops = HYPSO_STOPS
    xs = np.array([s[0] for s in stops])
    rgb = np.zeros(elev.shape + (3,), dtype="float32")
    paper = np.array(PAPER, dtype="float32")
    for ch in range(3):
        ys = np.array([s[1][ch] for s in stops], dtype="float32")
        rgb[..., ch] = np.interp(norm, xs, ys) * (1.0 - PAPER_LIFT) + paper[ch] * PAPER_LIFT
    rgb /= 255.0
    return rgb

def texture_pass(elev, radius_px=TEXTURE_RADIUS_PX):
    # high-pass: sharpen ridges and drainages (a cheap stand-in for true texture shading)
    blur = _blur(elev, radius_px)
    hp = elev - blur
    s = np.std(hp) + 1e-9
    return np.clip(0.5 + (hp / (4 * s)), 0, 1)   # 0..1, centered

def valley_pass(elev, radius_px=VALLEY_RADIUS_PX):
    # darken places that sit well below their surroundings
    big = _blur(elev, radius_px)
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
                  grain_cell_px=2.0, grain_strength=0.05,
                  texture_radius_px=TEXTURE_RADIUS_PX, valley_radius_px=VALLEY_RADIUS_PX,
                  biome=None, depth=0.0, shadow=0.0, shadow_res_m=None,
                  sun_azimuth=None, sun_altitude=None, golden=0.0, extras=None):
    """biome: optional (tint01, weight01) from render._biome_layers -- an RGB tint
    field (0..1) and per-pixel confidence, aligned to `elev`. Applied to the
    hypsometric base with luminance matching + the alpine fade (see BIOME_MIX).

    depth: 0..~1 terrain-depth strength, keyed to map scale in render.py. At 0 this is
    byte-identical to the single-light relief (county scale, every existing test); as
    it rises it adds multidirectional light, multiscale texture, aerial perspective,
    and the salt-pan treatment so a zoomed-out sheet stays sculptural (see the depth
    constants above).

    shadow: 0..1 cast-shadow + sky-occlusion strength (the client's shadow_strength
    knob). 0 (the parameter default) is a strict no-op -- the pre-shadow look, every
    direct caller unchanged; render.py supplies the spec's value. shadow_res_m pins
    the shadow working grid to a spec-derived ground resolution so proof == final
    (see _shadow_terms).

    sun_azimuth/sun_altitude/golden (Journey Light, v1.9): when a journey sun is given
    it drives the ray-marched CAST shadows (the form shading -- hillshade, multidir,
    texture, valley -- stays on the archival NW light for legibility, since south-lit
    slope shading reads inverted). `golden` (0..1) then adds a warm/cool split-tone from
    that same sun. Both default to the no-op (sun_azimuth=None, golden=0), so an archival
    render is byte-identical to pre-feature output."""
    elev = _fill_nan(elev.astype("float32"))
    norm = np.clip((elev - elev_min) / (elev_max - elev_min + 1e-9), 0, 1)
    # The frame registered passes read (see the extension seam at the top of this
    # file). Building it is free; with an empty registry no stage below does anything.
    frame = ReliefFrame(elev=elev, res_m=res_m, norm=norm, elev_min=elev_min,
                        elev_max=elev_max, seed=seed, azimuth=azimuth,
                        altitude=altitude, z_factor=z_factor, depth=depth,
                        shadow=shadow, golden=golden, sun_azimuth=sun_azimuth,
                        sun_altitude=sun_altitude, extras=dict(extras or {}))
    # `norm` is the identical expression hypsometric would recompute -- hand it over.
    base = hypsometric(elev, elev_min, elev_max, norm=norm)        # color
    if biome is not None:
        tint, weight = biome
        base_lum = base.mean(axis=2, keepdims=True)
        tint_lum = tint.mean(axis=2, keepdims=True) + 1e-6
        matched = np.clip(tint * (base_lum / tint_lum), 0, 1)    # hue only; keep light
        fade = np.clip((ALPINE_FADE_END - norm) /
                       (ALPINE_FADE_END - ALPINE_FADE_START), 0, 1)
        w3 = (weight * BIOME_MIX * fade)[..., None]
        base = base * (1 - w3) + matched * w3
    base = _run_stage("color", base, frame)          # no-op with an empty registry
    # one slope/aspect pass serves the archival light, the multidirectional blend, and
    # the Journey Light sun -- they differ only in bearing (see slope_aspect). The
    # frame shares it, so a registered pass never pays for a second gradient.
    terrain = frame.terrain()
    hs = hillshade(elev, res_m, azimuth, altitude, z_factor,
                   terrain=terrain) ** HILLSHADE_GAMMA
    tex = texture_pass(elev, texture_radius_px)
    val = valley_pass(elev, valley_radius_px)

    # terrain depth: at depth 0 these blocks are skipped, so hs/tex are untouched and
    # the output is identical to the single-light relief (invariant 1, existing tests).
    if depth > 0:
        d = float(np.clip(depth, 0.0, 1.5))
        w = MULTIDIR_MAX * min(d, 1.0)
        hs_multi = multidirectional_hillshade(
            elev, res_m, azimuth, altitude, z_factor,
            terrain=terrain) ** HILLSHADE_GAMMA
        hs = hs * (1.0 - w) + hs_multi * w
        tex_ms = multiscale_texture(elev, texture_radius_px)
        tex = np.clip(tex + TEXTURE_DEPTH_MAX * d * (tex_ms - 0.5), 0, 1)

    # `hs` is ours (** built it), so the tonal remap runs in place. Addition and
    # multiplication are commutative in IEEE, so this is bit-identical to
    #   light = (SHADOW_FLOOR + (1 - SHADOW_FLOOR) * hs) * (1 - VALLEY_STRENGTH * val)
    light = hs
    light *= (1.0 - SHADOW_FLOOR)
    light += SHADOW_FLOOR                                        # never fully black
    sink = val * -VALLEY_STRENGTH
    sink += 1.0
    light *= sink                                                # sink the valleys
    del sink

    # cast shadows + sky occlusion: at shadow 0 this block is skipped entirely
    # (strict no-op, like the depth pass); shadows darken with an absolute floor so
    # they stay luminous, then fill with cool skylight rather than going grey-black.
    s = float(np.clip(shadow, 0.0, 1.0))
    if s > 0:
        # Journey Light: the cast shadows follow the journey sun when one is set; the
        # form shading above stays on the archival light (legibility). None -> archival,
        # so an archival render is byte-identical.
        cast_az = azimuth if sun_azimuth is None else float(sun_azimuth)
        cast_alt = altitude if sun_altitude is None else float(sun_altitude)
        cast, ao = _shadow_terms(elev, res_m, cast_az, cast_alt, z_factor, shadow_res_m)
        frame.cast, frame.ao = cast, ao          # the ray-march, shared with passes
        light *= (1.0 - CAST_DARKEN * s * cast)
        light *= (1.0 - AO_MAX * s * ao)
        np.maximum(light, CAST_LIGHT_FLOOR, out=light)
    frame.tex, frame.val = tex, val
    light = _run_stage("light", light, frame)
    light = light[..., None]

    # From here `img` is the full-sheet RGB plane -- ~260 MB at a 300 dpi 18x24 final,
    # so every stage composites INTO it rather than allocating a fresh copy. The
    # operations and their order are unchanged (see _tonal_finish), so the sheet is
    # bit-identical; only the peak memory and the memory traffic drop.
    img = base * light
    del base
    if s > 0:                                         # cool skylight in the shadows
        w = (CAST_TINT_MAX * s * cast)[..., None]
        cool = np.array(CAST_TINT, np.float32)[None, None, :]
        img *= (1.0 - w + cool * w)
    # Journey Light golden grade: warm the sunlit faces, cool the shadowed ground. Strict
    # no-op unless a journey sun + golden strength are set (archival stays byte-identical).
    if golden > 0 and sun_azimuth is not None:
        g = float(np.clip(golden, 0.0, 1.0))
        hs_sun = np.clip(hillshade(elev, res_m, float(sun_azimuth), float(sun_altitude),
                                   z_factor, terrain=terrain), 0.0, 1.0)
        lit = hs_sun ** GOLDEN_LIT_GAMMA
        shade = 1.0 - hs_sun
        if s > 0:                       # a cast-shadowed face isn't really sunlit
            lit = lit * (1.0 - cast)
            shade = np.maximum(shade, np.maximum(cast, ao))
        ww = (GOLDEN_WARM_MAX * g * lit)[..., None]
        cw = (GOLDEN_COOL_MAX * g * shade)[..., None]
        warm = np.array(GOLDEN_WARM, np.float32)[None, None, :]
        cool2 = np.array(GOLDEN_COOL, np.float32)[None, None, :]
        img *= (1.0 - ww + warm * ww)
        img *= (1.0 - cw + cool2 * cw)
    # blend texture as a soft dodge/burn around mid-gray
    dodge = tex - 0.5
    dodge *= TEXTURE_STRENGTH
    dodge += 1.0
    img *= dodge[..., None]
    del dodge
    if depth > 0:
        img = _depth_atmosphere(img, elev, norm, tex, res_m, seed, float(np.clip(depth, 0, 1.5)))
    img = _run_stage("finish", img, frame)
    img = _tonal_finish(img)                                      # levels + curves + vibrance
    img = _run_stage("grade", img, frame)
    img *= grain(elev.shape, grain_cell_px, grain_strength, seed)[..., None]
    np.clip(img, 0, 1, out=img)
    img *= 255
    return img.astype("uint8")
