# tests/test_panel_furniture.py
from dataclasses import replace

import numpy as np
from PIL import Image, ImageDraw

from app import panels, render
from app.spec import CompositionSpec


def _set(n=3, gap=2.0, shape="wide", **kw):
    w, h = panels.sheet_sizes(n, gap)[0 if shape == "wide" else 1]
    base = dict(region_id="t", crs="EPSG:32610", crop=(0.0, 0.0, 1000.0 * w, 1000.0 * h),
                print_w_in=w, print_h_in=h, native_resolution_m=10, tracks=[], hotspots=[],
                seed=7, panels=n, panel_gap_in=gap, title_text="Tecopa")
    base.update(kw)
    return CompositionSpec(**base)


def _keepout(spec, dpi):
    w, h = spec.pixel_size(dpi)
    d = ImageDraw.Draw(Image.new("RGBA", (w, h)))
    return render._label_keepout(spec, d, w, h, dpi)


def test_the_keepout_of_a_set_holds_each_seam_band():
    spec = _set(3, 2.0)
    dpi = 40
    edge = round(render.GEO_EDGE_IN * dpi)
    rects = _keepout(spec, dpi)
    for band in panels.seam_bands_px(spec, dpi, edge):
        assert band in rects
    gap = panels.gap_rects_px(spec, dpi)[0]
    band = panels.seam_bands_px(spec, dpi, edge)[0]
    assert band[0] == gap[0] - edge and band[2] == gap[2] + edge


def test_the_keepout_of_a_cut_set_holds_a_band_on_each_seam():
    spec = _set(2, 0.0, "tall")
    dpi = 40
    edge = round(render.GEO_EDGE_IN * dpi)
    seam = panels.panel_rects_px(spec, dpi)[0][2]
    h = spec.pixel_size(dpi)[1]
    assert (seam - edge, 0, seam + edge, h) in _keepout(spec, dpi)


def test_the_keepout_of_a_single_sheet_has_no_band():
    single = _set(3, 2.0, panels=1, panel_gap_in=0.0)
    h = single.pixel_size(40)[1]
    assert not [r for r in _keepout(single, 40) if r[1] == 0 and r[3] == h]


def test_a_marker_label_stays_inside_its_panel():
    spec = _set(2, 2.0, "tall")
    dpi = 40
    w, h = spec.pixel_size(dpi)
    lo, hi = panels.span_px_at(spec, 600, dpi, w)            # an anchor in panel 1
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    render._draw_label(d, "A long marker label", hi - 20, h // 2, render._font(14),
                       w, h, x_lo=lo, x_hi=hi)
    xs = np.nonzero(np.asarray(img)[..., 3])[1]
    assert xs.min() >= lo and xs.max() < hi


def test_a_marker_label_in_a_later_panel_does_not_start_before_it():
    spec = _set(2, 2.0, "tall")
    dpi = 40
    w, h = spec.pixel_size(dpi)
    lo, hi = panels.span_px_at(spec, 745, dpi, w)            # behind the gap: panel 2 is nearer
    assert lo > 0
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    render._draw_label(ImageDraw.Draw(img, "RGBA"), "Camp", lo - 30, h // 2,
                       render._font(14), w, h, x_lo=lo, x_hi=hi)
    xs = np.nonzero(np.asarray(img)[..., 3])[1]
    assert xs.min() >= lo and xs.max() < hi


def test_a_marker_label_on_a_single_sheet_is_placed_as_before():
    w, h = 400, 200
    a = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    b = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    render._draw_label(ImageDraw.Draw(a, "RGBA"), "Camp", 380, 100, render._font(14), w, h)
    render._draw_label(ImageDraw.Draw(b, "RGBA"), "Camp", 380, 100, render._font(14), w, h,
                       x_lo=0, x_hi=w)
    assert np.array_equal(np.asarray(a), np.asarray(b))


def _marker_at(spec, x_px, dpi, **hs):
    """A hotspot whose anchor is at x_px, on the middle row of the sheet."""
    w, _ = spec.pixel_size(dpi)
    x = spec.crop[0] + (spec.crop[2] - spec.crop[0]) * x_px / w
    return dict(x=x, y=(spec.crop[1] + spec.crop[3]) / 2, weight=3, **hs)


