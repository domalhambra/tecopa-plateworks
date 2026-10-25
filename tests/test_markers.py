# tests/test_markers.py
# Rich-marker drawing (labels, vector icons, pinned photos) exercised directly on
# blank canvases -- no DEM needed, so these run on a fresh clone.
import numpy as np
from PIL import Image
from app.spec import CompositionSpec
from app import render

def _spec(hotspots, **kw):
    return CompositionSpec(
        region_id="t", crs="EPSG:32610", crop=(0, 0, 1000, 1000),
        print_w_in=10, print_h_in=10, native_resolution_m=10,
        tracks=[], hotspots=hotspots, seed=7, **kw)

def _blank(w, h):
    return Image.new("RGBA", (w, h), (128, 128, 128, 255))

def test_each_icon_draws_ink():
    w = h = 400
    lum = np.ones((h, w), np.float32)                  # light bg -> dark ring + ink
    for icon in ("peak", "camp", "water", "flag", "camera", "star"):
        spec = _spec([{"x": 500, "y": 500, "weight": 3, "icon": icon}],
                     marker_diameter_in=0.8)
        out = np.asarray(render._draw_markers(_blank(w, h), spec, lum, w, h, dpi=96).convert("RGB"))
        # gold disc present, and dark glyph ink somewhere inside it
        gold = (np.abs(out[..., 0].astype(int) - 190) < 40) & (out[..., 2] < 130)
        dark = (out.sum(axis=2) < 200)
        assert gold.sum() > 50, icon
        assert dark.sum() > 5, icon

def test_label_renders_plate_and_text():
    w = h = 400
    lum = np.ones((h, w), np.float32)
    spec = _spec([{"x": 200, "y": 500, "weight": 3, "label": "Eagle Lake"}],
                 marker_diameter_in=0.4, label_pt=24)
    base = np.asarray(_blank(w, h).convert("RGB"))
    out = np.asarray(render._draw_markers(_blank(w, h), spec, lum, w, h, dpi=96).convert("RGB"))
    assert not np.array_equal(base, out)               # something was drawn
    cream = (out[..., 0] > 225) & (out[..., 1] > 220) & (out[..., 2] > 200)
    assert cream.sum() > 100                            # the cream label plate

def test_photo_pin_composites_and_tolerates_missing(tmp_path):
    w = h = 600
    p = tmp_path / "pic.png"
    Image.new("RGB", (80, 80), (255, 0, 255)).save(p)   # vivid magenta, not in any palette
    spec = _spec([{"x": 500, "y": 500, "weight": 3, "photo": str(p)}], photo_box_in=2.0)
    out = np.asarray(render._draw_photos(_blank(w, h), spec, w, h, dpi=96).convert("RGB"))
    magenta = (out[..., 0] > 200) & (out[..., 1] < 80) & (out[..., 2] > 200)
    assert magenta.sum() > 200                          # the photo thumbnail landed

    # a missing file must not crash the render -- it is simply skipped
    spec2 = _spec([{"x": 500, "y": 500, "weight": 3, "photo": str(tmp_path / "nope.png")}])
    render._draw_photos(_blank(w, h), spec2, w, h, dpi=96)

def test_marker_ring_slider_and_size():
    # ring=0 -> no outline ring pixels; a bigger marker_diameter_in -> more disc pixels
    w = h = 400
    lum = np.zeros((h, w), np.float32)               # dark bg -> would get a PAPER ring
    base_kw = dict(marker_diameter_in=0.5)
    ringed = np.asarray(render._draw_markers(
        _blank(w, h), _spec([{"x": 500, "y": 500, "weight": 3}], **base_kw),
        lum, w, h, dpi=96).convert("RGB"))
    ringless = np.asarray(render._draw_markers(
        _blank(w, h), _spec([{"x": 500, "y": 500, "weight": 3}], marker_ring=0.0, **base_kw),
        lum, w, h, dpi=96).convert("RGB"))
    paper = lambda a: ((a[..., 0] > 230) & (a[..., 1] > 225) & (a[..., 2] > 210)).sum()
    assert paper(ringed) > 50, "no ring drawn at default"
    assert paper(ringless) < paper(ringed) / 4, "ring=0 still draws a ring"
    small = np.asarray(render._draw_markers(
        _blank(w, h), _spec([{"x": 500, "y": 500, "weight": 3}], marker_diameter_in=0.14),
        lum, w, h, dpi=96).convert("RGB"))
    gold = lambda a: ((np.abs(a[..., 0].astype(int) - 190) < 40) & (a[..., 2] < 130)).sum()
    assert gold(ringless) > gold(small) * 3, "marker size slider has no effect"

