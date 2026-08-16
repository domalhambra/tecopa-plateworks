#!/usr/bin/env python3
"""Fetch one plate's road/trail network from Overpass into the gitignored cache.

    ./.venv/bin/python scripts/fetch_track_network.py --region lassen_ca

ODbL data stays in cache/networks/ (gitignored); it must never be committed and
never enter a plate (plates are CC0). The cache is the snapshot of record:
renders read it, never live Overpass, so same cache + seed -> same image.
Network-touching and hand-verified, same policy as region_prep.py.

The written file's `ways` array is canonical -- ways deduped by OSM id, sorted by
id, coordinates rounded to 0.1 m (`Graph.key`'s own rounding) -- so re-fetching an
unchanged plate reproduces it byte for byte. `ways_sha256` in the header makes
that checkable; `fetched` is the one field that moves on every run, by design."""
from __future__ import annotations

# certifi BEFORE any network import, same reason and same ordering as
# region_prep.py: this Mac's framework Python ships no root certificates, so a
# bare urlopen dies with CERTIFICATE_VERIFY_FAILED. The explicit SSLContext
# below is the belt to this braces -- env vars only bind when a default context
# happens to be built after they are set.
import os
import certifi
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("SSL_CERT_DIR", "")

import argparse
import hashlib
import json
import math
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timezone, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.regions import Region                                  # noqa: E402

SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]
# A real contact string is Overpass etiquette; the bare python-urllib UA is what
# mirrors throttle first.
USER_AGENT = ("tecopa-plateworks/1 (poster engine, one fetch per plate; "
              "https://github.com/domalhambra/tecopa-plateworks)")

HIGHWAYS = ("motorway|trunk|primary|secondary|tertiary|unclassified|residential|"
            "service|track|path|footway|bridleway|cycleway")
# Measured on a 0.01 deg^2 square over central Reno (the densest corner of any
# plate): 20,220 ways unfiltered, 10,504 with these two exclusions. Half the
# urban network is parking aisles, driveways and sidewalks -- graph weight and
# routing cost with nothing to show on a poster. Overpass's negated regex also
# matches when the key is ABSENT, so a way with no `service`/`footway` subtype
# still passes, which is exactly the backcountry case we are keeping.
SERVICE_EXCLUDE = "parking_aisle|driveway|drive-through|parking|alley|emergency_access"
FOOTWAY_EXCLUDE = "sidewalk|crossing|traffic_island|link"

CLASSES = {"track": "4wd", "path": "trail", "footway": "trail",
           "bridleway": "trail", "cycleway": "trail"}             # else: road

# Tiling. elko_bonneville is 5.835 x 3.117 deg (18.2 deg^2) and swallows Salt
# Lake City, Provo and Ogden: 322,468 ways after filtering, ~290 MB of `out geom`
# in one response. That is a request no public mirror should be asked to serve,
# so plates above MAX_TILE_DEG2 are split into a grid and fetched sequentially
# with a pause. Small plates stay a single request, which is the spec's rule.
MAX_TILE_DEG2 = 1.0
TILE_PAUSE_S = 5.0          # overpass-api.de allots ~2 slots per IP and answers
                            # a third with 429; measured, not guessed

QUERY_TIMEOUT_S = 600       # Overpass-side [timeout:] -- how long it may compute
SOCKET_TIMEOUT_S = 900      # client-side -- must exceed the above plus transfer
ATTEMPTS = 4
BACKOFF_S = 20              # 20, 40, 60 between attempts (never after the last)
COORD_DECIMALS = 1          # decimetres: `Graph.key` rounds to 0.1 m, so this is
                            # the finest resolution the graph can even represent
MANIFEST_SOURCE = "OpenStreetMap via Overpass, ODbL 1.0"
ATTRIBUTION = "© OpenStreetMap contributors"
CACHE_DIR = os.path.join("cache", "networks")


# --------------------------------------------------------------------------
# pure helpers (unit-tested in tests/test_track_network.py -- no network)
# --------------------------------------------------------------------------
def overpass_bbox(lonlat_bbox) -> tuple:
    """`Region.lonlat_bbox` is (west, south, east, north); Overpass wants
    (south, west, north, east). Transposing these silently returns the wrong
    part of the planet -- or, off the coast of Africa, nothing at all -- so the
    conversion lives in one named function with a test on it."""
    w, s, e, n = lonlat_bbox
    return (s, w, n, e)


