# tests/test_oblique.py
"""High relief (plan-oblique terrain, v1.8) -- the contract suite.

The knob's promises, each pinned here:
- oblique=0 is a STRICT no-op (byte-identical render, byte-identical manifest);
- the shear budget is a pure function of the spec (no dpi anywhere), the probe is
  DPI-independent, and the warped proof is a faithful scale of the warped final;
- everything on the sheet displaces together (a summit marker stays glued to its
  displaced summit), occlusion is real (a route/pin behind standing terrain ghosts,
  never vanishes and never floats), and no output pixel inside the sheet is left
  unpainted by the sweep;
- the southern band that shears into view is real data or an honest 422;
- the knob rides the spec end to end: endpoint stamp, manifest omit-at-default,
  frozen-fixture reprint, /api/continue prefill, wallpaper re-fit, time-lapse
  last-frame==still, and the cartouche's PLAN OBLIQUE tag.
"""
import dataclasses
import io
import json
import os

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.transform import from_bounds as transform_from_bounds

from app import render
from app.spec import CompositionSpec, OffDemError, SpecError

REGION_DIR = "regions/lassen_ca"


def _cfg(region_dir=REGION_DIR):
    return json.load(open(os.path.join(region_dir, "region.json")))


def _center_spec(oblique=0.0, tracks=None, hotspots=None, **kw):
    """The house 27x36 km center crop (9x12 in, exactly the 10 m/px floor at 300)."""
    cfg = _cfg()
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    crop = (cx - 13500, cy - 18000, cx + 13500, cy + 18000)
    base = dict(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                print_w_in=9, print_h_in=12, native_resolution_m=10,
                tracks=tracks if tracks is not None else [],
                hotspots=hotspots if hotspots is not None else [],
                seed=7, oblique=oblique)
    base.update(kw)
    return CompositionSpec(**base)


NO_WATER = {"lakes": [], "rivers": []}


def _write_plate(region_dir, surface, bounds=(600000.0, 4400000.0, 630000.0, 4440000.0),
                 emin=1000.0, emax=2000.0, res=10, south_pad_m=8000.0):
    """A throwaway terrain plate whose DEM is the given 0..1 `surface` (row 0 = north),
    for occlusion geometry the smooth stock synthetic peak can't produce. The physical
    DEM is extended `south_pad_m` past the declared southern bound (the last row
    repeated), so a plan-oblique shear band always has real data to pull in -- the
    plate's declared bounds (region.json) stay the crop footprint."""
    os.makedirs(region_dir, exist_ok=True)
    ny, nx = surface.shape
    west, south, east, north = bounds
    gy = (north - south) / ny
    pad_rows = int(round(south_pad_m / gy)) if south_pad_m else 0
    if pad_rows:
        surface = np.vstack([surface, np.repeat(surface[-1:], pad_rows, axis=0)])
    ny2 = surface.shape[0]
    dem_south = south - pad_rows * gy
    cfg = {"id": os.path.basename(region_dir), "name": "Cliff", "crs": "EPSG:32610",
           "bounds": list(bounds), "native_resolution_m": res,
           "elevation_min": emin, "elevation_max": emax,
           "light_azimuth": 315, "light_altitude": 45, "z_factor": 1.0,
           "overview_size": [300, 400], "dem_path": "dem.tif"}
    json.dump(cfg, open(os.path.join(region_dir, "region.json"), "w"))
    data = (emin + (emax - emin) * np.clip(surface, 0, 1)).astype("float32")
    profile = dict(driver="GTiff", dtype="float32", count=1, height=ny2, width=nx,
                   crs=cfg["crs"],
                   transform=transform_from_bounds(west, dem_south, east, north, nx, ny2),
                   nodata=np.nan, tiled=True, blockxsize=128, blockysize=128,
                   compress="deflate")
    with rasterio.open(os.path.join(region_dir, "dem.tif"), "w", **profile) as ds:
        ds.write(data, 1)
        ds.build_overviews([2, 4], Resampling.average)
        ds.update_tags(synthetic="1")
    return cfg


