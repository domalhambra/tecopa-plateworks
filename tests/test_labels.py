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
