# tests/test_render.py
import json, os
import numpy as np
import pytest
from PIL import Image
from app.spec import CompositionSpec, ZoomTooTightError, OffDemError
from app.render import rasterize

REGION_DIR = "regions/lassen_ca"

# The DEM is gitignored, but tests/conftest.py hydrates a synthetic one on a fresh
# clone / in CI, so these integration tests always run (red-team V1-4). A machine
# with a real 3DEP DEM runs them against real terrain instead.

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
    # empty hydro keeps this relief-only (water has its own DPI-scaled elements)
    no_water = {"lakes": [], "rivers": []}
    proof = rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=no_water)
    final = rasterize(spec, dpi=300, region_dir=REGION_DIR, hydro=no_water)
    final_ds = final.resize(proof.size, Image.LANCZOS)
    mad = np.abs(np.asarray(proof, np.float32) - np.asarray(final_ds, np.float32)).mean()
    assert mad < 2.5, f"proof is not a faithful scale of the final: mean abs diff {mad:.2f}/255"

def test_water_fills_lake_area():
    cfg = _cfg(); bx = cfg["bounds"]
    cx = (bx[0]+bx[2])/2; cy = (bx[1]+bx[3])/2
    crop = (cx-13500, cy-18000, cx+13500, cy+18000)
    spec = CompositionSpec(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                           print_w_in=9, print_h_in=12, native_resolution_m=10,
                           tracks=[], hotspots=[], seed=7)
    lake = [[cx-6000, cy-6000], [cx+6000, cy-6000], [cx+6000, cy+6000], [cx-6000, cy+6000]]
    dry = rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro={"lakes": [], "rivers": []})
    wet = rasterize(spec, dpi=96, region_dir=REGION_DIR,
                    hydro={"lakes": [{"coords": lake, "name": "L"}], "rivers": []})
    from app.render import WATER_FILL
    a = np.asarray(dry); b = np.asarray(wet)
    assert not np.array_equal(a, b)                       # water changed the image
    px = b[wet.size[1] // 2, wet.size[0] // 2]            # centre of the lake
    assert all(abs(int(px[i]) - WATER_FILL[i]) < 40 for i in range(3))

def test_hydro_tolerates_malformed_and_checks_crs():
    cfg = _cfg(); bx = cfg["bounds"]
    cx = (bx[0]+bx[2])/2; cy = (bx[1]+bx[3])/2
    crop = (cx-13500, cy-18000, cx+13500, cy+18000)
    spec = CompositionSpec(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                           print_w_in=9, print_h_in=12, native_resolution_m=10,
                           tracks=[], hotspots=[], seed=7)
    # missing 'coords' and 3-tuple (z) coords must not crash the render
    bad = {"crs": cfg["crs"],
           "lakes": [{"name": "no-coords"},
                     {"coords": [[cx-2000, cy-2000, 9], [cx+2000, cy-2000, 9], [cx+2000, cy+2000, 9]]}],
           "rivers": [{"order": 4, "name": "no-coords"}]}
    assert rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=bad).size == (864, 1152)
    # a foreign-CRS hydro must fail loud rather than mis-register water silently
    with pytest.raises(ValueError):
        rasterize(spec, dpi=96, region_dir=REGION_DIR,
                  hydro={"crs": "EPSG:32611", "lakes": [], "rivers": []})

def test_rasterize_rejects_off_dem_crop():
    # red-team V1-1: a cap-clearing crop shoved past the region's real DEM must raise
    # OffDemError, not silently paint crop-mean terrain under the tracks. 27x36 km
    # (passes the 10 m/px cap at 9x12) but pushed ~80% past the east edge.
    cfg = _cfg(); bx = cfg["bounds"]
    east = bx[2]; cy = (bx[1] + bx[3]) / 2
    crop = (east - 5000, cy - 18000, east + 22000, cy + 18000)
    spec = CompositionSpec(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                           print_w_in=9, print_h_in=12, native_resolution_m=10,
                           tracks=[np.array([[east - 4000, cy], [east + 20000, cy]])],
                           hotspots=[], seed=7)
    with pytest.raises(OffDemError):
        rasterize(spec, dpi=96, region_dir=REGION_DIR)

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