# ---- the strict no-op at 0 ----

def test_oblique_zero_is_a_strict_noop():
    spec = _center_spec(tracks=[np.array([[660000.0, 4470000.0], [700000.0, 4500000.0]])],
                        hotspots=[{"x": 690000.0, "y": 4485000.0, "weight": 2}])
    a = np.asarray(render.rasterize(spec, dpi=96, region_dir=REGION_DIR))
    b = np.asarray(render.rasterize(dataclasses.replace(spec, oblique=0.0),
                                    dpi=96, region_dir=REGION_DIR))
    assert np.array_equal(a, b)
    # and the pipeline reports no warp at all (ctx None -> every painter takes the
    # classic branch), with the legacy symmetric window shape
    cfg = _cfg()
    _, lum, ctx = render._paint_base(spec, 96, REGION_DIR, cfg)
    assert ctx is None
    out_w, out_h = spec.pixel_size(96)
    elev, pad_x, pad_top, pad_bot, _ = render._read_window(
        REGION_DIR, cfg, spec.crop, out_w, out_h, extra_south_px=0)
    assert pad_top == pad_bot == round(out_h * render.MARGIN_FRAC)
    assert elev.shape == (out_h + 2 * pad_top, out_w + 2 * pad_x)


def test_oblique_changes_the_render_and_is_deterministic():
    spec = _center_spec(oblique=1.0)
    flat = np.asarray(render.rasterize(dataclasses.replace(spec, oblique=0.0),
                                       dpi=96, region_dir=REGION_DIR, hydro=NO_WATER))
    a = np.asarray(render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=NO_WATER))
    b = np.asarray(render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=NO_WATER))
    assert not np.array_equal(flat, a), "oblique=1 did nothing"
    assert np.array_equal(a, b), "the warped render is not deterministic"


# ---- budget purity + probe stability (invariant 1) ----

def test_oblique_band_is_dpi_independent():
    # a pure function of the spec: knob x max-fraction x crop height, no dpi anywhere
    spec = _center_spec(oblique=0.5)
    assert abs(render.oblique_band_m(spec)
               - 0.5 * render.OBLIQUE_MAX_FRAC * (spec.crop[3] - spec.crop[1])) < 1e-9
    assert render.oblique_band_m(dataclasses.replace(spec, oblique=0.0)) == 0.0


def test_oblique_shear_probe_is_stable_and_budget_exact():
    cfg = _cfg()
    spec = _center_spec(oblique=1.0)
    a = render._oblique_shear(REGION_DIR, cfg, spec)
    b = render._oblique_shear(REGION_DIR, cfg, spec)
    assert a is not None and a == b
    s, z_floor = a
    # the budget identity: the probe's highest ground rises exactly band_m
    band = render.oblique_band_m(spec)
    probe = render._probe_dem(REGION_DIR, cfg,
                              (spec.crop[0], spec.crop[1] - band,
                               spec.crop[2], spec.crop[3]))
    assert abs(s * (np.nanmax(probe) - z_floor) - band) < 1e-6
    assert render._oblique_shear(REGION_DIR, cfg,
                                 dataclasses.replace(spec, oblique=0.0)) is None


# ---- proof == final under the warp ----

def test_oblique_proof_is_a_faithful_scale_of_final():
    spec = _center_spec(oblique=0.6)
    proof = render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=NO_WATER)
    final = render.rasterize(spec, dpi=300, region_dir=REGION_DIR, hydro=NO_WATER)
    final_ds = final.resize(proof.size, Image.LANCZOS)
    mad = np.abs(np.asarray(proof, np.float32) - np.asarray(final_ds, np.float32)).mean()
    # measured 1.2/255 on the synthetic plate at oblique=1; the flat sheet's own
    # bound is 3.0 (test_render.py) -- the warp must not loosen it.
    assert mad < 3.0, f"warped proof is not a faithful scale of the final: {mad:.2f}/255"


