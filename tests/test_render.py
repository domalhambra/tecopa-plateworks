# tests/test_render.py
import json, os
import numpy as np
import pytest
from PIL import Image
from app.spec import CompositionSpec, ZoomTooTightError
from app.render import rasterize

REGION_DIR = "regions/lassen_ca"

# Integration tests need the built DEM (gitignored); skip on a fresh clone.
pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(REGION_DIR, "dem.tif")),
    reason="region assets not built; run region_prep.py")

def _cfg():
    return json.load(open(os.path.join(REGION_DIR, "region.json")))

def test_proof_and_final_same_layout():
    cfg = _cfg(); bx = cfg["bounds"]
    cx = (bx[0]+bx[2])/2; cy = (bx[1]+bx[3])/2
    # 27 km x 36 km crop (0.75 aspect) -> exactly 10 m/px at 9x12 in @ 300 dpi (passes the cap)
    crop = (cx-13500, cy-18000, cx+13500, cy+18000)
    spec = CompositionSpec(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                           print_w_in=9, print_h_in=12, native_resolution_m=10,
                           tracks=[np.array([[crop[0]+2000, crop[1]+2000],
                                             [crop[2]-2000, crop[3]-2000]])],
                           hotspots=[{"x": cx, "y": cy, "weight": 4}],
                           seed=7)
    proof = rasterize(spec, dpi=96, region_dir=REGION_DIR, watermark=True)
    final = rasterize(spec, dpi=300, region_dir=REGION_DIR, watermark=False)
    assert proof.size == (864, 1152)      # 9x12 @ 96
    assert final.size == (2700, 3600)     # 9x12 @ 300 -- same layout, more pixels

def test_proof_relief_is_a_faithful_scale_of_final():
    # Invariant 1: one spec, painted at many sizes. The proof (96 dpi) downscaled
    # from the final (300 dpi) must be nearly identical -- relief texture/valley
    # scale must NOT shift with DPI. (Relief only: no tracks/markers to isolate it.)
    cfg = _cfg(); bx = cfg["bounds"]
    cx = (bx[0]+bx[2])/2; cy = (bx[1]+bx[3])/2
    crop = (cx-13500, cy-18000, cx+13500, cy+18000)
    spec = CompositionSpec(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                           print_w_in=9, print_h_in=12, native_resolution_m=10,
                           tracks=[], hotspots=[], seed=7)
    proof = rasterize(spec, dpi=96, region_dir=REGION_DIR)
    final = rasterize(spec, dpi=300, region_dir=REGION_DIR)
    final_ds = final.resize(proof.size, Image.LANCZOS)
    mad = np.abs(np.asarray(proof, np.float32) - np.asarray(final_ds, np.float32)).mean()
    assert mad < 2.5, f"proof is not a faithful scale of the final: mean abs diff {mad:.2f}/255"

def test_rasterize_rejects_too_tight():
    cfg = _cfg(); bx = cfg["bounds"]
    cx = (bx[0]+bx[2])/2; cy = (bx[1]+bx[3])/2
    crop = (cx-5000, cy-6667, cx+5000, cy+6667)   # 10 km wide on 9 in @ 300 -> ~3.7 m/px < 10
    spec = CompositionSpec(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                           print_w_in=9, print_h_in=12, native_resolution_m=10,
                           tracks=[np.array([[cx, cy], [cx+100, cy+100]])],
                           hotspots=[], seed=7)
    with pytest.raises(ZoomTooTightError):
        rasterize(spec, dpi=300, region_dir=REGION_DIR)
