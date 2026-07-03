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
    # 3.0: relief is base*light, so the V1-10 paper-lift (brighter base) scales the
    # same relative resampling noise to a larger absolute MAD (~2.4 -> ~2.5 measured
    # on the real DEM). The guard is against DPI-dependent texture/valley scale, which
    # would push this far past 3.
    assert mad < 3.0, f"proof is not a faithful scale of the final: mean abs diff {mad:.2f}/255"

def test_proof_track_treatment_is_a_faithful_scale_of_final():
    # V1-10 regression guard for physical-unit track styling: casing blur and edge
    # feather used to be raw PIXELS, so the proof's halo was ~3x softer than the
    # final's. Whole-image MAD is dominated by terrain and cannot see this, so the
    # comparison is masked to the TRACK CORRIDOR (where the regression lives).
    # Two coincident distinct-day tracks exercise the worn-width path across DPIs.
    from app import render as render_mod
    cfg = _cfg(); bx = cfg["bounds"]
    cx = (bx[0]+bx[2])/2; cy = (bx[1]+bx[3])/2
    crop = (cx-13500, cy-18000, cx+13500, cy+18000)
    line = np.array([[crop[0]+3000, crop[1]+3000], [crop[2]-3000, crop[3]-3000]])
    spec = CompositionSpec(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                           print_w_in=9, print_h_in=12, native_resolution_m=10,
                           tracks=[line, line.copy()],
                           track_days=["2024-06-01", "2024-06-02"],
                           hotspots=[], seed=7)
    no_water = {"lakes": [], "rivers": []}
    proof = rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=no_water)
    final = rasterize(spec, dpi=300, region_dir=REGION_DIR, hydro=no_water)
    final_ds = final.resize(proof.size, Image.LANCZOS)
    w, h = proof.size
    corridor = render_mod._coverage(spec, w, h, width_px=12) > 0    # line + halo + slack
    diff = np.abs(np.asarray(proof, np.float32) - np.asarray(final_ds, np.float32))
    mad = diff[corridor].mean()
    # calibrated on the real DEM: the physical-unit treatment measures 14.75 here;
    # the old px-valued blur/feather (same pixel sigma at both DPIs) measures 17.34.
    assert mad < 16.0, f"track treatment shifts with DPI: corridor MAD {mad:.2f}/255"
    assert diff.mean() < 3.5, f"whole-image drift: {diff.mean():.2f}/255"

def test_terrain_depth_scale_keying():
    # the depth strength is a pure function of the DPI-independent map scale: off at
    # county scale (where every other relief test renders), full at corridor scale.
    from app.render import _terrain_depth
    def mk(crop_w_m, print_w, td=1.0):
        return CompositionSpec(region_id="x", crs="EPSG:32611",
                               crop=(0, 0, crop_w_m, crop_w_m * 2 / 3),
                               print_w_in=print_w, print_h_in=print_w * 2 / 3,
                               native_resolution_m=30, tracks=[], hotspots=[],
                               seed=7, terrain_depth=td)
    assert _terrain_depth(mk(27000, 9)) == 0.0        # ~1:118k -> no-op
    assert _terrain_depth(mk(437000, 36)) == 1.0      # ~1:478k -> full
    assert abs(_terrain_depth(mk(437000, 36, td=0.5)) - 0.5) < 1e-9
    assert _terrain_depth(mk(437000, 36, td=0.0)) == 0.0   # client can force it off