def test_oblique_track_corridor_is_faithful_across_dpi():
    line = np.array([[661244.0, 4462659.0], [711744.0, 4509992.0]])
    spec = _center_spec(oblique=0.6, tracks=[line])
    proof = render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=NO_WATER)
    final = render.rasterize(spec, dpi=300, region_dir=REGION_DIR, hydro=NO_WATER)
    final_ds = final.resize(proof.size, Image.LANCZOS)
    w, h = proof.size
    # corridor = the UNSHEARED ribbon dilated up-sheet by the full displacement
    # budget, so it covers every position the warped ribbon can occupy at this dpi
    from scipy.ndimage import binary_dilation
    cov = render._coverage(spec, w, h, width_px=12) > 0
    band_px = int(np.ceil(render.oblique_band_m(spec) / ((spec.crop[3] - spec.crop[1]) / h)))
    corr = binary_dilation(cov, structure=np.ones((band_px + 1, 1), bool))
    diff = np.abs(np.asarray(proof, np.float32) - np.asarray(final_ds, np.float32))
    mad = diff[corr].mean()
    assert mad < 16.0, f"warped track treatment shifts with DPI: corridor MAD {mad:.2f}/255"


# ---- registration: the journey stays glued to the standing terrain ----

def _marker_centroid(img):
    a = np.asarray(img).astype(int)
    m = (np.abs(a[..., 0] - render.MARKER_FILL[0]) < 12) \
        & (np.abs(a[..., 1] - render.MARKER_FILL[1]) < 12) \
        & (np.abs(a[..., 2] - render.MARKER_FILL[2]) < 12)
    ys, xs = np.nonzero(m)
    assert ys.size > 40, "marker disc not found"
    return ys.mean(), xs.mean()


def test_oblique_summit_marker_stays_glued():
    # the synthetic plate's Gaussian peak sits at the region center = the crop/sheet
    # center; a marker there must move UP by exactly the warp's own shift, and not
    # sideways (the shear is purely vertical).
    cfg = _cfg()
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    mk = [{"x": cx, "y": cy, "weight": 2}]
    flat = render.rasterize(_center_spec(hotspots=mk), dpi=96,
                            region_dir=REGION_DIR, hydro=NO_WATER)
    spec1 = _center_spec(oblique=1.0, hotspots=mk)
    warped = render.rasterize(spec1, dpi=96, region_dir=REGION_DIR, hydro=NO_WATER)
    y0, x0 = _marker_centroid(flat)
    y1, x1 = _marker_centroid(warped)
    out_w, out_h = spec1.pixel_size(96)
    _, _, ctx = render._paint_base(spec1, 96, REGION_DIR, cfg, hydro=NO_WATER)
    px, py = render._crs_to_px(cx, cy, spec1.crop, out_w, out_h)
    expected = render._shift_px_at(ctx, px, py)
    assert expected > 10, "the peak should stand well clear of the sheet"
    assert abs((y0 - y1) - expected) <= 3.0, \
        f"summit marker shifted {y0 - y1:.1f}px, terrain shifted {expected:.1f}px"
    # anti-aliased disc edges blend against different ground at the two positions,
    # so allow measurement noise; a real column drift would be band-sized.
    assert abs(x1 - x0) <= 2.0


def test_oblique_track_drapes_with_terrain():
    cfg = _cfg()
    bx = cfg["bounds"]
    cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    line = np.array([[cx - 9000, cy], [cx + 9000, cy]])   # E-W across the summit
    spec1 = _center_spec(oblique=1.0, tracks=[line])
    warped = np.asarray(render.rasterize(spec1, dpi=96, region_dir=REGION_DIR,
                                         hydro=NO_WATER)).astype(int)
    out_w, out_h = spec1.pixel_size(96)
    _, _, ctx = render._paint_base(spec1, 96, REGION_DIR, cfg, hydro=NO_WATER)
    px, py = render._crs_to_px(cx, cy, spec1.crop, out_w, out_h)
    shift = render._shift_px_at(ctx, px, py)
    gold = np.array(spec1.track_rgb)

    def has_ink(row, col, slack=6):
        patch = warped[int(row) - slack:int(row) + slack, int(col) - slack:int(col) + slack]
        return (np.linalg.norm(patch - gold, axis=2) < 60).any()

    assert has_ink(py - shift, px), "ink missing at the displaced corridor"
    assert not has_ink(py, px), "ink still at the undisplaced corridor (didn't drape)"


