# tests/test_labels.py
"""Named-geography labels: off is a strict no-op, candidates only surface in-crop,
priority + collision keep the sheet legible, and placement is DPI-stable (proof==final)."""
import json
import os
import numpy as np
from PIL import Image

from app import render
from app.spec import CompositionSpec

REGION_DIR = "regions/lassen_ca"


def _cfg():
    return json.load(open(os.path.join(REGION_DIR, "region.json")))

def _spec(labels=False, print_w=9, print_h=12, **kw):
    cfg = _cfg(); bx = cfg["bounds"]
    cx = (bx[0] + bx[2]) / 2; cy = (bx[1] + bx[3]) / 2
    half = 18000.0
    crop = (cx - half, cy - half * print_h / print_w, cx + half, cy + half * print_h / print_w)
    return CompositionSpec(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                           print_w_in=print_w, print_h_in=print_h, native_resolution_m=10,
                           tracks=[], hotspots=[], seed=7, title_text="-", compass=False,
                           labels=labels, **kw)

# a couple of synthetic labels guaranteed to land in the test crop, plus one far away
def _labels_for(spec):
    cfg = _cfg()
    cx = (spec.crop[0] + spec.crop[2]) / 2; cy = (spec.crop[1] + spec.crop[3]) / 2
    return {"crs": cfg["crs"], "features": [
        {"name": "Test Range", "kind": "range", "rank": 100,
         "coords": [[cx - 4000, cy], [cx, cy], [cx + 4000, cy]]},
        {"name": "Test Peak", "kind": "summit", "rank": 85, "coords": [[cx + 3000, cy - 4000]]},
        {"name": "Faraway Peak", "kind": "summit", "rank": 85,
         "coords": [[cfg["bounds"][0] - 50000, cfg["bounds"][1] - 50000]]},  # off-crop
    ]}


def test_labels_off_is_a_strict_noop():
    nw = {"lakes": [], "rivers": []}
    off = np.asarray(render.rasterize(_spec(labels=False), dpi=96, region_dir=REGION_DIR,
                                      hydro=nw, labels=_labels_for(_spec())))
    base = np.asarray(render.rasterize(_spec(labels=False), dpi=96, region_dir=REGION_DIR,
                                       hydro=nw, labels=None))
    assert np.array_equal(off, base), "labels=False must not touch the render"

def test_labels_on_changes_the_render():
    nw = {"lakes": [], "rivers": []}
    spec = _spec(labels=True)
    off = np.asarray(render.rasterize(_spec(labels=False), dpi=96, region_dir=REGION_DIR, hydro=nw))
    on = np.asarray(render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=nw,
                                     labels=_labels_for(spec)))
    assert not np.array_equal(off, on), "labels=True drew nothing"

def test_only_in_crop_features_become_candidates():
    spec = _spec(labels=True)
    out_w, out_h = spec.pixel_size(96)
    cands = render._label_candidates(_labels_for(spec), {"lakes": [], "rivers": []},
                                     spec, out_w, out_h)
    names = {c[2] for c in cands}
    assert "Test Range" in names and "Test Peak" in names
    assert "Faraway Peak" not in names, "an off-crop feature must not be a candidate"

def test_candidates_are_ranked_high_first():
    spec = _spec(labels=True)
    out_w, out_h = spec.pixel_size(96)
    cands = render._label_candidates(_labels_for(spec), {"lakes": [], "rivers": []},
                                     spec, out_w, out_h)
    ranks = [c[0] for c in cands]
    assert ranks == sorted(ranks, reverse=True)

def test_collision_avoidance_drops_overlapping_labels():
    # two identical-anchor summits: only one can be placed (their boxes coincide).
    spec = _spec(labels=True)
    cx = (spec.crop[0] + spec.crop[2]) / 2; cy = (spec.crop[1] + spec.crop[3]) / 2
    labels = {"crs": _cfg()["crs"], "features": [
        {"name": "Alpha Peak", "kind": "summit", "rank": 85, "coords": [[cx, cy]]},
        {"name": "Beta Peak", "kind": "summit", "rank": 84, "coords": [[cx, cy]]},
    ]}
    nw = {"lakes": [], "rivers": []}
    a = np.asarray(render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=nw, labels=labels))
    one = {"crs": labels["crs"], "features": labels["features"][:1]}
    b = np.asarray(render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=nw, labels=one))
    # the second (colliding) label is dropped, so both renders are identical
    assert np.array_equal(a, b), "an overlapping lower-rank label should have been dropped"

