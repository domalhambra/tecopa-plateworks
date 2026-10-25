# tests/test_photo_band.py
"""Order photos (Task 5): the gallery band across the top or the bottom of the map,
the furniture taking the other end, and the occupancy the open-ground layout reads."""
import dataclasses
import json
import os
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from app import panels, render
from app.spec import CompositionSpec
from tests.conftest import synthetic_region

COLOURS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 0, 255), (0, 255, 255),
           (255, 255, 0), (255, 128, 0)]


def _photos(tmp_path, n):
    out = []
    for i in range(n):
        p = tmp_path / f"p{i}.png"
        Image.new("RGB", (120, 90), COLOURS[i]).save(p)
        out.append(str(p))
    return out


def _sheet(hotspots, w=12.0, h=18.0, **kw):
    base = dict(region_id="t", crs="EPSG:32610", crop=(0.0, 0.0, 1000.0 * w, 1000.0 * h),
                print_w_in=w, print_h_in=h, native_resolution_m=10, tracks=[],
                hotspots=hotspots, seed=7, title_text="Tecopa", photo_box_in=2.0)
    base.update(kw)
    return CompositionSpec(**base)


def _spots(spec, photos, labels=None):
    """One hotspot per photo, spread across the middle of the map."""
    x0, y0, x1, y1 = spec.crop
    n = len(photos)
    return [{"x": x0 + (x1 - x0) * (i + 1) / (n + 1), "y": (y0 + y1) / 2, "weight": 1,
             "photo": p, **({"label": labels[i]} if labels else {})}
            for i, p in enumerate(photos)]


def _band(tmp_path, n=3, side="top", **kw):
    spec = _sheet([], **kw)
    hs = _spots(spec, _photos(tmp_path, n))
    return replace(spec, hotspots=hs, photo_layout="band", photo_band_side=side)


def _overlays(spec, dpi):
    w, h = spec.pixel_size(dpi)
    blank = Image.new("RGBA", (w, h), (128, 128, 128, 255))
    return np.asarray(render._paint_overlays(blank, spec, np.zeros((h, w)), w, h, dpi))


def _boxes(out, n):
    """(x0, y0, x1, y1) of each photo's solid colour, inclusive."""
    found = []
    for rgb in COLOURS[:n]:
        ys, xs = np.nonzero(np.all(out[..., :3] == rgb, axis=2))
        assert xs.size, rgb
        found.append((xs.min(), ys.min(), xs.max(), ys.max()))
    return found


def _keepout(spec, dpi):
    w, h = spec.pixel_size(dpi)
    return render._label_keepout(spec, ImageDraw.Draw(Image.new("RGBA", (w, h))), w, h, dpi)


def test_band_draws_numbered_boxes_across_the_top(tmp_path, monkeypatch):
    dpi = 30
    spec = _band(tmp_path, 3, "top", keyline=False, title_text="", compass=False)
    drawn = []
    real = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **kw):
        drawn.append(text)
        return real(self, xy, text, *a, **kw)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", spy)
    out = _overlays(spec, dpi)
    w, h = spec.pixel_size(dpi)
    band_px = render.band_height_in(spec) * dpi
    inset = render.KEYLINE_INSET_IN * dpi
    boxes = _boxes(out, 3)
    side = round(spec.photo_box_in * dpi)
    for x0, y0, x1, y1 in boxes:
        assert x1 - x0 + 1 == side and y1 - y0 + 1 == side     # centre-cropped squares
        assert y0 >= inset and y1 < inset + band_px            # in the top strip
        assert x0 >= inset and x1 < w - inset                  # inside the trim
    assert [b[0] for b in boxes] == sorted(b[0] for b in boxes)  # hotspot order, left to right
    assert len({b[1] for b in boxes}) == 1                     # one row
    # each box carries its number, and each spot gets the same numbered mark
    for k in ("1", "2", "3"):
        assert drawn.count(k) == 2, (k, repr(drawn))
    assert len(drawn) == 6


def test_band_height_is_physical_and_holds_the_band(tmp_path):
    spec = _band(tmp_path, 3, "top", keyline=False)
    m = render._photo_frame_fracs(spec.photo_frame_style)
    caption = spec.label_pt * render.PHOTO_CAPTION_LINE_EM / 72.0
    want = spec.photo_box_in * (1 + m[1] + m[2]) + 2 * render.BAND_PAD_IN + caption
    assert render.band_height_in(spec) == pytest.approx(want)
    assert render.BAND_PAD_IN == 0.25
    # no dpi in it: the same inches at a proof and at a final
    for dpi in (20, 40):
        rect = [r for r in _keepout(spec, dpi) if r[1] == round(render.KEYLINE_INSET_IN * dpi)]
        assert rect, dpi                                        # the band is a label keep-out
        assert rect[0][3] - rect[0][1] == pytest.approx(render.band_height_in(spec) * dpi, abs=1)