# ---- the warp core: walls, occlusion, hole-freeness (hand-built arrays) ----

def test_oblique_warp_walls_and_occlusion():
    # a plain (z=0) with a plateau (z=100) standing mid-array, at shear s=0.5 / gy=1
    # so the plateau shifts 50 rows up-sheet. Geometry (viewer from the south, rows
    # grow southward): the plateau TOP (source 60..99) projects to dest 10..49; its
    # SOUTHERN cliff (99->100) becomes a visible wall spanning dest 49..100, painted
    # at y=100 with the base row's color, wall-shaded; the plain outside stays put.
    H, W = 160, 12
    elev = np.zeros((H, W), np.float32)
    elev[60:100, :] = 100.0                       # plateau rows 60..99
    rgb = np.full((H, W, 3), 100, np.uint8)       # plain grey
    rgb[60:100] = 200                             # plateau lighter grey
    out, winner = render._oblique_warp(rgb, elev, s=0.5, z_floor=0.0, gy=1.0,
                                       band_px=50.0)
    # (a) occlusion: the band that was far plain (dest 10..48) now shows plateau top
    # (nearer terrain won), and its winner rows are plateau rows (souther than the
    # flat plain that projected there)
    assert (out[12:48, :, 0] == 200).all(), "standing plateau failed to occlude the plain"
    assert ((winner[12:48, :] >= 60) & (winner[12:48, :] <= 99)).all()
    # (b) far-north plain is untouched, winner = its own rows
    assert (out[0:9, :, 0] == 100).all()
    assert winner[5, 3] == 5
    # (c) no unpainted holes anywhere the sweep reaches
    assert (winner >= 0).all(), "the span fill left holes"
    # (d) the southern cliff is a WALL: dest 55..95 (interior of the 49..100 span) is
    # the base plain color, wall-shaded, owned by the base row 100
    wall = out[55:95, :, 0].astype(float)
    base = 100.0 * render.OBLIQUE_WALL_SHADE      # base-row (plain) color, shaded
    assert abs(wall.mean() - base) < 6.0, f"wall not shaded: {wall.mean():.1f} vs {base:.1f}"
    assert (winner[55:95, :] == 100).all(), "wall span not owned by its base row"


def test_oblique_warp_flat_ground_is_identity():
    H, W = 40, 9
    elev = np.zeros((H, W), np.float32)
    rgb = (np.arange(H * W * 3) % 251).reshape(H, W, 3).astype(np.uint8)
    out, winner = render._oblique_warp(rgb, elev, s=2.0, z_floor=0.0, gy=1.0,
                                       band_px=30.0)
    assert np.array_equal(out, rgb)
    assert np.array_equal(winner, np.arange(H, dtype=np.int32)[:, None].repeat(W, 1))


# ---- occlusion end-to-end on a custom cliff plate ----

@pytest.fixture()
def cliff_region(tmp_path):
    # north 60%: plain at emin; south 40%: plateau at emax, sharp escarpment.
    # crop = the full bounds (30x40 km, 0.75 aspect) -> band at oblique=1 is 12% of
    # 40 km = 4.8 km; a track 1.2 km north of the escarpment sits well inside the
    # plateau's projected cover -> hidden.
    ny, nx = 400, 300
    surf = np.zeros((ny, nx), np.float32)
    surf[int(ny * 0.6):, :] = 1.0
    d = tmp_path / "cliff"
    cfg = _write_plate(str(d), surf)
    return str(d), cfg


