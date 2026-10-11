# tests/test_panel_render.py
import json
import os

import numpy as np

from app import panels, render
from app.spec import CompositionSpec
from tests.conftest import synthetic_region

REGION_DIR = synthetic_region("lassen_ca")
DPI = 40


def _cfg():
    return json.load(open(os.path.join(REGION_DIR, "region.json")))


def _spec(n=2, gap=2.0, **kw):
    """Two panels 17 in across on the middle of the plate: 36 x 22 in at gap 2."""
    cfg = _cfg(); bx = cfg["bounds"]
    w, h = panels.sheet_sizes(2, gap)[1]
    cx = (bx[0] + bx[2]) / 2; cy = (bx[1] + bx[3]) / 2
    half = 27000.0
    crop = (cx - half, cy - half * h / w, cx + half, cy + half * h / w)
    base = dict(region_id="lassen_ca", crs=cfg["crs"], crop=crop, print_w_in=w,
                print_h_in=h, native_resolution_m=10,
                tracks=[np.array([[crop[0] + 3000, crop[1] + 3000],
                                  [crop[2] - 3000, crop[3] - 3000]])],
                hotspots=[], seed=7, title_text="", compass=False, keyline=False,
                panels=n, panel_gap_in=gap if n > 1 else 0.0)
    base.update(kw)
    return CompositionSpec(**base)


def _render(spec, labels=None):
    return np.asarray(render.rasterize(spec, dpi=DPI, region_dir=REGION_DIR, cfg=_cfg(),
                                       hydro={"lakes": [], "rivers": []}, labels=labels))


def _seam_labels(spec):
    """One summit on the middle of the gap, and one range that crosses it."""
    cx = (spec.crop[0] + spec.crop[2]) / 2; cy = (spec.crop[1] + spec.crop[3]) / 2
    return {"crs": _cfg()["crs"], "features": [
        {"name": "Seam Peak", "kind": "summit", "rank": 100, "coords": [[cx, cy + 6000]]},
        {"name": "Seam Range", "kind": "range", "rank": 100,
         "coords": [[cx - 5000, cy - 6000], [cx, cy - 6000], [cx + 5000, cy - 6000]]},
    ]}


def test_each_panel_is_the_matching_window_of_the_unbroken_sheet():
    from PIL import Image, ImageDraw
    as_set = _spec(2, 2.0)
    unbroken = _spec(1, 2.0)
    a, b = _render(as_set).copy(), _render(unbroken).copy()
    assert a.shape == b.shape
    frames = panels.panel_rects_px(as_set, DPI)
    d = ImageDraw.Draw(Image.new("RGBA", (a.shape[1], a.shape[0])))
    marks = render._panel_mark_rects(as_set, d, frames, DPI)
    assert any((a[my0:my1, mx0:mx1] != b[my0:my1, mx0:mx1]).any()
               for mx0, my0, mx1, my1 in marks)      # the mark is there to leave out
    for mx0, my0, mx1, my1 in marks:
        a[my0:my1, mx0:mx1] = 0                  # the panel mark is the one thing a set adds
        b[my0:my1, mx0:mx1] = 0
    for x0, y0, x1, y1 in frames:
        assert np.array_equal(a[y0:y1, x0:x1], b[y0:y1, x0:x1])