def tile_bboxes(lonlat_bbox, max_deg2: float = MAX_TILE_DEG2) -> list:
    """Split a (w, s, e, n) lon/lat box into Overpass-ordered (s, w, n, e) tiles,
    each no larger than `max_deg2`, in a fixed row-major order.

    Tiles overlap in content, not in extent: Overpass's bbox filter selects any
    way with a node inside, and `out geom` then returns that way's FULL
    geometry, so a way straddling a seam comes back whole from both tiles. The
    caller dedupes by OSM id, which is why no clipping or stitching is needed."""
    w, s, e, n = lonlat_bbox
    width, height = abs(e - w), abs(n - s)
    if width <= 0 or height <= 0:
        return [overpass_bbox(lonlat_bbox)]
    side = math.sqrt(max_deg2)
    nx = max(1, math.ceil(width / side))
    ny = max(1, math.ceil(height / side))
    dx, dy = width / nx, height / ny
    tiles = []
    for j in range(ny):
        for i in range(nx):
            tw = w + i * dx
            ts = s + j * dy
            # snap the far edges to the true bounds so float drift can't leave a
            # hairline gap along the top/right of the plate
            te = e if i == nx - 1 else w + (i + 1) * dx
            tn = n if j == ny - 1 else s + (j + 1) * dy
            tiles.append((ts, tw, tn, te))
    return tiles


def way_class(tags: dict) -> str:
    """OSM tags -> our three-way class. `highway=track` is 4wd, the foot/bike
    family is trail, everything else in the query is road."""
    return CLASSES.get((tags or {}).get("highway", ""), "road")


def overpass_query(bbox_swne, timeout: int = QUERY_TIMEOUT_S) -> str:
    s, w, n, e = bbox_swne
    return (f'[out:json][timeout:{timeout}];'
            f'way["highway"~"^({HIGHWAYS})$"]'
            f'["service"!~"^({SERVICE_EXCLUDE})$"]'
            f'["footway"!~"^({FOOTWAY_EXCLUDE})$"]'
            f'({s:.6f},{w:.6f},{n:.6f},{e:.6f});'
            f'out geom;')


def collect_ways(elements, into: dict) -> int:
    """Fold one payload's elements into `into` (osm id -> (class, lons, lats)).
    Returns how many ids were new. Ways under two points are dropped; a repeat
    id from an overlapping tile is identical geometry and is skipped."""
    added = 0
    for el in elements or []:
        if el.get("type") != "way":
            continue
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        wid = el.get("id")
        if wid is None or wid in into:
            continue
        # a clipped tile edge can hand back a null placeholder inside geometry
        pts = [p for p in geom if p and p.get("lon") is not None
               and p.get("lat") is not None]
        if len(pts) < 2:
            continue
        into[wid] = (way_class(el.get("tags")),
                     [float(p["lon"]) for p in pts],
                     [float(p["lat"]) for p in pts])
        added += 1
    return added


def project_ways(by_id: dict, crs: str) -> list:
    """(osm id -> (class, lons, lats)) -> the manifest's `ways` list, in region
    CRS metres, sorted by OSM id so the file is reproducible.

    Consecutive duplicate points after rounding are collapsed: `build_graph`
    already skips zero-length segments, so this changes no graph and only makes
    the file smaller and canonical."""
    from pyproj import Transformer
    fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    ids = sorted(by_id)
    if not ids:
        return []
    flat_lon, flat_lat, spans = [], [], []
    for wid in ids:
        _cls, lons, lats = by_id[wid]
        spans.append(len(lons))
        flat_lon.extend(lons)
        flat_lat.extend(lats)
    xs, ys = fwd.transform(flat_lon, flat_lat)      # one call: 3M points is fine
    ways, cursor = [], 0
    for wid, span in zip(ids, spans):
        coords = []
        for x, y in zip(xs[cursor:cursor + span], ys[cursor:cursor + span]):
            if not (math.isfinite(x) and math.isfinite(y)):
                continue                            # off-projection node
            pt = [round(x, COORD_DECIMALS), round(y, COORD_DECIMALS)]
            if coords and coords[-1] == pt:
                continue
            coords.append(pt)
        cursor += span
        if len(coords) >= 2:
            ways.append({"class": by_id[wid][0], "coords": coords})
    return ways