def _cliff_spec(cfg, tracks=(), hotspots=(), oblique=1.0):
    b = cfg["bounds"]
    return CompositionSpec(region_id=cfg["id"], crs=cfg["crs"], crop=tuple(b),
                           print_w_in=9, print_h_in=12,
                           native_resolution_m=cfg["native_resolution_m"],
                           tracks=list(tracks), hotspots=list(hotspots), seed=7,
                           oblique=oblique)


def test_oblique_hidden_track_ghosts_never_vanishes(cliff_region):
    rd, cfg = cliff_region
    b = cfg["bounds"]
    edge_y = b[3] - 0.6 * (b[3] - b[1])           # the escarpment's CRS northing
    hidden_y = edge_y + 1200.0                     # 1.2 km north of the cliff
    open_y = b[3] - 0.15 * (b[3] - b[1])           # far north, unoccluded
    x0, x1 = b[0] + 6000, b[2] - 6000
    hidden_tr = np.array([[x0, hidden_y], [x1, hidden_y]])
    open_tr = np.array([[x0, open_y], [x1, open_y]])
    bare = np.asarray(render.rasterize(_cliff_spec(cfg), dpi=96, region_dir=rd,
                                       hydro=NO_WATER), np.float32)
    inked = np.asarray(render.rasterize(_cliff_spec(cfg, tracks=[hidden_tr, open_tr]),
                                        dpi=96, region_dir=rd, hydro=NO_WATER), np.float32)
    spec = _cliff_spec(cfg, tracks=[hidden_tr, open_tr])
    out_w, out_h = spec.pixel_size(96)
    _, _, ctx = render._paint_base(spec, 96, rd, cfg, hydro=NO_WATER)

    def ink_delta(y_crs):
        px, py = render._crs_to_px((x0 + x1) / 2, y_crs, spec.crop, out_w, out_h)
        pyd = py - render._shift_px_at(ctx, px, py)
        r0, r1 = int(pyd) - 3, int(pyd) + 4
        c0, c1 = int(px) - 20, int(px) + 20
        return np.abs(inked[r0:r1, c0:c1] - bare[r0:r1, c0:c1]).max()

    # the hidden ribbon is occluded at its displaced position...
    px, py = render._crs_to_px((x0 + x1) / 2, hidden_y, spec.crop, out_w, out_h)
    pyd = py - render._shift_px_at(ctx, px, py)
    assert render._occluded(ctx, px, pyd, py), "track behind the cliff not seen as occluded"
    # ...yet its ink survives as a ghost: visibly present, visibly quieter than open ink
    hidden_d, open_d = ink_delta(hidden_y), ink_delta(open_y)
    assert hidden_d > 8.0, "hidden route vanished (no ghost)"
    assert hidden_d < 0.75 * open_d, \
        f"hidden route as loud as an open one ({hidden_d:.0f} vs {open_d:.0f})"


def test_oblique_occluded_marker_ghosts_never_drops(cliff_region, monkeypatch):
    # a marker behind the standing cliff must be occluded (a ghost, not a solid) yet
    # never silently dropped. Isolate the ghosting from background contrast by drawing
    # the SAME occluded marker over the SAME warped ground at two ghost factors --
    # the honest whisper (0.4) and a forced-solid control (1.0).
    rd, cfg = cliff_region
    b = cfg["bounds"]
    edge_y = b[3] - 0.6 * (b[3] - b[1])
    cx = (b[0] + b[2]) / 2
    mk = {"x": cx, "y": edge_y + 1200.0, "weight": 2}      # behind the cliff
    spec = _cliff_spec(cfg, hotspots=[mk])
    out_w, out_h = spec.pixel_size(96)
    _, _, ctx = render._paint_base(spec, 96, rd, cfg, hydro=NO_WATER)
    px, py = render._crs_to_px(mk["x"], mk["y"], spec.crop, out_w, out_h)
    pyd = py - render._shift_px_at(ctx, px, py)
    assert render._occluded(ctx, px, pyd, py), "marker behind the cliff not seen as occluded"

    bare = np.asarray(render.rasterize(_cliff_spec(cfg), dpi=96, region_dir=rd,
                                       hydro=NO_WATER)).astype(int)

    def disc_delta():
        img = np.asarray(render.rasterize(spec, dpi=96, region_dir=rd,
                                          hydro=NO_WATER)).astype(int)
        r, c = int(pyd), int(px)
        return np.abs(img[r - 6:r + 6, c - 6:c + 6] - bare[r - 6:r + 6, c - 6:c + 6]).max()

    ghost_d = disc_delta()                                  # the real 0.4 ghost
    monkeypatch.setattr(render, "OBLIQUE_SYMBOL_GHOST", 1.0)
    solid_d = disc_delta()                                  # forced solid, same spot
    assert ghost_d > 8, "occluded marker was silently dropped (no ghost)"
    assert ghost_d < solid_d, "occluded marker not ghosted (drawn at full strength)"


