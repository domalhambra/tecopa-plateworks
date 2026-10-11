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