def test_the_watermark_word_reaches_each_panel_through_rasterize():
    spec = _spec(2, 2.0)

    def shot(**kw):
        return np.asarray(render.rasterize(spec, dpi=DPI, region_dir=REGION_DIR, cfg=_cfg(),
                                           hydro={"lakes": [], "rivers": []}, **kw))

    bare, proof = shot(), shot(watermark=True)
    preview = shot(watermark=True, watermark_text="PREVIEW")
    assert np.array_equal(proof, shot(watermark=True, watermark_text="PROOF"))   # the default
    for x0, y0, x1, y1 in panels.panel_rects_px(spec, DPI):
        top = slice(y0, y0 + (y1 - y0) // 2)
        assert (proof[top, x0:x1] != bare[top, x0:x1]).any()
        assert (preview[top, x0:x1] != proof[top, x0:x1]).any()
    for x0, y0, x1, y1 in panels.gap_rects_px(spec, DPI):
        assert np.array_equal(proof[y0:y1, x0:x1], bare[y0:y1, x0:x1])
        assert np.array_equal(preview[y0:y1, x0:x1], bare[y0:y1, x0:x1])


def test_no_place_name_is_drawn_in_a_seam_band():
    for gap in (2.0, 0.0):
        as_set = _spec(2, gap, labels=True)
        unbroken = _spec(1, gap, labels=True)
        names = _seam_labels(as_set)
        edge = round(render.GEO_EDGE_IN * DPI)
        band = panels.seam_bands_px(as_set, DPI, edge // 2)[0]
        x0, x1 = band[0], band[2]
        # the control: with one panel the two names do paint in the band
        plain = _render(_spec(1, gap))
        assert (_render(unbroken, names)[:, x0:x1] != plain[:, x0:x1]).any()
        # the set: nothing of a name is in the band
        bare = _render(_spec(2, gap))
        assert np.array_equal(_render(as_set, names)[:, x0:x1], bare[:, x0:x1]), gap


LONG_NAMES = ["Seam Peak of the Long Name Told in Full Here",
              "Gap Butte of the Long Name Told in Full Here",
              "Edge Knob of the Long Name Told in Full Here"]


def _summits_at(spec, x_px, names):
    """Summits that share one anchor at x_px, clear of the route. Smart placement
    gives the anchor to the first and pushes the next ones out, each with a leader."""
    w, _ = spec.pixel_size(DPI)
    x = spec.crop[0] + (spec.crop[2] - spec.crop[0]) * x_px / w
    cy = (spec.crop[1] + spec.crop[3]) / 2
    return {"crs": _cfg()["crs"], "features": [
        {"name": name, "kind": "summit", "rank": 100, "coords": [[x, cy + 6000]]}
        for name in names]}


def _watch_leaders(monkeypatch):
    """Each leader that is drawn from now on, as (anchor, label_box)."""
    drawn = []
    draw = render._draw_leader

    def spy(d, anchor, label_box, dpi):
        drawn.append((anchor, label_box))
        return draw(d, anchor, label_box, dpi)
    monkeypatch.setattr(render, "_draw_leader", spy)
    return drawn


def _leader_x(anchor, label_box):
    """(lo, hi): the x span of a leader's line, as _draw_leader draws it."""
    ax = anchor[0]
    tx = min(max(ax, label_box[0]), label_box[2])
    return min(ax, tx), max(ax, tx)


def test_a_leader_stays_in_the_box_the_placement_reads():
    from PIL import Image, ImageDraw
    for dpi in (40, 96, 300):
        for anchor, box in (((400, 400), (520, 300, 700, 330)),      # pushed up and right
                            ((400, 400), (100, 480, 280, 510)),      # pushed down and left
                            ((400, 400), (310, 250, 490, 280))):     # pushed above
            img = Image.new("RGBA", (800, 800), (0, 0, 0, 0))
            render._draw_leader(ImageDraw.Draw(img, "RGBA"), anchor, box, dpi)
            ys, xs = np.nonzero(np.asarray(img)[..., 3])
            x0, y0, x1, y1 = render._leader_bounds(anchor, box, dpi)
            assert x0 <= xs.min() and xs.max() < x1 and y0 <= ys.min() and ys.max() < y1
            slack = 0.1 * dpi + 2                # and the box is not a loose guess
            assert xs.min() - x0 <= slack and x1 - 1 - xs.max() <= slack


def test_no_leader_or_anchor_dot_is_drawn_in_a_seam_band(monkeypatch):
    drawn = _watch_leaders(monkeypatch)
    for gap in (2.0, 0.0):
        as_set = _spec(2, gap, labels=True, label_place="smart")
        unbroken = _spec(1, gap, labels=True, label_place="smart")
        edge = round(render.GEO_EDGE_IN * DPI)
        full = panels.seam_bands_px(as_set, DPI, edge)[0]
        band = panels.seam_bands_px(as_set, DPI, edge // 2)[0]
        x0, x1 = band[0], band[2]
        # two names anchored on the middle of the gap strip, or on the seam of a cut set
        names = _summits_at(as_set, (full[0] + full[2]) / 2, LONG_NAMES[:2])
        # the control: with one panel a name is pushed out, and its leader starts in the band
        plain = _render(_spec(1, gap))
        drawn.clear()
        assert (_render(unbroken, names)[:, x0:x1] != plain[:, x0:x1]).any()
        assert [a for a, _ in drawn if x0 <= a[0] < x1], gap
        # the set: no name, no leader and no anchor dot is in the band
        bare = _render(_spec(2, gap))
        drawn.clear()
        assert np.array_equal(_render(as_set, names)[:, x0:x1], bare[:, x0:x1]), gap
        assert not drawn, gap


def test_no_leader_crosses_a_seam_band(monkeypatch):
    drawn = _watch_leaders(monkeypatch)
    for gap in (2.0, 0.0):
        as_set = _spec(2, gap, labels=True, label_place="smart")
        unbroken = _spec(1, gap, labels=True, label_place="smart")
        edge = round(render.GEO_EDGE_IN * DPI)
        full = panels.seam_bands_px(as_set, DPI, edge)[0]
        band = panels.seam_bands_px(as_set, DPI, edge // 2)[0]
        x0, x1 = band[0], band[2]

        def crossing():
            return [(a, b) for a, b in drawn
                    if _leader_x(a, b)[0] < full[2] and _leader_x(a, b)[1] >= full[0]]

        # three names anchored in panel 1, next to the band: two fit beside the anchor,
        # and the only free place for a pushed-out name is on the far side of the seam
        names = _summits_at(as_set, full[0] - 3, LONG_NAMES)
        # the control: with one panel a leader runs through the band
        plain = _render(_spec(1, gap))
        drawn.clear()
        assert (_render(unbroken, names)[:, x0:x1] != plain[:, x0:x1]).any()
        assert crossing(), gap
        # the set: the names that fit in panel 1 are drawn, and nothing is in the band
        bare = _render(_spec(2, gap))
        drawn.clear()
        out = _render(as_set, names)
        assert (out[:, :full[0]] != bare[:, :full[0]]).any(), gap
        assert np.array_equal(out[:, x0:x1], bare[:, x0:x1]), gap
        assert not crossing(), gap


def test_a_name_whose_feature_is_in_a_seam_band_is_not_drawn(monkeypatch):
    drawn = _watch_leaders(monkeypatch)
    for gap in (2.0, 0.0):
        as_set = _spec(2, gap, labels=True, label_place="smart")
        unbroken = _spec(1, gap, labels=True, label_place="smart")
        edge = round(render.GEO_EDGE_IN * DPI)
        full = panels.seam_bands_px(as_set, DPI, edge)[0]
        # the last pixel of the band: a slot up and right of the anchor is clear of it
        names = _summits_at(as_set, full[2] - 1, LONG_NAMES[:1])
        assert (_render(unbroken, names) != _render(_spec(1, gap))).any()   # the control
        assert np.array_equal(_render(as_set, names), _render(_spec(2, gap))), gap
    assert not drawn