# ---- honesty: the southern band must be real data ----

def test_oblique_south_boundary_422():
    cfg = _cfg()
    bx = cfg["bounds"]
    cx = (bx[0] + bx[2]) / 2
    # a crop sitting ON the region's southern boundary: fine flat, but High relief
    # needs the band south of it, which has no data -> honest 422 naming the shear
    crop = (cx - 13500, bx[1], cx + 13500, bx[1] + 36000)
    spec = _center_spec()
    spec = dataclasses.replace(spec, crop=crop)
    render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=NO_WATER)  # flat: renders
    with pytest.raises(OffDemError) as e:
        render.rasterize(dataclasses.replace(spec, oblique=1.0),
                         dpi=96, region_dir=REGION_DIR, hydro=NO_WATER)
    assert "High relief" in str(e.value)


def test_oblique_flat_crop_degenerates_to_the_flat_sheet(tmp_path):
    # a dead-flat plate: the shear has nothing to raise -> byte-identical to flat,
    # no div-by-zero, and the probe helper reports the degeneracy as None
    d = tmp_path / "flat"
    cfg = _write_plate(str(d), np.full((200, 150), 0.5, np.float32))
    spec = _cliff_spec(cfg, oblique=1.0)
    assert render._oblique_shear(str(d), cfg, spec) is None
    a = np.asarray(render.rasterize(spec, dpi=96, region_dir=str(d), hydro=NO_WATER))
    b = np.asarray(render.rasterize(dataclasses.replace(spec, oblique=0.0),
                                    dpi=96, region_dir=str(d), hydro=NO_WATER))
    assert np.array_equal(a, b)


# ---- the spec/manifest contract ----

def test_spec_to_json_omits_the_default_oblique():
    from app.serialize import spec_to_json, spec_from_json
    spec = _center_spec()
    d = spec_to_json(spec)
    assert "oblique" not in d, "default oblique must be omitted (forever-contract)"
    assert spec_from_json(d).oblique == 0.0
    d2 = spec_to_json(dataclasses.replace(spec, oblique=0.7))
    assert d2["oblique"] == 0.7
    assert spec_from_json(d2).oblique == 0.7


def test_pre_oblique_manifest_loads_with_the_default():
    from app import provenance
    manifest = json.load(open("tests/fixtures/manifest_v1.json"))
    spec = provenance.manifest_to_spec(manifest)
    assert spec.oblique == 0.0


def test_oblique_bounds_rejected():
    for bad in (-0.1, 1.5, float("nan")):
        with pytest.raises(SpecError):
            dataclasses.replace(_center_spec(), oblique=bad).validate(300)
    dataclasses.replace(_center_spec(), oblique=0.0).validate(300)
    dataclasses.replace(_center_spec(), oblique=1.0).validate(300)


def test_stats_line_carries_the_plan_oblique_tag():
    assert "PLAN OBLIQUE" in render._stats_line(_center_spec(oblique=0.4), 300)
    assert "PLAN OBLIQUE" not in render._stats_line(_center_spec(), 300)


# ---- the frozen fixture: an oblique poster must reprint forever ----

