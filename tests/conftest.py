# tests/conftest.py
"""Make the DEM-gated integration suites runnable on a fresh clone / in CI.

The real 3DEP DEMs are large and gitignored (see region_prep.py), so historically
the endpoint / render / registration suites skipped everywhere except a machine
that had run region_prep.py. That is the highest-value 29% of the suite silently
not running (red-team V1-4).

This module hydrates every built region with a *tiny synthetic* DEM whose bounds
match its region.json exactly (single source of truth), a deterministic smooth
elevation surface inside [elevation_min, elevation_max], and a `synthetic=1`
GeoTIFF tag so downstream code can tell it apart from a real DEM. It only builds a
DEM that is missing, so a machine with real 3DEP data is left untouched. The file
stays gitignored — it is a test artifact, never committed.
"""
from __future__ import annotations
import json
import os
import tempfile

# Isolate the app's writable stores BEFORE any test module imports app.main: the
# endpoint tests used to write finals into the repo's live blobs/ and uploads/
# (417 MB accumulated) and every put() swept the operator's real store (red-team).
os.environ.setdefault("TECOPA_BLOBS",
                      tempfile.mkdtemp(prefix="tecopa-test-blobs-"))
os.environ.setdefault("TECOPA_UPLOADS",
                      tempfile.mkdtemp(prefix="tecopa-test-uploads-"))

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_bounds

REGIONS_ROOT = os.environ.get("TECOPA_REGIONS", "regions")

# Coarse on purpose: a synthetic DEM only has to cover the region and read cleanly
# through rasterio's windowed/boundless path. The zoom cap is judged against
# region.json's native_resolution_m, not the DEM's own grid, so a coarse synthetic
# grid still exercises the same code paths as a 10 m real DEM.
_SYNTH_NX = 240
_SYNTH_NY = 300


def _synthetic_surface(nx: int, ny: int, emin: float, emax: float) -> np.ndarray:
    """A smooth, fully-finite elevation field in [emin, emax]. Deterministic (no RNG)
    so the committed tests are stable and relief/hillshade have real gradients to
    shade — a flat plane would make the hillshade azimuth test meaningless."""
    v, u = np.mgrid[0:ny, 0:nx].astype("float64")
    u /= max(1, nx - 1)
    v /= max(1, ny - 1)
    hills = 0.5 + 0.5 * np.sin(2 * np.pi * 1.5 * u) * np.cos(2 * np.pi * 1.5 * v)
    peak = np.exp(-(((u - 0.5) ** 2 + (v - 0.5) ** 2) / 0.08))
    s = np.clip(0.6 * hills + 0.4 * peak, 0.0, 1.0)
    return (emin + (emax - emin) * s).astype("float32")


def _build_synthetic_dem(region_dir: str, cfg: dict) -> None:
    west, south, east, north = cfg["bounds"]
    emin = float(cfg.get("elevation_min", 1000.0))
    emax = float(cfg.get("elevation_max", 2000.0))
    if emax <= emin:
        emax = emin + 1000.0
    data = _synthetic_surface(_SYNTH_NX, _SYNTH_NY, emin, emax)
    transform = from_bounds(west, south, east, north, _SYNTH_NX, _SYNTH_NY)
    profile = dict(driver="GTiff", dtype="float32", count=1,
                   height=_SYNTH_NY, width=_SYNTH_NX, crs=cfg["crs"],
                   transform=transform, nodata=np.nan, tiled=True,
                   blockxsize=128, blockysize=128, compress="deflate")
    out = os.path.join(region_dir, cfg.get("dem_path", "dem.tif"))
    with rasterio.open(out, "w", **profile) as ds:
        ds.write(data, 1)
        ds.build_overviews([2, 4], Resampling.average)
        ds.update_tags(synthetic="1")   # marks this as a test DEM, not real terrain


def _hydrate_regions(root: str = REGIONS_ROOT) -> None:
    if not os.path.isdir(root):
        return
    for rid in sorted(os.listdir(root)):
        rdir = os.path.join(root, rid)
        cfg_path = os.path.join(rdir, "region.json")
        if not os.path.exists(cfg_path):
            continue
        with open(cfg_path) as f:
            cfg = json.load(f)
        dem_path = os.path.join(rdir, cfg.get("dem_path", "dem.tif"))
        if not os.path.exists(dem_path):
            _build_synthetic_dem(rdir, cfg)


def dem_is_synthetic(dem_path: str) -> bool:
    """True if the DEM at `dem_path` is one this harness built (tagged synthetic=1).
    Lets a real-terrain assertion (e.g. the control-point elevation test) skip when
    only a synthetic DEM is present."""
    if not os.path.exists(dem_path):
        return False
    with rasterio.open(dem_path) as ds:
        return ds.tags().get("synthetic") == "1"


# Hydrate at import (before any test module is collected or app.main is imported),
# so the integration suites find a DEM without needing a session fixture to run first.
_hydrate_regions()
