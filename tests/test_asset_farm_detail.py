# The 1:1 detail crop is the landing page's "actual print pixels" proof, so it has to
# land on ink -- the copy beside it promises labels standing clear of the routes. Demo
# journeys route over real OSM ways and are spread across the whole plate on purpose,
# which makes the plate's CENTRE typically its emptiest part. So the crop is chosen by
# ink content, and falls back to the centre only for a poster that carries no ink at all.
import numpy as np
from PIL import Image

from app.render import TRACK_INK
from scripts.render_asset_farm import _detail

GROUND = (118, 110, 98)          # terrain-ish, nowhere near the gold
CW, CH = 1400, 1050              # the crop the farm cuts


def _poster(tmp_path, size, ink_boxes=()):
    """A synthetic poster: flat ground with rectangles of route ink where asked."""
    img = Image.new("RGB", size, GROUND)
    for box in ink_boxes:
        img.paste(TRACK_INK, box)
    img.save(str(tmp_path / "poster.png"), "PNG")
    return img


def _ink_pixels(img):
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    return int((np.abs(a - np.array(TRACK_INK, np.int16)).max(axis=2) <= 12).sum())


def test_detail_crop_lands_on_the_ink_not_the_empty_centre(tmp_path):
    # ink in the top-left quarter only; the centre crop (x 800-2200, y 575-1625) is bare
    _poster(tmp_path, (3000, 2200), [(120, 140, 320, 340)])
    made = _detail(str(tmp_path))
    assert made == [str(tmp_path / "detail.png")]
    crop = Image.open(made[0])
    assert crop.size == (CW, CH)
    assert _ink_pixels(crop) > 0


def test_detail_crop_falls_back_to_centre_when_a_poster_has_no_ink(tmp_path):
    img = _poster(tmp_path, (3000, 2200))
    _detail(str(tmp_path))
    w, h = img.size
    centre = img.crop(((w - CW) // 2, (h - CH) // 2,
                       (w - CW) // 2 + CW, (h - CH) // 2 + CH))
    assert np.array_equal(np.asarray(Image.open(str(tmp_path / "detail.png"))),
                          np.asarray(centre))


def test_detail_crop_stays_inside_the_sheet_when_the_ink_hugs_a_corner(tmp_path):
    w, h = 3000, 2200
    img = _poster(tmp_path, (w, h), [(w - 30, h - 30, w, h)])   # hard against the corner
    crop = Image.open(_detail(str(tmp_path))[0])
    assert crop.size == (CW, CH)
    assert _ink_pixels(crop) > 0
    # the crop is a real window of the poster, wholly inside it: prove by matching the
    # only in-bounds window that could hold the corner ink
    corner = img.crop((w - CW, h - CH, w, h))
    assert np.array_equal(np.asarray(crop), np.asarray(corner))


def test_detail_crop_of_a_small_poster_is_the_whole_sheet(tmp_path):
    img = _poster(tmp_path, (900, 700), [(10, 10, 40, 40)])
    crop = Image.open(_detail(str(tmp_path))[0])
    assert crop.size == img.size