def test_the_label_of_a_marker_next_to_a_seam_ends_inside_its_panel():
    dpi = 40
    spec = _set(2, 2.0, "tall")
    w, h = spec.pixel_size(dpi)
    lo, hi = panels.panel_rects_px(spec, dpi)[0][0], panels.panel_rects_px(spec, dpi)[0][2]
    lum = np.ones((h, w), np.float32)

    def drawn(s):
        blank = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        marked = replace(s, hotspots=[_marker_at(s, hi - 40, dpi, label="A long marker label")])
        out = np.asarray(render._draw_markers(blank, marked, lum, w, h, dpi))
        return np.nonzero(out[..., 3] >= 200)[1]     # the disc and the plate; not the soft shadow

    single = _set(2, 2.0, "tall", panels=1, panel_gap_in=0.0)
    assert drawn(single).max() >= hi            # the control: one sheet lets it cross
    xs = drawn(spec)
    assert xs.min() >= lo and xs.max() < hi


def test_a_photo_box_stays_inside_the_panel_of_its_anchor(tmp_path):
    dpi = 40
    p = tmp_path / "pic.png"
    Image.new("RGB", (80, 80), (255, 0, 255)).save(p)
    spec = _set(2, 2.0, "tall", photo_box_in=2.0)
    w, h = spec.pixel_size(dpi)
    lo, hi = panels.panel_rects_px(spec, dpi)[0][0], panels.panel_rects_px(spec, dpi)[0][2]

    def solid(s):
        blank = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        pinned = replace(s, hotspots=[_marker_at(s, hi - 20, dpi, photo=str(p))])
        out = np.asarray(render._draw_photos(blank, pinned, w, h, dpi))
        return np.nonzero(out[..., 3] == 255)[1]     # frame, photo and stem; not the soft shadow

    single = _set(2, 2.0, "tall", panels=1, panel_gap_in=0.0, photo_box_in=2.0)
    assert solid(single).max() >= hi            # the control: one sheet lets it cross
    xs = solid(spec)
    assert xs.min() >= lo and xs.max() < hi


def _overlays(spec, dpi, **kw):
    w, h = spec.pixel_size(dpi)
    blank = Image.new("RGBA", (w, h), (128, 128, 128, 255))
    out = render._paint_overlays(blank, spec, np.zeros((h, w)), w, h, dpi, **kw)
    return np.any(np.asarray(out) != 128, axis=2)


def test_a_set_sizes_its_furniture_as_one_panel_does():
    single = _set(3, 2.0, panels=1, panel_gap_in=0.0, print_w_in=17, print_h_in=22,
                  crop=(0.0, 0.0, 17000.0, 22000.0))
    for n, shape in ((2, "wide"), (3, "wide"), (2, "tall"), (3, "tall")):
        assert render._furniture_scale(_set(n, 4.0, shape)) == render._furniture_scale(single)


def test_nothing_is_painted_in_a_gap_strip():
    spec = _set(3, 2.0)
    dpi = 40
    painted = _overlays(spec, dpi, watermark=True)
    for x0, y0, x1, y1 in panels.gap_rects_px(spec, dpi):
        assert not painted[y0:y1, x0:x1].any()


def test_each_panel_has_its_own_keyline_and_mark():
    spec = _set(3, 2.0)
    dpi = 40
    painted = _overlays(spec, dpi)
    inset = round(render.KEYLINE_INSET_IN * dpi)
    d = ImageDraw.Draw(Image.new("RGBA", spec.pixel_size(dpi)))
    frames = panels.panel_rects_px(spec, dpi)
    marks = render._panel_mark_rects(spec, d, frames, dpi)
    assert len(marks) == 3
    for (x0, y0, x1, y1), (mx0, my0, mx1, my1) in zip(frames, marks):
        assert painted[y0 + inset, x0 + inset:x1 - inset].all()          # the top keyline
        assert painted[y0 + inset:y1 - inset, x1 - 1 - inset].all()      # the right keyline
        assert x0 < mx0 and mx1 <= x1 and my1 <= y1                      # the mark is in the panel
        assert mx0 > (x0 + x1) / 2 and my0 > (y0 + y1) / 2               # lower right
        assert painted[my0:my1, mx0:mx1].any()


