# app/wallpaper.py
"""Wallpaper output: a screen is a sheet with a known ppi.

A wallpaper is a print whose sheet size is derived from the device
(print_w_in = px / ppi) and whose final dpi is the device's ppi, so
pixel_size(final_dpi()) returns the device's exact native pixels and every
engine invariant -- physical units, the zoom cap, determinism, the off-DEM
guard, provenance/reprint -- carries over unchanged. A 2.6 pt track is
literally 2.6 pt on the client's glass.

The preset table below is the single source of truth: the wizard fetches it
from GET /api/wallpapers/presets and never hardcodes device sizes."""
from __future__ import annotations
from dataclasses import dataclass, replace
from app.geo import refit_crop_aspect
from app.spec import CompositionSpec

# Auto-placed geography labels stay out of the top of a phone/tablet sheet: the OS
# draws the lock-screen clock there. User-placed markers/photos are left alone.
PHONE_TOP_CLEAR = 0.18
TABLET_TOP_CLEAR = 0.10


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    px_w: int
    px_h: int
    ppi: float
    device_class: str            # desktop | laptop | phone | tablet (UI grouping)
    top_clear_frac: float = 0.0

    @property
    def aspect(self) -> float:
        return self.px_w / self.px_h

    def meta(self) -> dict:
        """What /api/wallpapers/presets serves the wizard."""
        return {"id": self.id, "name": self.name, "px": [self.px_w, self.px_h],
                "ppi": self.ppi, "device_class": self.device_class,
                "top_clear_frac": self.top_clear_frac}

    def spec_fields(self) -> dict:
        """THE definition of 'a wallpaper of this device' as CompositionSpec fields --
        the sheet derived from the glass (px / ppi), the device's ppi as the final
        resolution, and clean furniture (no keyline, compass or cartouche). Both
        spec-build sites (the proof endpoint's wallpaper mode and spec_for_preset's
        bundle re-target) consume this one dict, so the policy can never drift
        between a single-device final and the same device's file in a bundle."""
        return dict(print_w_in=self.px_w / self.ppi, print_h_in=self.px_h / self.ppi,
                    output_kind="wallpaper", screen_ppi=self.ppi,
                    keyline=False, compass=False, title_text="",
                    top_clear_frac=self.top_clear_frac)


# ppi values are the device's real physical density (the "sheet" is the actual glass).
PRESETS = {p.id: p for p in (
    Preset("desktop_fhd", "Desktop FHD 24″", 1920, 1080, 92.0, "desktop"),
    Preset("desktop_qhd", "Desktop QHD 27″", 2560, 1440, 109.0, "desktop"),
    Preset("desktop_4k", "Desktop 4K 27″", 3840, 2160, 163.0, "desktop"),
    Preset("ultrawide", "Ultrawide 34″", 3440, 1440, 110.0, "desktop"),
    Preset("macbook_air", "MacBook Air 13″", 2560, 1664, 224.0, "laptop"),
    Preset("macbook_pro_14", "MacBook Pro 14″", 3024, 1964, 254.0, "laptop"),
    Preset("macbook_pro_16", "MacBook Pro 16″", 3456, 2234, 254.0, "laptop"),
    Preset("iphone", "iPhone (Pro / 16)", 1179, 2556, 460.0, "phone", PHONE_TOP_CLEAR),
    Preset("iphone_max", "iPhone Pro Max", 1290, 2796, 460.0, "phone", PHONE_TOP_CLEAR),
    Preset("android", "Android flagship", 1440, 3120, 500.0, "phone", PHONE_TOP_CLEAR),
    Preset("android_fhd", "Android FHD+", 1080, 2400, 400.0, "phone", PHONE_TOP_CLEAR),
    Preset("ipad", "iPad Pro 13″", 2064, 2752, 264.0, "tablet", TABLET_TOP_CLEAR),
)}


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