def class_counts(ways) -> dict:
    counts = {"road": 0, "4wd": 0, "trail": 0}
    for w in ways:
        counts[w["class"]] = counts.get(w["class"], 0) + 1
    return counts


# --------------------------------------------------------------------------
# network
# --------------------------------------------------------------------------
class OverpassError(RuntimeError):
    pass


def _post(url: str, query: str) -> dict:
    """One Overpass POST. Raises OverpassError with a readable reason; the
    caller decides what is worth retrying."""
    body = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"User-Agent": USER_AGENT,
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=SOCKET_TIMEOUT_S,
                                    context=SSL_CONTEXT) as r:
            raw = r.read()
    except urllib.error.HTTPError as ex:
        detail = ""
        try:
            detail = ex.read()[:400].decode("utf-8", "replace").strip()
        except Exception:
            pass
        retry_after = ex.headers.get("Retry-After") if ex.headers else None
        raise OverpassError(f"HTTP {ex.code} {ex.reason}"
                            + (f" (Retry-After: {retry_after})" if retry_after else "")
                            + (f" -- {detail}" if detail else "")) from ex
    return _post_from_bytes(raw)


def _post_from_bytes(raw: bytes) -> dict:
    """Overpass answers a rejected or overloaded query with 200 and an HTML
    error page more often than it answers with a status code. json.load would
    surface that as a bare JSONDecodeError pointing at column 1, which tells an
    operator nothing, so name it here."""
    head = raw[:512].lstrip()[:200]      # slice first: a tile can be 100 MB and
                                         # lstrip() on the whole body copies it
    if head[:1] not in (b"{", b"["):
        snippet = head.decode("utf-8", "replace").replace("\n", " ")[:200]
        raise OverpassError(f"non-JSON response ({len(raw)} bytes): {snippet}")
    try:
        return json.loads(raw)
    except ValueError as ex:
        raise OverpassError(f"malformed JSON ({len(raw)} bytes): {ex}") from ex


def _fatal(err: OverpassError) -> bool:
    """A 400 is a bad query -- retrying it just burns someone else's slot."""
    return str(err).startswith("HTTP 400")


def fetch_tile(query: str, endpoints=ENDPOINTS, attempts: int = ATTEMPTS,
               sleep=time.sleep) -> dict:
    """One tile, retried with linear backoff across every endpoint in turn.

    Written as a flat loop over (endpoint, attempt) rather than the nested
    for/else the sketch used. That nesting is correct Python but sleeps a full
    backoff after the FINAL attempt on every endpoint -- three wasted minutes on
    a dead network before the honest error appears -- and it hides which
    endpoint failed how."""
    last = None
    for url in endpoints:
        for attempt in range(1, attempts + 1):
            try:
                return _post(url, query)
            except OverpassError as ex:
                last = ex
                host = urllib.parse.urlparse(url).netloc
                print(f"    ! {host} attempt {attempt}/{attempts}: {ex}",
                      file=sys.stderr)
                if _fatal(ex):
                    raise
                if attempt < attempts:            # never sleep after the last try
                    sleep(BACKOFF_S * attempt)
    raise OverpassError(f"every Overpass endpoint failed; last error: {last}\n"
                        f"    mirrors: https://wiki.openstreetmap.org/wiki/Overpass_API"
                        f"#Public_Overpass_API_instances")