def test_terrain_depth_changes_relief_at_corridor_scale():
    # end-to-end: a corridor-scale render with the depth pass on differs from the same
    # render with it forced off (synthetic DEM hydrated by conftest for elko_bonneville).
    cfg = json.load(open("regions/elko_bonneville/region.json"))
    bx = cfg["bounds"]; cx = (bx[0]+bx[2])/2; cy = (bx[1]+bx[3])/2
    half = 215000.0
    crop = (cx-half, cy-half*2/3, cx+half, cy+half*2/3)
    def mk(td):
        return CompositionSpec(region_id="elko_bonneville", crs=cfg["crs"], crop=crop,
                               print_w_in=36, print_h_in=24,
                               native_resolution_m=cfg["native_resolution_m"],
                               tracks=[], hotspots=[], seed=7, title_text="-",
                               compass=False, terrain_depth=td)
    nw = {"lakes": [], "rivers": []}
    off = np.asarray(rasterize(mk(0.0), dpi=64, region_dir="regions/elko_bonneville", hydro=nw))
    on = np.asarray(rasterize(mk(1.0), dpi=64, region_dir="regions/elko_bonneville", hydro=nw))
    assert not np.array_equal(off, on), "terrain depth did nothing at corridor scale"

def test_shadow_res_m_is_dpi_independent():
    # the shadow working grid is a pure function of the spec (96 samples per print
    # inch), never the render DPI -- proof and final ray-march the same terrain.
    from app.render import _shadow_res_m
    spec = CompositionSpec(region_id="x", crs="EPSG:32611",
                           crop=(0, 0, 86400, 57600), print_w_in=24, print_h_in=16,
                           native_resolution_m=10, tracks=[], hotspots=[], seed=7)
    assert abs(_shadow_res_m(spec) - 86400 / (24 * 96)) < 1e-9   # 37.5 m/sample
    # no dpi anywhere in the function: same value regardless of render size

def test_shadow_strength_changes_the_render():
    # end-to-end: shadow_strength=1 differs from 0 through rasterize (synthetic DEM).
    cfg = json.load(open("regions/elko_bonneville/region.json"))
    bx = cfg["bounds"]; cx = (bx[0]+bx[2])/2; cy = (bx[1]+bx[3])/2
    half = 100000.0
    crop = (cx-half, cy-half*2/3, cx+half, cy+half*2/3)
    def mk(ss):
        return CompositionSpec(region_id="elko_bonneville", crs=cfg["crs"], crop=crop,
                               print_w_in=36, print_h_in=24,
                               native_resolution_m=cfg["native_resolution_m"],
                               tracks=[], hotspots=[], seed=7, title_text="-",
                               compass=False, shadow_strength=ss)
    nw = {"lakes": [], "rivers": []}
    off = np.asarray(rasterize(mk(0.0), dpi=64, region_dir="regions/elko_bonneville", hydro=nw))
    on = np.asarray(rasterize(mk(1.0), dpi=64, region_dir="regions/elko_bonneville", hydro=nw))
    assert not np.array_equal(off, on), "shadow_strength did nothing"

def test_rasterize_composites_terminus_pins():
    # the pins must actually be wired into rasterize (the unit tests call
    # _draw_termini directly and would stay green if the call were dropped).
    cfg = _cfg(); bx = cfg["bounds"]
    cx = (bx[0]+bx[2])/2; cy = (bx[1]+bx[3])/2
    crop = (cx-13500, cy-18000, cx+13500, cy+18000)
    line = np.array([[crop[0]+3000, crop[1]+3000], [crop[2]-3000, crop[3]-3000]])
    spec = CompositionSpec(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                           print_w_in=9, print_h_in=12, native_resolution_m=10,
                           tracks=[line], hotspots=[], seed=7,
                           compass=False)   # the rose's ground disc would cover the probe
    img = rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro={"lakes": [], "rivers": []})
    out = np.asarray(img).astype(int)
    from app.render import TERMINUS_INK
    # start point (crop[0]+3000, crop[1]+3000) -> px (96, 1056) at 9x12 @ 96 dpi
    patch = out[1056-8:1056+8, 96-8:96+8]
    d = np.linalg.norm(patch - np.array(TERMINUS_INK), axis=2)
    assert (d < 40).sum() > 8, "terminus pin not composited by rasterize()"
    assert (patch.sum(axis=2) > 640).sum() > 3, "terminus ring not composited"

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
