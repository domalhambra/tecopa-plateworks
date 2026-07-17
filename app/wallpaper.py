# app/wallpaper.py
"""Wallpaper output: a screen is a sheet with a known ppi.

A wallpaper is a print whose sheet size is derived from the device
(print_w_in = px / ppi) and whose final dpi is the device's ppi, so
pixel_size(final_dpi()) returns the device's exact native pixels and every
engine invariant -- physical units, the zoom cap, determinism, the off-DEM
guard, provenance/reprint -- carries over unchanged. A 2.6 pt track is
literally 2.6 pt on the client's glass.

The same contract carries the social share canvases (device_class "social"):
a Reel/feed frame is a small sheet whose *chosen* effective ppi sets the
stroke weight on a phone screen -- the one knob a platform canvas has no
physical truth for, so the table decides it once (SOCIAL_PPI).

The preset table below is the single source of truth: the wizard fetches it
from GET /api/wallpapers/presets and never hardcodes device sizes. A device
the table doesn't carry renders through custom_preset() (the escape hatch:
the table goes stale a little every device cycle; the engine doesn't)."""
from __future__ import annotations
import math
from dataclasses import dataclass, replace
from app.geo import refit_crop_aspect
from app.spec import CompositionSpec

# Auto-placed geography labels stay out of the top of a phone/tablet sheet: the OS
# draws the lock-screen clock there. User-placed markers/photos are left alone.
PHONE_TOP_CLEAR = 0.18
TABLET_TOP_CLEAR = 0.10
# ...and out of the bottom band: the phone home-indicator / lock-screen quick
# controls, and a Reel's caption + action zone. Same posture as the clock band --
# auto geography only, user-placed markers/photos are the operator's call.
PHONE_BOTTOM_CLEAR = 0.10
REEL_BOTTOM_CLEAR = 0.20

# Social canvases have no physical glass, so the effective ppi is a DESIGN choice:
# it sets every physical style value's pixel weight (2.6 pt track ≈ 5.8 px at 160).
# Chosen so the route reads at phone-feed size; validated by eye, one place to tune.
SOCIAL_PPI = 160.0


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    px_w: int
    px_h: int
    ppi: float
    device_class: str            # desktop | laptop | phone | tablet | social | custom
    top_clear_frac: float = 0.0
    bottom_clear_frac: float = 0.0

    @property
    def aspect(self) -> float:
        return self.px_w / self.px_h

    def meta(self) -> dict:
        """What /api/wallpapers/presets serves the wizard."""
        return {"id": self.id, "name": self.name, "px": [self.px_w, self.px_h],
                "ppi": self.ppi, "device_class": self.device_class,
                "top_clear_frac": self.top_clear_frac,
                "bottom_clear_frac": self.bottom_clear_frac}

    def spec_fields(self) -> dict:
        """THE definition of 'a wallpaper of this device' as CompositionSpec fields --
        the sheet derived from the glass (px / ppi), the device's ppi as the final
        resolution, and clean furniture (no keyline, compass or cartouche). Both
        spec-build sites (the proof endpoint's wallpaper mode and spec_for_preset's
        bundle re-target) consume this one dict, so the policy can never drift
        between a single-device final and the same device's file in a bundle.
        Social canvases ship the same clean furniture: a caption belongs to the
        platform post, not the pixels (a titled social card is a recorded product
        call, not a silent default)."""
        return dict(print_w_in=self.px_w / self.ppi, print_h_in=self.px_h / self.ppi,
                    output_kind="wallpaper", screen_ppi=self.ppi,
                    keyline=False, compass=False, title_text="",
                    top_clear_frac=self.top_clear_frac,
                    bottom_clear_frac=self.bottom_clear_frac)