def fetch(region: Region, max_tile_deg2: float = MAX_TILE_DEG2,
          raw_dir: str | None = None) -> dict:
    """Every tile of one plate, folded into a single manifest dict."""
    tiles = tile_bboxes(region.lonlat_bbox, max_tile_deg2)
    area = ((region.lonlat_bbox[2] - region.lonlat_bbox[0])
            * (region.lonlat_bbox[3] - region.lonlat_bbox[1]))
    print(f"  bbox {tuple(round(v, 4) for v in region.lonlat_bbox)} "
          f"= {area:.2f} deg^2 -> {len(tiles)} tile(s)")
    if raw_dir:
        os.makedirs(raw_dir, exist_ok=True)

    by_id: dict[int, tuple] = {}
    for i, tile in enumerate(tiles, 1):
        query = overpass_query(tile)
        cached = os.path.join(raw_dir, f"tile-{i:03d}.json") if raw_dir else None
        t0 = time.time()
        if cached and os.path.exists(cached):
            with open(cached) as f:
                payload = json.load(f)
            note = "raw cache"
        else:
            if i > 1:
                time.sleep(TILE_PAUSE_S)          # one plate should not look
                                                  # like a scrape
            payload = fetch_tile(query)
            note = "fetched"
            if cached:
                with open(cached, "w") as f:
                    json.dump(payload, f)
        added = collect_ways(payload.get("elements"), by_id)
        print(f"  tile {i}/{len(tiles)} {note}: "
              f"{len(payload.get('elements') or []):,} elements, "
              f"{added:,} new ways ({len(by_id):,} total) in {time.time() - t0:.1f}s")

    ways = project_ways(by_id, region.cfg["crs"])
    blob = json.dumps(ways, separators=(",", ":"), sort_keys=True).encode()
    return {"region_id": region.id,
            "crs": region.cfg["crs"],
            "lonlat_bbox": [round(v, 6) for v in region.lonlat_bbox],
            "fetched": date.today().isoformat(),
            "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": MANIFEST_SOURCE,
            "attribution": ATTRIBUTION,
            "license": "ODbL-1.0",
            "query": {"highways": HIGHWAYS,
                      "service_excluded": SERVICE_EXCLUDE,
                      "footway_excluded": FOOTWAY_EXCLUDE,
                      "tiles": len(tiles),
                      "coord_decimals": COORD_DECIMALS},
            "counts": class_counts(ways),
            "ways_sha256": hashlib.sha256(blob).hexdigest(),
            "ways": ways}


def write_cache(manifest: dict, out_dir: str = CACHE_DIR) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{manifest['region_id']}.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(manifest, f, separators=(",", ":"))
    os.replace(tmp, path)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--region", required=True, help="plate id, e.g. lassen_ca")
    ap.add_argument("--out", default=CACHE_DIR,
                    help=f"cache directory (default {CACHE_DIR}; gitignored)")
    ap.add_argument("--max-tile-deg2", type=float, default=MAX_TILE_DEG2,
                    help="split the bbox into tiles no larger than this")
    ap.add_argument("--raw-cache", action="store_true",
                    help="keep/reuse raw Overpass payloads under "
                         "cache/overpass-raw/<region>/ so re-runs while "
                         "debugging do not hit the servers again")
    args = ap.parse_args(argv)

    if not os.path.isdir("regions"):
        print("run this from the repo root (no ./regions here)", file=sys.stderr)
        return 2
    try:
        region = Region(args.region)
    except FileNotFoundError:
        print(f"unknown plate {args.region!r}; built plates: "
              f"{', '.join(sorted(os.listdir('regions')))}", file=sys.stderr)
        return 2

    raw_dir = (os.path.join("cache", "overpass-raw", region.id)
               if args.raw_cache else None)
    print(f"fetching {region.id} ({region.name})")
    t0 = time.time()
    try:
        manifest = fetch(region, args.max_tile_deg2, raw_dir)
    except OverpassError as ex:
        print(f"fetch failed: {ex}", file=sys.stderr)
        return 1
    path = write_cache(manifest, args.out)

    c = manifest["counts"]
    size = os.path.getsize(path)
    print(f"wrote {path}  {size / 1e6:.1f} MB  "
          f"{len(manifest['ways']):,} ways "
          f"(road {c['road']:,} / 4wd {c['4wd']:,} / trail {c['trail']:,})  "
          f"in {time.time() - t0:.1f}s")
    print(f"  ways_sha256 {manifest['ways_sha256'][:16]}...  "
          f"ODbL -- gitignored, never commit this")
    empty = [k for k, v in c.items() if not v]
    if empty:
        print(f"  ! no ways of class {', '.join(empty)} -- check the query",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
