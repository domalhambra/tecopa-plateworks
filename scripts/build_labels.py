#!/usr/bin/env python3
"""Build regions/<id>/labels.json -- the named-geography layer (GNIS terrain features).

Offline, like region_prep. Queries the USGS ArcGIS GNIS "Landforms" layer (summits,
ranges, valleys, gaps/passes, flats, basins, ridges) for the region's recorded fetch
bbox (regions/<id>/sources.json -> fetch_bbox_4326), projects the names into the region
CRS, ranks and de-dupes them, and writes labels.json. Water names ship already in
hydro.json (GNIS names on lakes/rivers), so this file is terrain-only; the renderer
merges the two. The DEM is not touched, so this regenerates cleanly for any built
region without a rebuild.

    python scripts/build_labels.py                 # every region under regions/
    python scripts/build_labels.py rifle_aspen     # one region
"""
import gzip
import json
import os
import sys
import urllib.parse
import urllib.request

# GNIS Landforms layer (feature-class in gaz_featureclass). Layer 5 of the geonames
# service. We keep the classes that read as terrain on a relief poster and rank them:
# a range name is the headline (big tracked caps); a peak is iconic; passes/valleys are
# supporting; ridges/benches are noise on a small sheet.
LANDFORMS_URL = ("https://carto.nationalmap.gov/arcgis/rest/services/geonames/"
                 "MapServer/5/query")
# gaz_featureclass -> (kind, rank). Higher rank wins a collision.
CLASS_RANK = {
    "Range": ("range", 100),
    "Summit": ("summit", 70),
    "Gap": ("gap", 55),          # passes / saddles
    "Basin": ("basin", 45),
    "Flat": ("flat", 42),        # playa / desert flats (the NV/UT sheets)
    "Valley": ("valley", 40),
    # Ridge deliberately excluded: rank-30 noise that the density cap never places,
    # and on a corridor region (elko) it was ~200 features of pure file bloat.
}


def _get_json(url, params):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(url + "?" + q, headers={
        "Accept-Encoding": "gzip", "User-Agent": "trailprint-labels/1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw)


def fetch_landforms(bbox_4326):
    """[(name, kind, rank, [(lon,lat), ...])] for the bbox. Paginates the ArcGIS
    service (2000-row default cap) so a dense region isn't silently truncated."""
    west, south, east, north = bbox_4326
    out, offset = [], 0
    while True:
        d = _get_json(LANDFORMS_URL, {
            "geometry": f"{west},{south},{east},{north}",
            "geometryType": "esriGeometryEnvelope", "inSR": "4326", "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects", "where": "1=1", "outFields": "*",
            "returnGeometry": "true", "resultOffset": offset,
            "resultRecordCount": 1000, "f": "json"})
        feats = d.get("features", [])
        for ft in feats:
            a = ft.get("attributes", {})
            name = (a.get("gaz_name") or "").strip()
            cls = a.get("gaz_featureclass")
            if not name or cls not in CLASS_RANK:
                continue
            geom = ft.get("geometry") or {}
            pts = geom.get("points")
            if not pts:
                continue
            kind, rank = CLASS_RANK[cls]
            out.append((name, kind, rank, [(float(x), float(y)) for x, y in pts]))
        if len(feats) < 1000 or not d.get("exceededTransferLimit"):
            break
        offset += len(feats)
    return out


def bake_labels(features, dst_crs):
    """Project the lon/lat features into the region CRS and shape them for labels.json.
    Point features (summit/gap) keep their anchor; multi-point features (range/valley)
    keep the run so the renderer can place along it. De-dupe by (name, kind) keeping the
    longest geometry -- GNIS returns a range in several rows."""
    from pyproj import Transformer
    fwd = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
    best = {}
    for name, kind, rank, lonlat in features:
        xs, ys = fwd.transform([p[0] for p in lonlat], [p[1] for p in lonlat])
        coords = [[round(x, 2), round(y, 2)] for x, y in zip(xs, ys)]
        key = (name.lower(), kind)
        if key not in best or len(coords) > len(best[key]["coords"]):
            best[key] = {"name": name, "kind": kind, "rank": rank, "coords": coords}
    # rank desc, then name for a stable file
    return sorted(best.values(), key=lambda f: (-f["rank"], f["name"]))


def build_region(region_dir):
    rid = os.path.basename(region_dir.rstrip("/"))
    cfg = json.load(open(os.path.join(region_dir, "region.json")))
    src = json.load(open(os.path.join(region_dir, "sources.json")))
    bbox = src["fetch_bbox_4326"]
    print(f"[{rid}] fetching GNIS landforms for bbox {bbox} ...")
    feats = fetch_landforms(bbox)
    baked = bake_labels(feats, cfg["crs"])
    from collections import Counter
    counts = Counter(f["kind"] for f in baked)
    out = {"crs": cfg["crs"], "features": baked}
    with open(os.path.join(region_dir, "labels.json"), "w") as f:
        json.dump(out, f)
    print(f"[{rid}] wrote {len(baked)} labels {dict(counts)}")


def main():
    root = "regions"
    ids = sys.argv[1:] or sorted(d for d in os.listdir(root)
                                 if os.path.isdir(os.path.join(root, d)))
    for rid in ids:
        build_region(os.path.join(root, rid))


if __name__ == "__main__":
    main()