def test_the_title_block_is_inside_panel_one():
    spec = _set(3, 2.0, keyline=False)
    dpi = 40
    painted = _overlays(spec, dpi)
    frames = panels.panel_rects_px(spec, dpi)
    d = ImageDraw.Draw(Image.new("RGBA", spec.pixel_size(dpi)))
    marks = render._panel_mark_rects(spec, d, frames, dpi)
    for (x0, y0, x1, y1), (mx0, my0, mx1, my1) in list(zip(frames, marks))[1:]:
        outside_mark = painted[y0:y1, x0:x1].copy()
        outside_mark[my0 - y0:my1 - y0, mx0 - x0:mx1 - x0] = False
        assert not outside_mark.any()        # panels 2 and 3 carry the mark and nothing more
    x0, y0, x1, y1 = frames[0]
    assert painted[(y0 + y1) // 2:y1, x0:(x0 + x1) // 2].any()           # lower left of panel 1


def test_each_panel_mark_is_a_label_keepout():
    spec = _set(2, 0.0, "tall")
    dpi = 40
    d = ImageDraw.Draw(Image.new("RGBA", spec.pixel_size(dpi)))
    marks = render._panel_mark_rects(spec, d, panels.panel_rects_px(spec, dpi), dpi)
    rects = _keepout(spec, dpi)
    assert all(m in rects for m in marks)


def test_the_watermark_word_is_drawn_on_each_panel():
    spec = _set(2, 2.0, "tall", keyline=False, compass=False, title_text="")
    dpi = 40
    proof = _overlays(spec, dpi, watermark=True)
    preview = _overlays(spec, dpi, watermark=True, watermark_text="PREVIEW")
    assert np.array_equal(proof, _overlays(spec, dpi, watermark=True, watermark_text="PROOF"))
    for x0, y0, x1, y1 in panels.panel_rects_px(spec, dpi):
        top = slice(y0, y0 + (y1 - y0) // 2)
        assert proof[top, x0:x1].any() and preview[top, x0:x1].any()
        short, long_ = (np.nonzero(a[top, x0:x1].any(axis=0))[0] for a in (proof, preview))
        assert np.ptp(long_) > np.ptp(short)          # the longer word is the one drawn
    assert not np.array_equal(proof, preview)


def test_the_elevation_strip_of_a_set_is_in_panel_one_and_in_the_keepout():
    # a strip this high is wider than one panel unless panel 1 is the box that clamps it
    spec = _set(2, 2.0, "tall", profile=True, profile_height_in=6.0, keyline=False)
    dpi = 40
    climb = (np.linspace(0.0, 9000.0, 50), np.linspace(1000.0, 2000.0, 50))
    painted = _overlays(spec, dpi, profile=climb)
    d = ImageDraw.Draw(Image.new("RGBA", spec.pixel_size(dpi)))
    frames = panels.panel_rects_px(spec, dpi)
    strip = render._profile_rect(spec, d, frames[0], dpi)
    assert strip in _keepout(spec, dpi)                  # the painter's box is the keep-out's
    sx0, sy0, sx1, sy1 = strip
    assert painted[(sy0 + sy1) // 2, sx0:sx1].all()       # the strip is drawn, edge to edge
    assert painted[sy0:sy1, (sx0 + sx1) // 2].all()
    x0, y0, x1, y1 = frames[0]
    assert x0 <= sx0 and sx1 < x1 and y0 <= sy0 and sy1 < y1
    stack = render._furniture_stack_rects(spec, d, x0, y1, dpi)
    assert all(r in _keepout(spec, dpi) and r[2] <= x1 for r in stack)   # title and compass too
    px0, py0, px1, py1 = frames[1]
    mx0, my0, mx1, my1 = render._panel_mark_rects(spec, d, frames, dpi)[1]
    rest = painted[py0:py1, px0:px1].copy()
    rest[my0 - py0:my1 - py0, mx0 - px0:mx1 - px0] = False
    assert not rest.any()                                # panel 2 has its mark and no strip