def _client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_frozen_oblique_manifest_loads_validates_and_reprints():
    from app import provenance
    manifest = json.load(open("tests/fixtures/manifest_oblique_v1.json"))
    spec = provenance.manifest_to_spec(manifest)
    assert spec.oblique == 0.55
    spec.validate(300)
    img = Image.new("RGB", (16, 16), (20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, "PNG", pnginfo=provenance.manifest_pnginfo(manifest))
    c = _client()
    r = c.post("/api/reprint", files={"file": ("ob_v1.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200, r.text
    assert Image.open(io.BytesIO(r.content)).size == (9 * 300, 12 * 300)


# ---- endpoint stamp, prefill round-trip, wallpaper carry-through ----

def _upload(c):
    files = [("files", ("a.gpx", open("tests/fixtures/sample.gpx", "rb").read(),
                        "application/gpx+xml"))]
    r = c.post("/api/upload", files=files)
    assert r.status_code == 200
    return r.json()


def _crop_form(j, km_wide=30.0, ar=0.75):
    cfg = _cfg()
    region_w = cfg["bounds"][2] - cfg["bounds"][0]
    ovw, ovh = j["overview_size"]
    cw = ovw * (km_wide * 1000.0 / region_w)
    ch = cw / ar
    x0 = ovw * 0.5 - cw / 2
    y0 = ovh * 0.5 - ch / 2
    return {"x0": x0, "y0": y0, "x1": x0 + cw, "y1": y0 + ch}


def test_oblique_stamped_through_endpoint_and_bounded():
    from app import session as sess_mod
    c = _client()
    j = _upload(c)
    data = {"session_id": j["session"], **_crop_form(j), "print_w": 9, "print_h": 12}
    assert c.post("/api/proof", data={**data, "oblique": 0.4}).status_code == 200
    assert sess_mod.get(j["session"])["spec"].oblique == 0.4
    assert c.post("/api/proof", data={**data, "oblique": 1.5}).status_code == 422
    assert c.post("/api/proof", data={**data, "oblique": -0.2}).status_code == 422


def test_oblique_prefill_round_trip():
    c = _client()
    j = _upload(c)
    data = {"session_id": j["session"], **_crop_form(j), "print_w": 9, "print_h": 12,
            "oblique": 0.6}
    assert c.post("/api/proof", data=data).status_code == 200
    final = c.post("/api/final", data={"session_id": j["session"]}).content
    cont = c.post("/api/continue",
                  files={"file": ("poster.png", final, "image/png")}).json()
    assert abs(cont["prefill"]["style"]["oblique"] - 0.6) < 1e-9


def test_wallpaper_preset_carries_oblique():
    from app import wallpaper
    spec = _center_spec(oblique=0.5)
    preset = next(iter(wallpaper.PRESETS.values()))
    cfg = _cfg()
    tspec = wallpaper.spec_for_preset(spec, preset, tuple(cfg["bounds"]))
    assert tspec.oblique == 0.5


# ---- time-lapse: the film's last frame is the still, warped and all ----

def test_oblique_timelapse_last_frame_equals_still():
    from app import timelapse
    line = np.array([[661244.0, 4462659.0], [711744.0, 4509992.0]])
    spec = _center_spec(oblique=0.5, tracks=[line], track_days=["2024-06-01"])
    frames = list(timelapse.render_frames(spec, 64, REGION_DIR, hydro=NO_WATER))
    still = render.rasterize(spec, dpi=64, region_dir=REGION_DIR, hydro=NO_WATER)
    assert np.array_equal(np.asarray(frames[-1]), np.asarray(still))


def test_oblique_progressive_last_frame_equals_still():
    from app import timelapse
    line = np.array([[661244.0, 4462659.0], [711744.0, 4509992.0]])
    spec = _center_spec(oblique=0.5, tracks=[line], track_days=["2024-06-01"])
    frames = list(timelapse.progressive_frames(spec, 64, REGION_DIR, n_frames=4,
                                               hydro=NO_WATER))
    still = render.rasterize(spec, dpi=64, region_dir=REGION_DIR, hydro=NO_WATER)
    assert np.array_equal(np.asarray(frames[-1]), np.asarray(still))
