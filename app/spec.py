# app/spec.py
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

# All three are "this picture can't be made here" conditions, not bugs: the API maps
# any SpecError to a humanized 422 (like the zoom cap), so a single except catches them.
class SpecError(ValueError):
    pass

class ZoomTooTightError(SpecError):
    pass

class OutputTooLargeError(SpecError):
    """The requested print size would paint an OOM-sized image. Caught before any
    allocation in validate() so one oversized request can't kill a client session."""
    pass

class OffDemError(SpecError):
    """The crop extends past the region's real elevation data. Raised at render time
    (render.py) rather than validate() because it needs the DEM window, not just the
    spec. Invariant 5: never paint invented terrain -- refuse loudly instead."""
    pass

# Absolute output ceiling (guards OOM): 18x24 @ 300 dpi is ~39 MP, 24x36 is ~78 MP,
# so this leaves headroom for any real poster while blocking a gigapixel request.
MAX_OUTPUT_PIXELS = 120_000_000

@dataclass
class CompositionSpec:
    region_id: str
    crs: str
    crop: tuple           # (min_x, min_y, max_x, max_y) in CRS meters
    print_w_in: float
    print_h_in: float
    native_resolution_m: float
    tracks: list          # list of (N,2) arrays in CRS meters
    hotspots: list        # list of {"x","y","weight", and optional "label"/"icon"/"photo"}
    seed: int = 7

    # physical style values (invariant 2): everything visual sized in print units
    track_width_pt: float = 1.4
    track_color: tuple = (38, 36, 33)        # basalt-ish
    track_max_darken: float = 0.85           # overlap darkening ceiling
    marker_diameter_in: float = 0.18
    grain_cell_in: float = 0.014
    grain_strength: float = 0.05
    title_pt: float = 22.0
    title_text: str = ""
    # rich markers (v1.1): labels, vector icons, and pinned photos -- all picture
    # decisions, so they live on the spec; sizes physical so proof == final layout.
    label_pt: float = 11.0                   # marker label text size
    photo_box_in: float = 1.15               # long edge of a pinned photo thumbnail

    def pixel_size(self, dpi: int) -> tuple:
        return (round(self.print_w_in * dpi), round(self.print_h_in * dpi))

    def ground_per_pixel(self, dpi: int) -> float:
        w_px, _ = self.pixel_size(dpi)
        return (self.crop[2] - self.crop[0]) / w_px

    def validate(self, dpi: int = 300):
        w_px, h_px = self.pixel_size(dpi)
        # print-size sanity: a non-positive size would divide-by-zero the zoom cap below
        if w_px < 1 or h_px < 1:
            raise SpecError(
                f"print size {self.print_w_in}x{self.print_h_in} in is not renderable")
        # absolute output-pixel ceiling: refuse an OOM-sized render before any allocation
        if w_px * h_px > MAX_OUTPUT_PIXELS:
            raise OutputTooLargeError(
                f"{w_px}x{h_px}px ({w_px * h_px / 1e6:.0f} MP) exceeds the "
                f"{MAX_OUTPUT_PIXELS // 1_000_000} MP output ceiling; "
                f"choose a smaller print size")
        # zoom cap (invariant 6): never request finer ground detail than the data holds
        if self.ground_per_pixel(dpi) < self.native_resolution_m:
            raise ZoomTooTightError(
                f"{self.ground_per_pixel(dpi):.1f} m/px requested, "
                f"data floor is {self.native_resolution_m} m/px")
        return self