def test_a_crowded_band_shrinks_its_boxes_to_one_row(tmp_path):
    dpi = 20
    spec = _band(tmp_path, 7, "top", keyline=False, w=12.0, h=18.0)
    out = _overlays(spec, dpi)
    boxes = _boxes(out, 7)
    w, _ = spec.pixel_size(dpi)
    assert len({b[1] for b in boxes}) == 1
    for a, b in zip(boxes, boxes[1:]):
        assert a[2] < b[0]                                     # no two boxes touch
    assert boxes[-1][2] < w - render.KEYLINE_INSET_IN * dpi


def test_a_bottom_band_moves_the_furniture_to_the_upper_left(tmp_path):
    dpi = 30
    spec = _band(tmp_path, 3, "bottom", compass=True, profile=True)
    w, h = spec.pixel_size(dpi)
    d = ImageDraw.Draw(Image.new("RGBA", (w, h)))
    stack = render._furniture_stack_rects(spec, d, 0, h, dpi, ty0=0)
    m = render._title_block_metrics(spec, d, dpi)
    title = [r for r in stack if r[2] - r[0] >= m["bw"]][0]
    assert title[3] < h / 3 and title[0] == 0                   # top third, left edge
    assert all(r[3] < h / 2 for r in stack)                     # the compass too
    rects = _keepout(spec, dpi)
    assert all(r in rects for r in stack)                       # labels avoid its new place
    strip = render._profile_rect(spec, d, (0, 0, w, h), dpi)
    assert strip in rects and strip[1] >= max(r[3] for r in stack)   # the strip under it
    assert strip[3] < h / 2
    out = _overlays(spec, dpi)
    painted = np.any(out[..., :3] != 128, axis=2)
    tx0, ty0, tx1, ty1 = title
    assert painted[ty0:ty1, tx0:tx1].any()                      # the cartouche is drawn there
    inset = round(render.KEYLINE_INSET_IN * dpi)
    for x0, y0, x1, y1 in _boxes(out, 3):
        assert y0 > h - inset - render.band_height_in(spec) * dpi   # the band at the bottom
    # the lower left is free of furniture down to the band (the spots' marks sit on
    # the middle row, so the check starts below them)
    band_top = round(h - inset - render.band_height_in(spec) * dpi)
    below_marks = h // 2 + round(spec.marker_diameter_in * dpi)
    assert not painted[below_marks:band_top - 1, inset + 2:w // 3].any()


def test_a_top_band_or_no_band_leaves_the_furniture_where_it_is(tmp_path):
    dpi = 30
    plain = _sheet([], compass=True, profile=True)
    top = _band(tmp_path, 3, "top", compass=True, profile=True)
    w, h = plain.pixel_size(dpi)
    d = ImageDraw.Draw(Image.new("RGBA", (w, h)))
    assert (render._furniture_stack_rects(top, d, 0, h, dpi)
            == render._furniture_stack_rects(plain, d, 0, h, dpi))
    assert render._profile_rect(top, d, (0, 0, w, h), dpi) == render._profile_rect(
        plain, d, (0, 0, w, h), dpi)
    a, b = _overlays(plain, dpi), _overlays(top, dpi)
    for x0, y0, x1, y1 in render._furniture_stack_rects(plain, d, 0, h, dpi):
        assert np.array_equal(a[y0:y1, x0:x1], b[y0:y1, x0:x1])   # the same pixels
    # the band fields with no photo change nothing at all
    for side in ("top", "bottom"):
        idle = replace(plain, photo_layout="band", photo_band_side=side)
        assert np.array_equal(_overlays(idle, dpi), a)
        assert _keepout(idle, dpi) == _keepout(plain, dpi)


def test_band_avoids_seams_on_a_set(tmp_path):
    dpi = 20
    w_in, h_in = panels.sheet_sizes(3, 2.0)[0]
    spec = _sheet([], w=w_in, h=h_in, panels=3, panel_gap_in=2.0, keyline=False)
    spec = replace(spec, hotspots=_spots(spec, _photos(tmp_path, 7)), photo_layout="band")
    out = _overlays(spec, dpi)
    boxes = _boxes(out, 7)
    seams = panels.seam_bands_px(spec, dpi, round(render.GEO_EDGE_IN * dpi))
    for x0, y0, x1, y1 in boxes:
        for s0, _, s1, _ in seams:
            assert x1 < s0 or x0 >= s1                           # no box crosses a seam band
    frames = panels.panel_rects_px(spec, dpi)
    assert frames[0][0] <= boxes[0][0] < frames[0][2]           # the band runs across the
    assert frames[2][0] <= boxes[-1][0] < frames[2][2]          # whole hung width
    assert [b[0] for b in boxes] == sorted(b[0] for b in boxes)


def test_band_caption_sits_under_its_box(tmp_path):
    dpi = 30
    spec = _sheet([], keyline=False)
    hs = _spots(spec, _photos(tmp_path, 2), labels=["Bumpass Hell", "Lassen Peak"])
    spec = replace(spec, hotspots=hs, photo_layout="band")
    out = _overlays(spec, dpi)
    boxes = _boxes(out, 2)
    plate = np.all(out[..., :3] == render.LABEL_PLATE, axis=2)
    for x0, y0, x1, y1 in boxes:
        below = plate[y1 + 1:y1 + round(0.6 * dpi), x0:x1 + 1]
        assert below.any()                                       # a caption plate under it


REGION_DIR = synthetic_region("lassen_ca")


def _cfg():
    return json.load(open(os.path.join(REGION_DIR, "region.json")))


def _region_spec(**kw):
    cfg = _cfg(); bx = cfg["bounds"]
    cx = (bx[0] + bx[2]) / 2; cy = (bx[1] + bx[3]) / 2
    w, h = 12.0, 18.0
    half = 15000.0
    crop = (cx - half, cy - half * h / w, cx + half, cy + half * h / w)
    base = dict(region_id="lassen_ca", crs=cfg["crs"], crop=crop, print_w_in=w,
                print_h_in=h, native_resolution_m=10,
                tracks=[np.array([[cx - 10000, cy], [cx + 10000, cy]])],
                hotspots=[], seed=7, title_text="Lassen", compass=True)
    base.update(kw)
    return CompositionSpec(**base)


def test_occupancy_marks_routes_and_furniture(monkeypatch):
    spec = _region_spec()
    dpi = 20

    def no_relief(*a, **kw):
        raise AssertionError("occupancy painted the relief")
    monkeypatch.setattr(render, "_relief_or_override", no_relief)
    occ = render.occupancy(spec, REGION_DIR, dpi, cfg=_cfg())
    w, h = spec.pixel_size(dpi)
    assert occ.size_px == (w, h) and occ.route.shape == (h, w) and occ.route.dtype == bool
    assert occ.dpi == 20.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        occ.dpi = 30
    # the route, grown by the clearance: the track runs across the middle row
    assert occ.route[h // 2, w // 2]
    reach = render.PHOTO_ROUTE_CLEARANCE_IN * dpi
    col = np.nonzero(occ.route[:, w // 2])[0]
    assert col.max() - col.min() + 1 >= 2 * reach
    assert not occ.route[h // 4, w // 2] and not occ.route[:, :round(w * 0.05)].any()
    # the furniture: every label keep-out rect, the title block among them
    d = ImageDraw.Draw(Image.new("RGBA", (w, h)))
    stack = render._furniture_stack_rects(spec, d, 0, h, dpi)
    m = render._title_block_metrics(spec, d, dpi)
    assert any(r[2] - r[0] >= m["bw"] for r in occ.rects)        # the title block
    assert all(r in occ.rects for r in stack)
    assert occ.trim_px == (0, 0, w, h)


def test_occupancy_of_a_bleed_sheet_reports_its_trim():
    spec = _region_spec(bleed_in=0.125)
    dpi = 20
    occ = render.occupancy(spec, REGION_DIR, dpi, cfg=_cfg())
    w, h = spec.pixel_size(dpi)
    b = round(0.125 * dpi)
    assert occ.size_px == (w, h) and occ.trim_px == (b, b, w - b, h - b)


def test_occupancy_follows_the_route_under_high_relief():
    # the route under the plan-oblique warp: the cheap context must register exactly
    # with the painted one
    spec = _region_spec(oblique=0.8)
    dpi = 12
    occ = render.occupancy(spec, REGION_DIR, dpi, cfg=_cfg())
    _, ctx, _ = render._paint_terrain(spec, dpi, REGION_DIR, _cfg(), hydro={"lakes": [], "rivers": []})
    assert ctx is not None
    cheap = render._oblique_ctx(spec, dpi, REGION_DIR, _cfg())
    assert np.array_equal(cheap.winner, ctx.winner) and cheap.s == ctx.s
    flat = render.occupancy(replace(spec, oblique=0.0), REGION_DIR, dpi, cfg=_cfg())
    assert not np.array_equal(occ.route, flat.route)              # the warp moved the route
