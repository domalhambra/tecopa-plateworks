# app/spec.py
from __future__ import annotations
from dataclasses import dataclass
import math

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

PHOTO_FRAME_STYLES = ("mat", "keyline", "borderless", "polaroid")
# Style-slider bounds: the UI's sliders stay inside these, and validate() refuses
# anything outside them so a hand-rolled API call can't render something absurd.
STYLE_BOUNDS = {"track_width_pt": (0.8, 6.0), "track_halo": (0.0, 0.9),
                "marker_diameter_in": (0.1, 0.5), "marker_ring": (0.0, 0.25)}

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
    # Journey identity, parallel to `tracks` (None -> each track is its own journey).
    # Devices split one outing into several segments at auto-pause/stop-resume; the
    # renderer groups segments sharing a day into ONE journey so the worn-width pass
    # counts distinct outings (not segments) and terminus pins mark real start/end.
    track_days: list | None = None

    # physical style values (invariant 2): everything visual sized in print units.
    # Defaults follow the V1-10 "pronounced" pass (approved by Dom): the route,
    # markers, and photos are sized to read at poster viewing distance (2-3 m),
    # not arm's length -- legibility-first, like a mapping app.
    track_width_pt: float = 2.6
    track_max_darken: float = 0.9            # ink ceiling (grain still shows through)
    marker_diameter_in: float = 0.24
    grain_cell_in: float = 0.014
    grain_strength: float = 0.05
    title_pt: float = 22.0
    title_text: str = ""
    # rich markers (v1.1): labels, vector icons, and pinned photos -- all picture
    # decisions, so they live on the spec; sizes physical so proof == final layout.
    label_pt: float = 13.0                   # marker label text size
    photo_box_in: float = 1.5                # long edge of a pinned photo thumbnail
    # map furniture (v1.2): elevation contours (auto interval from the crop's local
    # relief) and the compass rose above the title block. Picture decisions -> spec.
    contours: bool = False
    compass: bool = True
    # client style controls (v1.2): the knobs the wizard's Style panel exposes.
    # All picture decisions -> spec, so the final renders exactly the styled proof.
    track_rgb: tuple = (214, 158, 58)        # route ink (curated swatches in the UI)
    track_halo: float = 0.7                  # paper-halo strength; 0 = no outline
    marker_ring: float = 0.09                # POI ring width, fraction of diameter; 0 = none
    photo_frame_style: str = "mat"           # mat | keyline | borderless | polaroid

    def pixel_size(self, dpi: int) -> tuple:
        return (round(self.print_w_in * dpi), round(self.print_h_in * dpi))

    def ground_per_pixel(self, dpi: int) -> float:
        w_px, _ = self.pixel_size(dpi)
        return (self.crop[2] - self.crop[0]) / w_px

    def validate(self, dpi: int = 300):
        # finiteness first: a NaN/inf print size or crop (a client can POST print_w=nan)
        # would make round() raise ValueError/OverflowError -- which are NOT SpecError, so
        # they'd escape the endpoint's `except SpecError` as an uncaught 500. Convert to a
        # clean 422 up front.
        if not (math.isfinite(self.print_w_in) and math.isfinite(self.print_h_in)):
            raise SpecError(f"print size {self.print_w_in}x{self.print_h_in} in is not finite")
        if not all(math.isfinite(v) for v in self.crop):
            raise SpecError("crop bounds are not finite")
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
        # style knobs: refuse out-of-range values rather than clamping silently (the
        # UI sliders can't produce them; a raw API call gets an honest 422)
        for name, (lo, hi) in STYLE_BOUNDS.items():
            v = getattr(self, name)
            if not (math.isfinite(v) and lo <= v <= hi):
                raise SpecError(f"{name} must be between {lo} and {hi}")
        if self.photo_frame_style not in PHOTO_FRAME_STYLES:
            raise SpecError(f"photo_frame_style must be one of {PHOTO_FRAME_STYLES}")
        if (len(tuple(self.track_rgb)) != 3
                or not all(isinstance(c, int) and 0 <= c <= 255 for c in self.track_rgb)):
            raise SpecError("track_rgb must be three 0-255 integers")
        # crop must be a real box, and its aspect must match the print aspect -- the
        # renderer maps crop -> full sheet, so a mismatch would stretch the terrain
        # anisotropically with no error anywhere downstream (red-team).
        cw, ch = self.crop[2] - self.crop[0], self.crop[3] - self.crop[1]
        if cw <= 0 or ch <= 0:
            raise SpecError("crop is empty or inverted")
        crop_ar, print_ar = cw / ch, self.print_w_in / self.print_h_in
        if abs(crop_ar - print_ar) / print_ar > 0.02:
            raise SpecError(
                f"crop aspect {crop_ar:.3f} doesn't match print aspect {print_ar:.3f}; "
                f"the picture would be stretched -- re-frame the crop")
        # zoom cap (invariant 6): never request finer ground detail than the data
        # holds, judged on BOTH axes (x-only let a tall thin crop bypass it).
        gpp = min(cw / w_px, ch / h_px)
        if gpp < self.native_resolution_m:
            raise ZoomTooTightError(
                f"{gpp:.1f} m/px requested, "
                f"data floor is {self.native_resolution_m} m/px")
        return self