def test_photo_frame_styles(tmp_path):
    from PIL import Image as _Im
    w = h = 600
    p = tmp_path / "pic.png"
    _Im.new("RGB", (80, 80), (255, 0, 255)).save(p)
    def frame_pixels(style):
        spec = _spec([{"x": 500, "y": 500, "weight": 3, "photo": str(p)}],
                     photo_box_in=2.0, photo_frame_style=style)
        out = np.asarray(render._draw_photos(_blank(w, h), spec, w, h, dpi=96).convert("RGB"))
        cream = ((out[..., 0] > 230) & (out[..., 1] > 225) & (out[..., 2] > 200)).sum()
        magenta = ((out[..., 0] > 200) & (out[..., 1] < 80) & (out[..., 2] > 200)).sum()
        return cream, magenta
    mat_cream, mat_mag = frame_pixels("mat")
    pol_cream, pol_mag = frame_pixels("polaroid")
    bare_cream, bare_mag = frame_pixels("borderless")
    key_cream, key_mag = frame_pixels("keyline")
    assert all(m > 200 for m in (mat_mag, pol_mag, bare_mag, key_mag))  # photo lands in all
    assert pol_cream > mat_cream, "polaroid bottom mat missing"
    assert bare_cream < mat_cream / 10, "borderless still draws a mat"
    assert key_cream < mat_cream / 2, "keyline mat too heavy"


# ---- order photos (Task 5): a box where the layout puts it, and a crop focus --------
import hashlib
import math

def _solid(tmp_path, name, rgb, size=(80, 80)):
    p = tmp_path / name
    Image.new("RGB", size, rgb).save(p)
    return str(p)

def _halves(tmp_path):
    """A landscape photo, red on the left half and blue on the right."""
    p = tmp_path / "halves.png"
    a = np.zeros((100, 200, 3), np.uint8)
    a[:, :100] = (255, 0, 0)
    a[:, 100:] = (0, 0, 255)
    Image.fromarray(a, "RGB").save(p)
    return str(p)

def _pattern(path):
    yy, xx = np.mgrid[0:90, 0:120]
    a = np.stack([(xx * 2) % 256, (yy * 3) % 256, ((xx + yy) * 5) % 256], -1)
    Image.fromarray(a.astype(np.uint8), "RGB").save(path)

def _magenta(a):
    return (a[..., 0] > 200) & (a[..., 1] < 80) & (a[..., 2] > 200)