# ppi values are the device's real physical density (the "sheet" is the actual glass).
# Phone panels are named by the models that actually carry them -- the exact-native-
# pixels promise dies quietly when the table trails the market (red-team 2026-07-17).
PRESETS = {p.id: p for p in (
    Preset("desktop_fhd", "Desktop FHD 24″", 1920, 1080, 92.0, "desktop"),
    Preset("desktop_qhd", "Desktop QHD 27″", 2560, 1440, 109.0, "desktop"),
    Preset("desktop_4k", "Desktop 4K 27″", 3840, 2160, 163.0, "desktop"),
    Preset("desktop_5k", "Studio Display 5K 27″", 5120, 2880, 218.0, "desktop"),
    Preset("ultrawide", "Ultrawide 34″", 3440, 1440, 110.0, "desktop"),
    Preset("macbook_air", "MacBook Air 13″", 2560, 1664, 224.0, "laptop"),
    Preset("macbook_pro_14", "MacBook Pro 14″", 3024, 1964, 254.0, "laptop"),
    Preset("macbook_pro_16", "MacBook Pro 16″", 3456, 2234, 254.0, "laptop"),
    Preset("iphone", "iPhone 16 / 15", 1179, 2556, 460.0, "phone",
           PHONE_TOP_CLEAR, PHONE_BOTTOM_CLEAR),
    Preset("iphone_pro", "iPhone 17 / 16 Pro", 1206, 2622, 460.0, "phone",
           PHONE_TOP_CLEAR, PHONE_BOTTOM_CLEAR),
    Preset("iphone_max", "iPhone 16 Plus / 15 Pro Max", 1290, 2796, 460.0, "phone",
           PHONE_TOP_CLEAR, PHONE_BOTTOM_CLEAR),
    Preset("iphone_pro_max", "iPhone 17 Pro Max / 16 Pro Max", 1320, 2868, 460.0,
           "phone", PHONE_TOP_CLEAR, PHONE_BOTTOM_CLEAR),
    Preset("android", "Android flagship", 1440, 3120, 500.0, "phone",
           PHONE_TOP_CLEAR, PHONE_BOTTOM_CLEAR),
    Preset("android_fhd", "Android FHD+", 1080, 2400, 400.0, "phone",
           PHONE_TOP_CLEAR, PHONE_BOTTOM_CLEAR),
    Preset("ipad", "iPad Pro 13″", 2064, 2752, 264.0, "tablet", TABLET_TOP_CLEAR),
    # Social share canvases: the vertical/portrait/square frames the film twins are
    # posted into. 9:16 is the Reels/Stories/Shorts frame the phone wallpapers only
    # approximate (1179x2556 is 0.46, a Reel is 0.5625 -- posted films were getting
    # pillarboxed on exactly the surfaces the share twins exist for).
    Preset("ig_reel", "Reel / Story 9:16", 1080, 1920, SOCIAL_PPI, "social",
           0.0, REEL_BOTTOM_CLEAR),
    Preset("ig_portrait", "Feed portrait 4:5", 1080, 1350, SOCIAL_PPI, "social"),
    Preset("ig_square", "Feed square 1:1", 1080, 1080, SOCIAL_PPI, "social"),
)}

# Custom-device pixel bounds: wide enough for any real screen (an 8K TV is 7680),
# tight enough that the 422 names the real problem. Everything load-bearing -- the
# ppi range, the output-pixel ceiling, the zoom cap -- is spec.validate()'s job.
CUSTOM_PX_BOUNDS = (240, 10240)


def custom_preset(px_w, px_h, ppi) -> Preset:
    """A one-off device the table doesn't carry: the same Preset contract under the
    id "custom", so a spec built from it is indistinguishable from a table device's
    (exact native pixels, physical styles at the glass's ppi, clean furniture). The
    table stays the convenience path; this is the escape hatch that keeps the
    exact-native-pixels promise from decaying with every device cycle. Raises
    ValueError with the operator-facing sentence; the caller maps it to a 422.
    No clock/home-indicator bands: the operator naming a bespoke screen frames the
    whole glass (the bands are a table-preset nicety, not a spec requirement)."""
    lo, hi = CUSTOM_PX_BOUNDS
    if not (isinstance(px_w, int) and isinstance(px_h, int)
            and lo <= px_w <= hi and lo <= px_h <= hi):
        raise ValueError(f"custom device pixels must be whole numbers "
                         f"between {lo} and {hi}")
    if not (isinstance(ppi, (int, float)) and not isinstance(ppi, bool)
            and math.isfinite(ppi) and ppi > 0):
        raise ValueError("custom_ppi must be a positive number")
    return Preset("custom", f"Custom {px_w}×{px_h}", px_w, px_h, float(ppi), "custom")


def spec_for_preset(spec: CompositionSpec, preset: Preset,
                    region_bounds) -> CompositionSpec:
    """Re-target a composed spec at a device: same tracks, hotspots, style values and
    seed -- the picture decisions -- with the crop re-fit to the device's aspect
    (center-preserving, region-clamped, grown to the zoom-cap floor) and the sheet
    re-derived from the glass (px / ppi). Furniture goes clean: no keyline, compass
    or cartouche on a wallpaper; the labels/contours/biome toggles stay as the user
    set them. Validates at the device's ppi, so an infeasible target raises the
    usual SpecError family for the caller to surface honestly."""
    floor_w = spec.native_resolution_m * preset.px_w
    crop = refit_crop_aspect(spec.crop, preset.aspect, region_bounds, floor_w=floor_w)
    out = replace(spec, crop=crop, **preset.spec_fields())
    out.validate(out.final_dpi())
    return out
