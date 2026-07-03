# tests/test_biome.py
# Biome tint (v1.2): hue from NLCD land cover, lightness from elevation + shade.
# Guards the blend physics (luminance preserved, alpine fade), the windowed-read
# registration path, and the graceful fallback when a region has no landcover.
import json
import os

import numpy as np
import rasterio
from rasterio.transform import from_bounds

from app.spec import CompositionSpec
from app import relief, render


def _ramp(h=240, w=200, lo=1000.0, hi=2000.0):
    """A north-south elevation ramp with gentle E-W texture so hillshade has work."""
    yy, xx = np.mgrid[0:h, 0:w].astype("float32")
    return lo + (hi - lo) * (yy / (h - 1)) + 8.0 * np.sin(xx / 7.0)


def test_blend_shifts_hue_keeps_luminance_and_summits():
    elev = _ramp()                                   # low at top rows, high at bottom
    tint = np.zeros(elev.shape + (3,), np.float32)
    tint[:] = np.array(relief.BIOME_TINT[42], np.float32) / 255.0   # evergreen
    weight = np.ones(elev.shape, np.float32)
    plain = relief.shaded_relief(elev, 30.0, 1000, 2000, seed=7).astype(np.float32)
    biome = relief.shaded_relief(elev, 30.0, 1000, 2000, seed=7,
                                 biome=(tint, weight)).astype(np.float32)
    # low ground (norm ~ 0.1): greener than plain (hue moved toward evergreen)
    low_p, low_b = plain[10:40], biome[10:40]
    green_frac = lambda a: (a[..., 1] / (a.sum(axis=2) + 1e-6)).mean()
    assert green_frac(low_b) > green_frac(low_p) + 0.01, "no hue shift on low ground"
    # ...but the same lightness (Imhof blend: hue from cover, light from relief)
    lum = lambda a: a.mean(axis=2)
    assert abs(lum(low_b).mean() - lum(low_p).mean()) < 3.0, "luminance not preserved"
    # summits (norm > ALPINE_FADE_END): the near-white hypsometric treatment survives
    top_p, top_b = plain[-12:], biome[-12:]
    assert np.abs(top_b - top_p).mean() < 1.0, "alpine fade failed; summits tinted"


def _write_region(root, rid, with_landcover, lc_class=42):
    b = (600000.0, 4400000.0, 632000.0, 4432000.0)   # 32x32 km
    d = os.path.join(root, rid)
    os.makedirs(d, exist_ok=True)
    cfg = {"id": rid, "name": rid, "crs": "EPSG:32610", "bounds": list(b),
           "overview_size": [100, 100], "dem_path": "dem.tif",
           "native_resolution_m": 10, "elevation_min": 1000.0,
           "elevation_max": 2000.0, "light_azimuth": 315, "light_altitude": 45,
           "z_factor": 1.0}
    with open(os.path.join(d, "region.json"), "w") as f:
        json.dump(cfg, f)
    elev = _ramp(200, 200)
    prof = dict(driver="GTiff", dtype="float32", count=1, height=200, width=200,
                crs="EPSG:32610", transform=from_bounds(*b, 200, 200), nodata=np.nan)
    with rasterio.open(os.path.join(d, "dem.tif"), "w", **prof) as f:
        f.write(elev, 1)
    if with_landcover:
        lc = np.full((200, 200), lc_class, "uint8")
        prof2 = dict(prof, dtype="uint8", nodata=0)
        with rasterio.open(os.path.join(d, "landcover.tif"), "w", **prof2) as f:
            f.write(lc, 1)
    return d, cfg, b


def _spec(b):
    return CompositionSpec(region_id="t", crs="EPSG:32610", crop=tuple(b),
                           print_w_in=10, print_h_in=10, native_resolution_m=10,
                           tracks=[], hotspots=[], seed=7, title_text="-",
                           compass=False)


def test_rasterize_biome_falls_back_without_landcover(tmp_path):
    d, cfg, b = _write_region(str(tmp_path), "nolc", with_landcover=False)
    spec = _spec(b)
    off = render.rasterize(spec, dpi=96, region_dir=d, hydro={"lakes": [], "rivers": []})
    spec.biome = True                                # asset absent -> graceful fallback
    on = render.rasterize(spec, dpi=96, region_dir=d, hydro={"lakes": [], "rivers": []})
    assert np.array_equal(np.asarray(off), np.asarray(on))


def test_rasterize_biome_tints_with_landcover(tmp_path):
    d, cfg, b = _write_region(str(tmp_path), "lc", with_landcover=True, lc_class=42)
    spec = _spec(b)
    plain = np.asarray(render.rasterize(spec, dpi=96, region_dir=d,
                                        hydro={"lakes": [], "rivers": []}), np.float32)
    spec.biome = True
    tinted = np.asarray(render.rasterize(spec, dpi=96, region_dir=d,
                                         hydro={"lakes": [], "rivers": []}), np.float32)
    assert not np.array_equal(plain, tinted), "biome toggle changed nothing"
    gf = lambda a: (a[..., 1] / (a.sum(axis=2) + 1e-6))[20:60].mean()
    assert gf(tinted) > gf(plain), "evergreen cover did not read greener"


def test_biome_layers_registration_and_edges(tmp_path):
    # a half-forest / half-shrub landcover: the tint field must place each class on
    # its own side (registration) with a softened boundary (no hard 30 m stairstep)
    d, cfg, b = _write_region(str(tmp_path), "split", with_landcover=True)
    lc = np.full((200, 200), 42, "uint8")
    lc[:, 100:] = 52                                 # east half shrub
    prof = dict(driver="GTiff", dtype="uint8", count=1, height=200, width=200,
                crs="EPSG:32610", transform=from_bounds(*b, 200, 200), nodata=0)
    with rasterio.open(os.path.join(d, "landcover.tif"), "w", **prof) as f:
        f.write(lc, 1)
    shape = (240, 240)
    out = render._biome_layers(d, cfg, tuple(b), (20, 20), shape, dpi=96)
    assert out is not None
    tint, weight = out
    ever = np.array(relief.BIOME_TINT[42], np.float32) / 255.0
    shrub = np.array(relief.BIOME_TINT[52], np.float32) / 255.0
    assert np.abs(tint[120, 60] - ever).max() < 0.02, "west half not evergreen"
    assert np.abs(tint[120, 200] - shrub).max() < 0.02, "east half not shrub"
    assert weight[120, 120] > 0.5
    # softened boundary: mid-column tint sits BETWEEN the two class colors
    mid = tint[120, 118:124].mean(axis=0)
    assert (mid > np.minimum(ever, shrub) - 0.02).all()
    assert (mid < np.maximum(ever, shrub) + 0.02).all()


def test_biome_layers_none_when_absent(tmp_path):
    d, cfg, b = _write_region(str(tmp_path), "none", with_landcover=False)
    assert render._biome_layers(d, cfg, tuple(b), (10, 10), (120, 120), 96) is None