def test_a_box_offset_moves_the_box(tmp_path):
    w = h = 600                        # 10 x 10 in at 60 dpi; the spot is at (300, 300)
    dpi = 60
    p = _solid(tmp_path, "m.png", (255, 0, 255))
    spec = _spec([{"x": 500, "y": 500, "weight": 3, "photo": p,
                   "box": {"dx_in": -2.5, "dy_in": 2.0}}], photo_box_in=1.0)
    out = np.asarray(render._draw_photos(_blank(w, h), spec, w, h, dpi=dpi).convert("RGB"))
    ys, xs = np.nonzero(_magenta(out))
    # the box is centred at the spot + the offset: (300 - 150, 300 + 120)
    assert abs((xs.min() + xs.max()) / 2 - 150) <= 1
    assert abs((ys.min() + ys.max()) / 2 - 420) <= 1
    assert xs.max() - xs.min() + 1 == 60 and ys.max() - ys.min() + 1 == 60   # a 1 in box
    ms = max(2, round(60 * 0.05))
    assert tuple(out[420, 150 - 30 - ms // 2 - 1]) == render.PHOTO_FRAME       # the mat
    # nothing up and to the right of the spot, where an old photo goes
    assert not _magenta(out[:300, 300:]).any()
    # the leader: one straight line in the edge colour from the spot toward the box
    edge = np.all(out == render.PHOTO_EDGE, axis=2)
    for t in (0.2, 0.5, 0.7):
        x, y = round(300 + t * (150 - 300)), round(300 + t * (420 - 300))
        assert edge[y - 1:y + 2, x - 1:x + 2].any(), t

GOLDEN_OLD_PHOTOS = {                 # _draw_photos, _paint_overlays on main's code path
    "mat": ("e2f809387d0db41b1b9a58dc971578c4aeefd01ee0047f7c73aa53a472986989",
            "a4655cb6e70bf11a319f98036ef4177fb6137f21be24065f81289fc5954ee072"),
    "keyline": ("383e66738dd6d74a429f68ecce4bc85d096571add3757cac7bb8b4c4f15c57f0",
                "79f7f8c6e24b9f39a55154d44e6688620a5d7edcd97fe3da8658459236c58592"),
    "borderless": ("57b58cba5675336f35c1f4ded4e669c371031327bc7ef387bb9b1d1cb3293d01",
                   "8d1af936d152f52474baaf42722408635093b17ed68fa80b403aefc02e3fe538"),
    "polaroid": ("1664d913e55410f4baf0f2da61626fea2da04b47a0bd918c196bb9d566324de1",
                 "311d0fe816fcdadeeee7a36ce7725a63f4bef4efdb3ee315b66bbc69609068f4"),
}

def test_old_hotspots_without_box_render_as_before(tmp_path):
    # invariant 7: a hotspot with no box and no crop is placed and fitted as it always
    # was. The hashes are main's pixels before order photos (no text is drawn, so no
    # font reaches them).
    p = str(tmp_path / "p.png")
    _pattern(p)
    hs = [{"x": 500, "y": 500, "weight": 3, "photo": p},
          {"x": 900, "y": 150, "weight": 1, "photo": p},
          {"x": 80, "y": 950, "weight": 1, "photo": p}]
    w = h = 600
    for style, (photos_hash, overlays_hash) in GOLDEN_OLD_PHOTOS.items():
        spec = _spec(hs, photo_box_in=2.0, photo_frame_style=style, title_text="",
                     compass=False, keyline=False)
        img = render._draw_photos(_blank(w, h), spec, w, h, 60)
        ov = render._paint_overlays(_blank(w, h), spec, np.zeros((h, w)), w, h, 60)
        assert hashlib.sha256(np.asarray(img).tobytes()).hexdigest() == photos_hash, style
        assert hashlib.sha256(np.asarray(ov).tobytes()).hexdigest() == overlays_hash, style

def test_crop_focus_moves_the_window(tmp_path):
    w = h = 600
    p = _halves(tmp_path)

    def colours(crop):
        hs = {"x": 500, "y": 500, "weight": 3, "photo": p, "box": {"dx_in": 0, "dy_in": -2.0}}
        if crop is not None:
            hs["crop"] = crop
        spec = _spec([hs], photo_box_in=1.5)
        out = np.asarray(render._draw_photos(_blank(w, h), spec, w, h, dpi=60).convert("RGB"))
        red = ((out[..., 0] > 200) & (out[..., 1] < 60) & (out[..., 2] < 60)).sum()
        blue = ((out[..., 0] < 60) & (out[..., 1] < 60) & (out[..., 2] > 200)).sum()
        return red, blue

    side = 90 * 90                                      # a 1.5 in square at 60 dpi
    red, blue = colours({"cx": 0.0, "cy": 0.5})
    assert red == side and blue == 0                    # the window at the left edge
    red, blue = colours({"cx": 1.0, "cy": 0.5})
    assert blue == side and red == 0                    # at the right edge
    red, blue = colours(None)                           # absent: the centre, half each
    assert abs(red - blue) <= 90 and red + blue == side

def test_a_bad_box_or_crop_is_tolerated_at_render_time(tmp_path):
    # a live session is not bounded at the manifest door: a box or crop that is not a
    # dict of finite numbers is absent, a crop is clamped to 0..1, and nothing raises
    w = h = 600
    p = _halves(tmp_path)

    def render_one(**keys):
        spec = _spec([dict({"x": 500, "y": 500, "weight": 3, "photo": p}, **keys)],
                     photo_box_in=1.5)
        return np.asarray(render._draw_photos(_blank(w, h), spec, w, h, dpi=60))

    bad = render_one(box={"dx_in": math.nan, "dy_in": 1.0}, crop={"cx": 5, "cy": 0.5})
    good = render_one(crop={"cx": 1.0, "cy": 0.5})       # no box: today's placement
    assert np.array_equal(bad, good)
    for box in ("left", [1, 2], {"dx_in": math.inf, "dy_in": 0}, {"dx_in": True, "dy_in": 0},
                {"dx_in": 10 ** 400, "dy_in": 0}, {"dx_in": 1.0}, {"dx_in": 1e300, "dy_in": -1e300}):
        render_one(box=box, crop={"cx": -3, "cy": math.nan})
    assert np.array_equal(render_one(box={"dx_in": 1e300, "dy_in": 0}).shape, (h, w, 4))
