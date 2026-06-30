# TrailPrint v1 Architecture Completion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the v1 architecture — KML/KMZ import, a multi-file drag-drop upload, baked hydrography (lakes + major rivers), and a properly-sized, NaN-trimmed Lassen region — so TrailPrint produces a finished, printable 18×24 map.

**Architecture:** Preserve the compose→rasterize seam and all six invariants. Region data (DEM, water) is read from the region dir by `render`, not carried on the spec. Hydrography is vector (drawn in physical units at paint time), so it scales correctly across DPIs. Ingest gains a format-dispatching `load_tracks` over a shared `_make_track` helper.

**Tech Stack:** Python 3.14, rasterio/rioxarray, pyproj, shapely, geopandas, gpxpy, lxml (KML), pynhd (NHD water), Pillow, FastAPI. Tests: pytest + FastAPI TestClient.

**Conventions (this repo):** venv at `.venv` (`./.venv/bin/python -m pytest`). Integration tests that need the built DEM use `pytestmark = pytest.mark.skipif(not os.path.exists(.../dem.tif), ...)`. Commit messages end with the `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer.

---

## Task 1: KML/KMZ ingest (shared `_make_track`, lxml parser, dispatcher)

**Files:**
- Modify: `app/ingest.py`
- Test: `tests/test_ingest.py`

- [ ] **Step 1: Failing tests for KML LineString, gx:Track, KMZ, and dispatch**

Add to `tests/test_ingest.py`:

```python
import io, zipfile

def _kml_linestring(points, name="t"):
    coords = " ".join(f"{lon},{lat},0" for lon, lat in points)
    return (f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>'
            f'<name>{name}</name><LineString><coordinates>{coords}</coordinates>'
            f'</LineString></Placemark></Document></kml>').encode()

def _kml_gx_track(points, day="2024-03-02"):
    whens = "".join(f"<when>{day}T10:0{i}:00Z</when>" for i in range(len(points)))
    coords = "".join(f"<gx:coord>{lon} {lat} 0</gx:coord>" for lon, lat in points)
    return (f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<kml xmlns="http://www.opengis.net/kml/2.2" '
            f'xmlns:gx="http://www.google.com/kml/ext/2.2"><Document><Placemark>'
            f'<gx:Track>{whens}{coords}</gx:Track></Placemark></Document></kml>').encode()

def test_kml_linestring_tracks():
    from app.ingest import load_kml_tracks
    data = _kml_linestring([(-120.66, 40.41), (-120.66, 40.44), (-120.66, 40.47)])
    tracks = load_kml_tracks(data, REGION)
    assert len(tracks) == 1
    assert tracks[0].coords.shape[1] == 2
    assert (tracks[0].coords[:, 0] > 100000).all()        # reprojected to metres

def test_kml_gx_track_with_time():
    from app.ingest import load_kml_tracks
    tracks = load_kml_tracks(_kml_gx_track([(-120.66, 40.41), (-120.66, 40.45)]), REGION)
    assert tracks[0].day == "2024-03-02"

def test_kmz_unzips_and_parses():
    from app.ingest import load_tracks
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("doc.kml", _kml_linestring([(-120.66, 40.41), (-120.66, 40.45)]))
    tracks = load_tracks(buf.getvalue(), REGION, filename="a.kmz")
    assert len(tracks) == 1

def test_load_tracks_dispatches_by_content():
    from app.ingest import load_tracks
    gpx = _gpx([(-120.66, 40.41), (-120.66, 40.45)])           # existing helper
    kml = _kml_linestring([(-120.66, 40.41), (-120.66, 40.45)])
    assert len(load_tracks(gpx, REGION)) == 1
    assert len(load_tracks(kml, REGION)) == 1