def test_label_placement_is_a_faithful_scale_across_dpi():
    # invariant 1: physical sizes -> the 96-dpi proof downscaled from the 300-dpi final
    # is near-identical. Labels only (no tracks) so the text treatment is what's measured.
    spec = _spec(labels=True)
    nw = {"lakes": [], "rivers": []}
    labels = _labels_for(spec)
    proof = render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=nw, labels=labels)
    final = render.rasterize(spec, dpi=300, region_dir=REGION_DIR, hydro=nw, labels=labels)
    final_ds = final.resize(proof.size, Image.LANCZOS)
    mad = np.abs(np.asarray(proof, np.float32) - np.asarray(final_ds, np.float32)).mean()
    assert mad < 3.0, f"labels shift with DPI: MAD {mad:.2f}/255"

def test_curved_plan_follows_a_diagonal_spine():
    import math
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGBA", (400, 400)))
    font = render._font(22)
    poly = [(40, 360), (200, 200), (360, 40)]           # up-right diagonal
    plan = render._curved_plan(d, poly, "RANGE", font, 3, 2, 10)
    assert plan is not None
    glyphs, box = plan
    xs = [cx for _, cx, _, _ in glyphs]
    assert xs[-1] > xs[0], "text must advance along the path (+x here)"
    angs = [math.degrees(a) for _, _, _, a in glyphs]
    assert all(abs(a - (-45)) < 20 for a in angs), f"glyph tangents should track ~-45deg: {angs}"

def test_curved_plan_falls_back_when_path_too_short():
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGBA", (200, 200)))
    font = render._font(22)
    assert render._curved_plan(d, [(0, 0), (6, 0)], "LONGRANGENAME", font, 3, 2, 5) is None

def test_reading_direction_flips_leftward_spines():
    # a spine pointing left is reversed so glyphs stay upright and read left-to-right
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGBA", (400, 200)))
    font = render._font(22)
    glyphs, _ = render._curved_plan(d, [(360, 100), (40, 100)], "ABCD", font, 2, 2, 5)
    xs = [cx for _, cx, _, _ in glyphs]
    assert xs[-1] > xs[0], "leftward spine should have been flipped to read +x"

def test_diagonal_range_is_dpi_stable():
    # the gating risk: rotated-glyph curved labels must still downscale faithfully.
    cfg = _cfg(); bx = cfg["bounds"]
    cx = (bx[0] + bx[2]) / 2; cy = (bx[1] + bx[3]) / 2
    half = 18000.0
    crop = (cx - half, cy - half * 12 / 9, cx + half, cy + half * 12 / 9)
    spec = CompositionSpec(region_id="lassen_ca", crs=cfg["crs"], crop=crop,
                           print_w_in=9, print_h_in=12, native_resolution_m=10,
                           tracks=[], hotspots=[], seed=7, title_text="-", compass=False, labels=True)
    # a long diagonal range spanning the crop -> exercises glyph rotation
    diag = {"crs": cfg["crs"], "features": [{"name": "Diagonal Range", "kind": "range", "rank": 100,
            "coords": [[cx - 14000, cy - 20000], [cx, cy], [cx + 14000, cy + 20000]]}]}
    nw = {"lakes": [], "rivers": []}
    proof = render.rasterize(spec, dpi=96, region_dir=REGION_DIR, hydro=nw, labels=diag)
    final = render.rasterize(spec, dpi=300, region_dir=REGION_DIR, hydro=nw, labels=diag)
    final_ds = final.resize(proof.size, Image.LANCZOS)
    mad = np.abs(np.asarray(proof, np.float32) - np.asarray(final_ds, np.float32)).mean()
    assert mad < 3.0, f"curved labels shift with DPI: MAD {mad:.2f}/255"

def test_shipped_region_labels_files_are_wellformed():
    # every built region ships a labels.json in its CRS with ranked terrain features.
    for rid in os.listdir("regions"):
        p = os.path.join("regions", rid, "labels.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p))
        assert d["crs"] == json.load(open(f"regions/{rid}/region.json"))["crs"]
        feats = d["features"]
        assert feats and all({"name", "kind", "coords"} <= set(f) for f in feats)
        assert all(f["kind"] in render.GEO_KINDS for f in feats)
