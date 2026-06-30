# app/regions.py
"""The region registry: discover every built region under regions/ and expose it
to the app. region_prep.py already writes a self-describing region.json per region
(id, name, crs, bounds, overview); this turns that directory into a lookup so the
app is no longer pinned to one hardcoded region.

A Region bundles the three things the rest of the app needs together: the parsed
config, a RegionGeo for coordinate math, and the on-disk directory render reads
DEM/hydro from. Nothing here loads the DEM -- that stays a lazy read in render."""
from __future__ import annotations
import json, os
from pyproj import Transformer
from app.geo import RegionGeo

REGIONS_ROOT = "regions"

def _lonlat_bbox(crs: str, bounds: tuple) -> tuple:
    """Approximate lon/lat bounding box of a region from its CRS-metre bounds, by
    projecting the four corners back to EPSG:4326. Used to route an upload to the
    region whose ground it actually falls on (auto-detect)."""
    inv = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    xs = [bounds[0], bounds[2], bounds[2], bounds[0]]
    ys = [bounds[1], bounds[1], bounds[3], bounds[3]]
    lons, lats = inv.transform(xs, ys)
    return (min(lons), min(lats), max(lons), max(lats))

class Region:
    def __init__(self, rid: str, root: str = REGIONS_ROOT):
        self.id = rid
        self.dir = os.path.join(root, rid)
        with open(os.path.join(self.dir, "region.json")) as f:
            self.cfg = json.load(f)
        self.geo = RegionGeo(crs=self.cfg["crs"], bounds=tuple(self.cfg["bounds"]),
                             overview_size=tuple(self.cfg["overview_size"]))
        self.lonlat_bbox = _lonlat_bbox(self.cfg["crs"], self.cfg["bounds"])

    @property
    def name(self) -> str:
        return self.cfg.get("name", self.id)

    def contains_lonlat(self, lon: float, lat: float) -> bool:
        w, s, e, n = self.lonlat_bbox
        return w <= lon <= e and s <= lat <= n

    def meta(self) -> dict:
        """Lightweight metadata for the region-picker UI (no DEM, no geometry)."""
        return {"id": self.id, "name": self.name,
                "bounds": list(self.cfg["bounds"]),
                "overview_size": list(self.cfg["overview_size"]),
                "overview": f"/regions/{self.id}/overview.png",
                "lonlat_bbox": list(self.lonlat_bbox)}

def discover(root: str = REGIONS_ROOT) -> dict:
    """Map region_id -> Region for every regions/<id>/region.json present."""
    out: dict[str, Region] = {}
    if not os.path.isdir(root):
        return out
    for rid in sorted(os.listdir(root)):
        if os.path.exists(os.path.join(root, rid, "region.json")):
            out[rid] = Region(rid, root)
    return out

def detect_region(regions: dict, lonlat_points) -> Region | None:
    """Pick the region containing the most of the given (lon, lat) points. Ties go
    to the first by id (discover() returns sorted); None if nothing lands anywhere."""
    best, best_n = None, 0
    for r in regions.values():
        n = sum(1 for lon, lat in lonlat_points if r.contains_lonlat(lon, lat))
        if n > best_n:
            best, best_n = r, n
    return best
