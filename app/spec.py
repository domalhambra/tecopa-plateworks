# app/spec.py
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

class ZoomTooTightError(ValueError):
    pass

@dataclass
class CompositionSpec:
    region_id: str
    crs: str
    crop: tuple           # (min_x, min_y, max_x, max_y) in CRS meters
    print_w_in: float
    print_h_in: float
    native_resolution_m: float
    tracks: list          # list of (N,2) arrays in CRS meters
    hotspots: list        # list of {"x","y","weight"}
    seed: int = 7

    # physical style values (invariant 2): everything visual sized in print units
    track_width_pt: float = 1.4
    track_color: tuple = (38, 36, 33)        # basalt-ish
    track_max_darken: float = 0.85           # overlap darkening ceiling
    marker_diameter_in: float = 0.32
    grain_cell_in: float = 0.014
    grain_strength: float = 0.05
    title_pt: float = 22.0
    title_text: str = ""

    def pixel_size(self, dpi: int) -> tuple:
        return (round(self.print_w_in * dpi), round(self.print_h_in * dpi))

    def ground_per_pixel(self, dpi: int) -> float:
        w_px, _ = self.pixel_size(dpi)
        return (self.crop[2] - self.crop[0]) / w_px

    def validate(self, dpi: int = 300):
        # zoom cap (invariant 6): never request finer ground detail than the data holds
        if self.ground_per_pixel(dpi) < self.native_resolution_m:
            raise ZoomTooTightError(
                f"{self.ground_per_pixel(dpi):.1f} m/px requested, "
                f"data floor is {self.native_resolution_m} m/px")
        return self