```

Note: `tests/test_ingest.py` `REGION` is UTM 12N; this is fine — KML/GPX coords here are near -120.66 which still reproject to finite metres. (The existing `_gpx` helper is reused.)

- [ ] **Step 2: Run, verify fail** — `./.venv/bin/python -m pytest tests/test_ingest.py -q` → FAIL (`load_kml_tracks` / dispatch missing).

- [ ] **Step 3: Refactor + implement in `app/ingest.py`**

Add imports: `import io, zipfile` and `from lxml import etree`. Extract the shared builder and add the KML path:

```python
def _make_track(pts, region, name, idx, simplify_tolerance_m):
    """pts: list of (lon, lat, time) where time is datetime | ISO str | None."""
    pts = [(lo, la, t) for lo, la, t in pts if lo is not None and la is not None]
    if len(pts) < 2:
        return None
    xy = np.array([lonlat_to_crs(region, lo, la) for lo, la, _ in pts])
    xy = xy[np.isfinite(xy).all(axis=1)]
    if xy.shape[0] < 2:
        return None
    line = LineString(xy).simplify(simplify_tolerance_m, preserve_topology=False)
    coords = np.asarray(line.coords)
    if coords.shape[0] < 2:
        return None
    t0 = next((t for _, _, t in pts if t is not None), None)
    day = None
    if t0 is not None:
        day = t0.date().isoformat() if hasattr(t0, "date") else str(t0)[:10]
    return Track(track_id=f"{name or 'track'}-{idx}", coords=coords, day=day)
```

Rewrite `load_gpx_tracks` to build per-segment `pts` and call `_make_track` (behavior unchanged). Then add KML + dispatch:

```python
def _localname(el):
    return etree.QName(el).localname

def _kml_segments(root):
    """Yield pts lists for every LineString and gx:Track, namespace-agnostic."""
    segs = []
    for el in root.iter():
        ln = _localname(el)
        if ln == "LineString":
            coord_el = next((c for c in el if _localname(c) == "coordinates"), None)
            if coord_el is None or not coord_el.text:
                continue
            pts = []
            for tok in coord_el.text.split():
                p = tok.split(",")
                if len(p) >= 2:
                    pts.append((float(p[0]), float(p[1]), None))
            if len(pts) >= 2:
                segs.append(pts)
        elif ln == "Track":   # gx:Track: parallel <when> and <gx:coord> children
            whens, coords = [], []
            for c in el:
                cl = _localname(c)
                if cl == "when":
                    whens.append(c.text)
                elif cl == "coord" and c.text:
                    xy = c.text.split()
                    if len(xy) >= 2:
                        coords.append((float(xy[0]), float(xy[1])))
            if len(coords) >= 2:
                times = whens + [None] * (len(coords) - len(whens))
                segs.append([(lon, lat, times[i]) for i, (lon, lat) in enumerate(coords)])
    return segs

def load_kml_tracks(data, region, simplify_tolerance_m=15.0):
    root = etree.fromstring(data)
    out = []
    for idx, pts in enumerate(_kml_segments(root)):
        t = _make_track(pts, region, "track", idx, simplify_tolerance_m)
        if t is not None:
            out.append(t)
    return out

def _kmz_to_kml(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        target = "doc.kml" if "doc.kml" in names else next((n for n in names if n.lower().endswith(".kml")), None)
        if target is None:
            raise ValueError("no .kml inside KMZ")
        return z.read(target)

def load_tracks(data, region, filename=None, simplify_tolerance_m=15.0):
    """Auto-detect GPX / KML / KMZ and return a list[Track]."""
    if data[:4] == b"PK\x03\x04":                      # zip -> KMZ
        return load_kml_tracks(_kmz_to_kml(data), region, simplify_tolerance_m)
    head = data[:400].lower()
    if b"<gpx" in head:
        return load_gpx_tracks(data, region, simplify_tolerance_m)
    if b"<kml" in head:
        return load_kml_tracks(data, region, simplify_tolerance_m)
    fn = (filename or "").lower()                       # fall back to extension
    if fn.endswith(".gpx"):
        return load_gpx_tracks(data, region, simplify_tolerance_m)
    if fn.endswith((".kml", ".kmz")):
        return load_kml_tracks(data, region, simplify_tolerance_m)
    return load_gpx_tracks(data, region, simplify_tolerance_m)
```

- [ ] **Step 4: Run, verify pass** — `./.venv/bin/python -m pytest tests/test_ingest.py -q` → PASS (all, incl. existing GPX).

- [ ] **Step 5: Commit**

```bash
git add app/ingest.py tests/test_ingest.py
git commit -m "Ingest: KML/KMZ support via shared _make_track + format dispatch"
```

---

## Task 2: Hydrography bake function (pure, testable)

**Files:**
- Modify: `region_prep.py`
- Test: `tests/test_hydro.py` (create)

- [ ] **Step 1: Failing test with synthetic geometries**

```python
# tests/test_hydro.py
import geopandas as gpd
from shapely.geometry import Polygon, LineString
from region_prep import bake_hydro

def test_bake_reprojects_and_filters_by_order():
    # one lake polygon + two flowlines (order 2 dropped, order 4 kept), EPSG:4326
    lake = gpd.GeoDataFrame(
        {"gnis_name": ["Eagle Lake"]},
        geometry=[Polygon([(-120.74, 40.60), (-120.72, 40.60), (-120.72, 40.62), (-120.74, 40.62)])],
        crs="EPSG:4326")
    rivers = gpd.GeoDataFrame(
        {"streamorde": [2, 4], "gnis_name": ["Creek", "Susan River"]},
        geometry=[LineString([(-120.70, 40.50), (-120.69, 40.51)]),
                  LineString([(-120.66, 40.41), (-120.66, 40.45)])],
        crs="EPSG:4326")
    hydro = bake_hydro(lake, rivers, "EPSG:32610", min_order=3)
    assert hydro["crs"] == "EPSG:32610"
    assert len(hydro["lakes"]) == 1
    assert hydro["lakes"][0]["coords"][0][0] > 100000          # reprojected metres
    assert len(hydro["rivers"]) == 1                            # order-2 filtered out
    assert hydro["rivers"][0]["order"] == 4

def test_bake_handles_empty():
    hydro = bake_hydro(None, None, "EPSG:32610")
    assert hydro == {"crs": "EPSG:32610", "lakes": [], "rivers": []}
```

- [ ] **Step 2: Run, verify fail** — `./.venv/bin/python -m pytest tests/test_hydro.py -q` → FAIL (`bake_hydro` missing).

- [ ] **Step 3: Implement `bake_hydro` in `region_prep.py`**

```python
from shapely.geometry import mapping  # noqa (or iterate geoms directly)

def _exterior_rings(geom):
    if geom.geom_type == "Polygon":
        return [list(geom.exterior.coords)]
    if geom.geom_type == "MultiPolygon":
        return [list(p.exterior.coords) for p in geom.geoms]
    return []

def _lines(geom):
    if geom.geom_type == "LineString":
        return [list(geom.coords)]
    if geom.geom_type == "MultiLineString":
        return [list(l.coords) for l in geom.geoms]
    return []

def bake_hydro(waterbodies, flowlines, dst_crs, simplify_m=30.0, min_order=3):
    lakes, rivers = [], []
    if waterbodies is not None and len(waterbodies):
        for _, row in waterbodies.to_crs(dst_crs).iterrows():
            g = row.geometry.simplify(simplify_m)
            for ring in _exterior_rings(g):
                lakes.append({"coords": [[float(x), float(y)] for x, y, *_ in ring],
                              "name": str(row.get("gnis_name") or "")})
    if flowlines is not None and len(flowlines):
        fl = flowlines.to_crs(dst_crs)
        col = "streamorde" if "streamorde" in fl.columns else ("StreamOrde" if "StreamOrde" in fl.columns else None)
        for _, row in fl.iterrows():
            order = int(row[col]) if col and row[col] is not None else 0
            if order < min_order:
                continue
            g = row.geometry.simplify(simplify_m)
            for line in _lines(g):
                rivers.append({"coords": [[float(x), float(y)] for x, y, *_ in line],
                               "order": order, "name": str(row.get("gnis_name") or "")})
    return {"crs": dst_crs, "lakes": lakes, "rivers": rivers}
```

- [ ] **Step 4: Run, verify pass** — `./.venv/bin/python -m pytest tests/test_hydro.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add region_prep.py tests/test_hydro.py
git commit -m "Region prep: bake_hydro reprojects/simplifies/filters water into hydro dict"
```

---

## Task 3: Region prep wiring — sizing, clip-to-bbox, hydro fetch, rebuild Lassen

**Files:**
- Modify: `region_prep.py`
- Test: `tests/test_registration.py` (re-run after rebuild)

- [ ] **Step 1: Add bbox clip to `to_cog`** — pass the 4326 bbox and clip the reprojected raster to its UTM box (removes NaN corners):

```python
def to_cog(dem_da, dst_crs, out_path, bbox_4326, resolution_m=10):
    if dem_da.rio.crs is None:
        dem_da = dem_da.rio.write_crs("EPSG:4326")
    dem_da = dem_da.rio.reproject(dst_crs, resolution=resolution_m,
                                  resampling=Resampling.bilinear, nodata=np.nan)
    from pyproj import Transformer
    fwd = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
    w, s, e, n = bbox_4326
    xs, ys = zip(*(fwd.transform(lo, la) for lo, la in [(w, s), (w, n), (e, s), (e, n)]))
    dem_da = dem_da.rio.clip_box(min(xs), min(ys), max(xs), max(ys))
    dst = np.asarray(dem_da.values, dtype="float32")
    dh, dw = dst.shape
    dst_transform = dem_da.rio.transform()
    # ... existing profile + write + build_overviews unchanged ...
```

- [ ] **Step 2: Add `fetch_hydro` and wire `main()`** — fetch NHD, bake, write `hydro.json`; pass bbox to `to_cog`; add `hydro_path` to region.json:

```python
def fetch_hydro(bbox):
    import pynhd
    wb = fl = None
    try:
        wb = pynhd.WaterData("nhdwaterbody").bybox(bbox)
    except Exception as ex:
        print(f"  no waterbodies: {ex}")
    try:
        fl = pynhd.WaterData("nhdflowline_network").bybox(bbox)
    except Exception as ex:
        print(f"  no flowlines: {ex}")
    return wb, fl
```

In `main()`: `cog = to_cog(dem, dst_crs, os.path.join(out_dir,"dem.tif"), tuple(args.bbox))`; then:

```python
    print("Fetching NHD hydrography...")
    wb, fl = fetch_hydro(tuple(args.bbox))
    hydro = bake_hydro(wb, fl, dst_crs)
    with open(os.path.join(out_dir, "hydro.json"), "w") as f:
        json.dump(hydro, f)
    print(f"  lakes: {len(hydro['lakes'])}  rivers: {len(hydro['rivers'])}")
```

Add `"hydro_path": "hydro.json"` to the `region` dict.

- [ ] **Step 3: Verify `pynhd.WaterData(...).bybox` API** — `./.venv/bin/python -c "import pynhd; help(pynhd.WaterData.bybox)"`. If the method/layer name differs (e.g. `bygeom`, or layer `nhdflowline_network` not found), adjust `fetch_hydro` accordingly and note it. The `streamorde` column name is handled in `bake_hydro`.

- [ ] **Step 4: Rebuild the region** (replaces `regions/lassen_ca`, a few minutes, ~190 MB DEM):

```bash
rm -rf regions/lassen_ca
./.venv/bin/python region_prep.py --id lassen_ca --name "Lassen County, California" \
  --bbox -121.06 40.16 -120.34 40.85 --epsg 32610
```
Expected: `regions/lassen_ca/{dem.tif, overview.png, region.json, hydro.json}`; printed lake/river counts > 0; `region.json.bounds` ≈ 61×77 km with **no NaN corners** (open `overview.png` to confirm a clean rectangle).

- [ ] **Step 5: Re-run registration + confirm dummy track still fits** — `./.venv/bin/python -m pytest tests/test_registration.py -q` → PASS (Susanville control point on the new DEM). Tracks (lon -120.76..-120.65) remain interior.

- [ ] **Step 6: Commit**

```bash
git add region_prep.py regions/lassen_ca/region.json regions/lassen_ca/overview.png regions/lassen_ca/hydro.json
git commit -m "Region prep: 18x24-sized Lassen region, NaN-trimmed, with baked hydrography"
```

---

## Task 4: Render hydrography (water layer)

**Files:**
- Modify: `app/render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Failing test — water composites over the relief**

```python
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
    import numpy as np
    a = np.asarray(dry); b = np.asarray(wet)
    assert not np.array_equal(a, b)                 # water changed the image
    cxpx, cypx = wet.size[0]//2, wet.size[1]//2     # centre of the lake
    px = b[cypx, cxpx]
    from app.render import WATER_FILL
    assert all(abs(int(px[i]) - WATER_FILL[i]) < 40 for i in range(3))
```

- [ ] **Step 2: Run, verify fail** — `./.venv/bin/python -m pytest tests/test_render.py::test_water_fills_lake_area -q` → FAIL (`hydro` kwarg / WATER_FILL missing).

- [ ] **Step 3: Implement in `app/render.py`** — style constants, loader, draw, and wire into `rasterize` between relief and tracks:

```python
# water cartography
WATER_FILL = (104, 128, 134)      # muted slate-blue, sits with the earthy palette
WATER_SHORELINE = (74, 96, 102)
RIVER_COLOR = (92, 118, 126)
RIVER_BASE_PT = 0.7
RIVER_STEP_PT = 0.5
RIVER_MAX_PT = 3.0

def _load_hydro(region_dir):
    p = os.path.join(region_dir, "hydro.json")
    return json.load(open(p)) if os.path.exists(p) else None

def _draw_hydro(img, hydro, spec, out_w, out_h, dpi):
    if not hydro:
        return img
    d = ImageDraw.Draw(img, "RGBA")
    for lake in hydro.get("lakes", []):
        pts = [_crs_to_px(x, y, spec.crop, out_w, out_h) for x, y in lake["coords"]]
        if len(pts) >= 3:
            d.polygon(pts, fill=WATER_FILL + (255,), outline=WATER_SHORELINE + (255,))
    for r in hydro.get("rivers", []):
        wpt = min(RIVER_MAX_PT, RIVER_BASE_PT + RIVER_STEP_PT * max(0, r.get("order", 3) - 3))
        wpx = max(1, round(_pt_to_px(wpt, dpi)))
        pts = [_crs_to_px(x, y, spec.crop, out_w, out_h) for x, y in r["coords"]]
        if len(pts) >= 2:
            d.line(pts, fill=RIVER_COLOR + (255,), width=wpx, joint="curve")
    return img
```

Change `rasterize` signature to `def rasterize(spec, dpi, region_dir, watermark=False, hydro=None):` and restructure the compose section so water sits under the tracks:

```python
    rgb = rgb[pad_y:pad_y+out_h, pad_x:pad_x+out_w, :]

    if hydro is None:
        hydro = _load_hydro(region_dir)
    himg = Image.fromarray(rgb, "RGB").convert("RGBA")
    himg = _draw_hydro(himg, hydro, spec, out_w, out_h, dpi)
    rgb = np.asarray(himg.convert("RGB"))

    lum = (0.2126*rgb[...,0] + 0.7152*rgb[...,1] + 0.0722*rgb[...,2]) / 255.0
    rgb = _ink_tracks(rgb, spec, out_w, out_h, dpi)
    img = Image.fromarray(rgb, "RGB").convert("RGBA")
    img = _draw_markers(img, spec, lum, out_w, out_h, dpi)
    # ... title + watermark unchanged ...
```

- [ ] **Step 4: Run, verify pass** — `./.venv/bin/python -m pytest tests/test_render.py -q` → PASS (incl. the invariant-1 scale test, which now also exercises water=None → loads real hydro.json).

- [ ] **Step 5: Eyeball a finalized poster** — render the corridor crop on the rebuilt region and open it; confirm Eagle Lake reads as water and the Susan River shows. (Reuse the poster one-liner from the session, or `scripts/`.)

- [ ] **Step 6: Commit**

```bash
git add app/render.py tests/test_render.py
git commit -m "Render: composite baked hydrography (flat lakes + order-weighted rivers)"
```

---

## Task 5: Multi-file upload — API accumulate + drag-drop UI

**Files:**
- Modify: `app/session.py`, `app/main.py`, `app/static/index.html`, `app/static/app.js`, `app/static/style.css`
- Test: `tests/test_main.py`

- [ ] **Step 1: Failing tests — multi-file in one request, and append by session_id**

```python
def test_upload_multiple_files_accumulate():
    c = _client()
    files = [("files", ("a.gpx", open("tests/fixtures/sample.gpx", "rb").read(), "application/gpx+xml")),
             ("files", ("b.gpx", open("tests/fixtures/sample.gpx", "rb").read(), "application/gpx+xml"))]
    r = c.post("/api/upload", files=files)
    assert r.status_code == 200
    assert len(r.json()["tracks"]) == 10            # 5 + 5 combined

def test_upload_appends_to_session():
    c = _client()
    j = _upload(c)                                   # 5 tracks
    files = [("files", ("b.gpx", open("tests/fixtures/sample.gpx", "rb").read(), "application/gpx+xml"))]
    r = c.post("/api/upload", files=files, data={"session_id": j["session"]})
    assert r.status_code == 200
    assert r.json()["session"] == j["session"]
    assert len(r.json()["tracks"]) == 10
```

Update the existing `_upload` helper to post under the `files` field name (list form).

- [ ] **Step 2: Run, verify fail** — `./.venv/bin/python -m pytest tests/test_main.py -q` → FAIL (single-file endpoint).

- [ ] **Step 3: Implement** — `app/session.py` add `def has(sid): return sid in _SESSIONS`. Rewrite `/api/upload` in `app/main.py`:

```python
from typing import List, Optional
from app.ingest import load_tracks

@app.post("/api/upload")
async def upload(files: List[UploadFile] = File(...), session_id: Optional[str] = Form(None)):
    new = []
    for f in files:
        new += load_tracks(await f.read(), GEO, filename=f.filename)
    if session_id and session.has(session_id):
        tracks = session.get(session_id)["tracks"] + new
        sid = session_id
    else:
        tracks, sid = new, None
    if not tracks:
        raise HTTPException(400, "No usable tracks in file(s)")
    spots = hotspots(tracks, region_bounds=CFG["bounds"])
    if sid is None:
        sid = session.create({"tracks": tracks, "hotspots": spots})
    else:
        session.update(sid, tracks=tracks, hotspots=spots)
    tpx = [[crs_to_overview_px(GEO, x, y) for x, y in t.coords] for t in tracks]
    hpx = [{"px": crs_to_overview_px(GEO, s["x"], s["y"]), "weight": s["weight"]} for s in spots]
    return {"session": sid, "overview": f"/regions/{REGION_ID}/overview.png",
            "overview_size": CFG["overview_size"], "tracks": tpx, "hotspots": hpx}
```

(Replace the old `gpx: UploadFile` import-site usage; `load_gpx_tracks` import in main.py may be dropped in favor of `load_tracks`.)

- [ ] **Step 4: Run, verify pass** — `./.venv/bin/python -m pytest tests/test_main.py -q` → PASS.

- [ ] **Step 5: Upgrade the UI** — `index.html`: replace the file input with a drop zone + `multiple` input + a `<ul id="fileList">` + a `Clear` button. `app.js`: handle `dragover`/`drop` and the input, POST all files as `files` with the current `session_id`, render the merged tracks, list filenames, and Clear resets `state.session=null` + canvas. `style.css`: style `#drop` (dashed border, hover state). Keep crop/proof/final unchanged.

- [ ] **Step 6: Manual end-to-end** — `./.venv/bin/uvicorn app.main:app --reload`; drop `sample.gpx` twice + a KML; confirm tracks accumulate, hotspots update, proof + final render with water. Stop the server.

- [ ] **Step 7: Commit**

```bash
git add app/session.py app/main.py app/static/ tests/test_main.py
git commit -m "Web app: multi-file accumulate upload (GPX/KML/KMZ) + drag-drop UI"
```

---

## Task 6: End-to-end verification + adversarial review

- [ ] **Step 1: Full suite** — `./.venv/bin/python -m pytest tests/ -q` → all green.
- [ ] **Step 2: Finalized poster** — render an 18×24 crop at 300 dpi on the rebuilt region with the dummy tracks + water; confirm it reads as a finished map (terrain + water + route). Send to the user.
- [ ] **Step 3: Adversarial correctness review** — run the established render/ingest review workflow over the changed files (`ingest.py`, `region_prep.py`, `render.py`, `main.py`); fold in confirmed findings with regression tests.
- [ ] **Step 4: Update `requirements.txt`** — add `pynhd>=0.19` (and `lxml` is already pulled in transitively, but pin it: `lxml>=5.0`). Commit.
- [ ] **Step 5: Push** — `git push origin main`.

---

## Risks / notes
- `pynhd` layer names / `bybox` signature: verified in Task 3 Step 3 before the rebuild; empty-water fallback keeps region prep working if NHD has no coverage.
- KML in the wild varies (LineString vs gx:Track, namespaces); the namespace-agnostic `_localname` walk covers the common Avenza/OnX/Google exports. Photos/placemark points are out of scope (markers come from density).
- Water color/weight are by-eye levers tuned after the pipeline lands.
