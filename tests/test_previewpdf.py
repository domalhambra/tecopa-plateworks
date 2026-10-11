# tests/test_previewpdf.py
# The preview PDF, from flat test images: no plate, no renderer, no network.
import re

import numpy as np
import pytest
from PIL import Image

from app import previewpdf as pdf

NAMES = {"11x17": {"name": "11 × 17 in", "price": "$69"},
         "17x22": {"name": "17 × 22 in", "price": "$99"},
         "two": {"name": "Two panels", "price": "Price on request"},
         "three": {"name": "Three panels", "price": "Price on request"}}
LONG_NAMES = {"11x17": {"name": "The small sheet, for a hallway or a desk", "price": "$69"},
              "17x22": {"name": "The large sheet, for a living room wall", "price": "$99"},
              "two": {"name": "Two panels side by side", "price": "Price on request"},
              "three": {"name": "Three panels, the whole route across one long wall",
                        "price": "Price on request, and it depends on the frames you choose"}}
PAGE = (round(11 * pdf.PAGE_DPI), round(8.5 * pdf.PAGE_DPI))


def _entry(tmp_path, key, panels, w, h, gap=0.0, offered=True):
    path = tmp_path / f"{key}.png"
    Image.new("RGB", (round(w * 20), round(h * 20)), (120, 140, 110)).save(path)
    return {"key": key, "panels": panels, "orientation": "landscape" if w > h else "portrait",
            "print_in": [float(w), float(h)], "gap": gap, "offered": offered,
            "image": str(path), "why": "" if offered else "the tracks span 15% of the sheet's width"}


def _entries(tmp_path):
    return [_entry(tmp_path, "11x17", 1, 11, 17), _entry(tmp_path, "17x22", 1, 17, 22),
            _entry(tmp_path, "two", 2, 46, 17, 2.0, offered=False),
            _entry(tmp_path, "three", 3, 70, 17, 2.0)]


# every wall a preview can make: (11x17, 17x22, two, three) as (width, height)
WALLS = {
    "an east-west route, single sheets upright": [(11, 17), (17, 22), (46, 17), (70, 17)],
    "an east-west route, single sheets on their side": [(17, 11), (22, 17), (46, 17), (70, 17)],
    "panels 17 in across": [(11, 17), (17, 22), (36, 22), (55, 22)],
    "the single sheets only": [(11, 17), (17, 22)],
    "one size": [(70, 17)],
    "the small sheet alone": [(11, 17)],
}


def _wall(tmp_path, sizes):
    keys = ("11x17", "17x22", "two", "three") if len(sizes) != 1 else (
        ("three",) if sizes[0][0] > 22 else ("11x17",))
    return [_entry(tmp_path, k, {"two": 2, "three": 3}.get(k, 1), w, h,
                   2.0 if k in ("two", "three") else 0.0)
            for k, (w, h) in zip(keys, sizes)]


def _cross(a, b):
    """True when two (x, y, w, h) boxes share any area."""
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _inside(box, frame):
    return (box[0] >= frame[0] and box[1] >= frame[1]
            and box[0] + box[2] <= frame[2] and box[1] + box[3] <= frame[3])


def _margins_are_clean(img):
    """Nothing is drawn in the page margins: a line of text that runs off the page, or
    a map that is too wide, puts ink there."""
    a = np.asarray(img)
    m = pdf._px(pdf.MARGIN_IN) - 1
    for strip in (a[:m], a[-m:], a[:, :m], a[:, -m:]):
        assert (strip == pdf.PAPER).all()


def test_the_caption_of_a_size():
    e = {"key": "three", "panels": 3, "print_in": [70.0, 17.0], "gap": 2.0}
    assert pdf.caption(e, NAMES) == ["Three panels",
                                     "3 panels of 17 × 22 in, 70 × 17 in hung, 2 in gaps",
                                     "Price on request"]
    # a sheet named by its own size does not say the size twice
    e = {"key": "11x17", "panels": 1, "print_in": [11.0, 17.0], "gap": 0.0}
    assert pdf.caption(e, NAMES) == ["11 × 17 in", "$69"]
    # on its side, the second line is how it hangs
    e = {"key": "11x17", "panels": 1, "print_in": [17.0, 11.0], "gap": 0.0}
    assert pdf.caption(e, NAMES) == ["11 × 17 in", "17 × 11 in", "$69"]
    assert pdf.caption(e, LONG_NAMES) == ["The small sheet, for a hallway or a desk",
                                          "17 × 11 in", "$69"]
    two = {"key": "two", "panels": 2, "print_in": [46.0, 17.0], "gap": 2.0}
    assert pdf.caption(two, NAMES)[1] == "2 panels of 17 × 22 in, 46 × 17 in hung, 2 in gap"


def test_sizes_are_packed_into_rows_of_wall():
    wide = [{"print_in": [11.0, 17.0]}, {"print_in": [17.0, 22.0]},
            {"print_in": [46.0, 17.0]}, {"print_in": [70.0, 17.0]}]
    rows = pdf.wall_rows(wide, 100.0)
    assert [[e["print_in"][0] for e in row] for row in rows] == [[11.0, 17.0, 46.0], [70.0]]


def test_the_page_follows_the_print_standard():
    # 00 Resources/print-documents.md, section 2: black text on white paper, the canon
    # inks, 0.5 in margins on a Letter piece, and the product's name in full
    assert pdf.PAGE_IN == (11.0, 8.5) and pdf.MARGIN_IN == 0.5
    assert pdf.PAPER == (255, 255, 255)
    assert pdf.INK == (0x1B, 0x1E, 0x26) and pdf.INK_STRONG == (0x02, 0x03, 0x06)
    assert pdf.MUTED == (0x56, 0x5B, 0x67)
    assert (pdf.TITLE_PT, pdf.BODY_PT, pdf.LABEL_PT, pdf.MUTED_PT) == (22, 11, 9, 8)
    assert pdf.BRAND == "Tecopa Plateworks"
    assert "—" not in pdf.NOTE


def test_every_page_is_letter_landscape(tmp_path):
    offered = [e for e in _entries(tmp_path) if e["offered"]]
    wall = pdf.wall_page(offered, NAMES, "Lassen walk")
    one = pdf.size_page(offered[2], NAMES, "Lassen walk")
    assert wall.size == one.size == PAGE
    assert wall.getcolors(maxcolors=1 << 20) and len(wall.getcolors(maxcolors=1 << 20)) > 4


def test_the_pdf_has_a_wall_page_and_a_page_for_each_offered_size(tmp_path):
    out = tmp_path / "out" / "preview" / "lassen-preview.pdf"
    pages = pdf.write(str(out), _entries(tmp_path), NAMES, "Lassen walk")
    assert pages == 4                                         # the wall, then three sizes
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(re.findall(rb"/Type\s*/Page\b(?!s)", data)) == 4
    boxes = re.findall(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", data)
    assert len(boxes) == 4
    for box in boxes:                                         # 11 x 8.5 in, in points
        assert [float(v) for v in box] == pytest.approx([0, 0, 792, 612], abs=0.5)
    assert sorted(p.name for p in out.parent.iterdir()) == ["lassen-preview.pdf"]
    # the file goes to a client: it has the mode of any file made here, not the
    # owner-only mode of a temporary file
    plain = out.parent / "plain.txt"
    plain.write_text("x")
    assert out.stat().st_mode == plain.stat().st_mode


# ---- the wall page: one scale, nothing off the page, no caption on another ----

@pytest.mark.parametrize("names", [NAMES, LONG_NAMES], ids=["names", "long names"])
@pytest.mark.parametrize("wall", list(WALLS))
def test_the_wall_holds_every_size_at_one_scale(tmp_path, wall, names):
    offered = _wall(tmp_path, WALLS[wall])
    box = pdf.content_box("Lassen walk", pdf.WALL_LABEL, True)
    lay = pdf.wall_layout(offered, names, box)
    assert [it["key"] for it in lay["items"]] == [e["key"] for e in offered]
    boxes = []
    for it, e in zip(lay["items"], offered):
        x, y, w, h = it["thumb"]
        # one scale for every size, to the pixel
        assert w == round(e["print_in"][0] * lay["scale"])
        assert h == round(e["print_in"][1] * lay["scale"])
        assert _inside(it["thumb"], box), (wall, it)
        assert _inside(it["caption"], box), (wall, it)
        assert not _cross(it["thumb"], it["caption"])
        boxes += [it["thumb"], it["caption"]]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert not _cross(a, b), (wall, a, b)
    # the sofa is 84 in at the same scale, on the page, with its label
    x0, y, x1 = lay["sofa"]
    assert x1 - x0 == round(pdf.SOFA_IN * lay["scale"])
    assert box[0] <= x0 and x1 <= box[2]
    assert _inside(lay["sofa_label"], box)
    for b in boxes:
        assert b[1] + b[3] <= y - pdf._px(0.05)               # the sofa line is below every size
    assert lay["sofa_label"][1] > y


def test_a_caption_wider_than_its_sheet_pushes_the_next_size_along(tmp_path):
    offered = _wall(tmp_path, WALLS["an east-west route, single sheets upright"])
    box = pdf.content_box("Lassen walk", pdf.WALL_LABEL, True)
    lay = pdf.wall_layout(offered, LONG_NAMES, box)
    small, large = lay["items"][0], lay["items"][1]
    assert small["caption"][2] > small["thumb"][2]            # the caption is the wider one
    assert small["row"] == large["row"] == 0
    assert large["thumb"][0] >= small["caption"][0] + small["caption"][2] + pdf._px(pdf.MIN_GAP_IN)


def test_the_wall_uses_the_page(tmp_path):
    # the worst wall: four sizes, with the sets in landscape. The prints must stay
    # large enough to compare: the small sheet at least an inch across on the page.
    for wall in ("an east-west route, single sheets upright",
                 "an east-west route, single sheets on their side"):
        offered = _wall(tmp_path, WALLS[wall])
        box = pdf.content_box("Lassen walk", pdf.WALL_LABEL, True)
        lay = pdf.wall_layout(offered, NAMES, box)
        assert min(it["thumb"][2] for it in lay["items"]) >= pdf._px(1.0), wall
        assert [it["row"] for it in lay["items"]] == [0, 0, 0, 1]   # the long set has its own row


@pytest.mark.parametrize("names", [NAMES, LONG_NAMES], ids=["names", "long names"])
@pytest.mark.parametrize("wall", list(WALLS))
def test_the_wall_page_keeps_its_margins_clean(tmp_path, wall, names):
    title = "Lassen walk" if names is NAMES else "W" * 200      # the longest title a spec holds
    img = pdf.wall_page(_wall(tmp_path, WALLS[wall]), names, title)
    assert img.size == PAGE
    _margins_are_clean(img)


def test_the_wall_page_draws_the_layout(tmp_path):
    offered = _wall(tmp_path, WALLS["an east-west route, single sheets upright"])
    img = np.asarray(pdf.wall_page(offered, NAMES, "Lassen walk"))
    lay = pdf.wall_layout(offered, NAMES, pdf.content_box("Lassen walk", pdf.WALL_LABEL, True))
    for it in lay["items"]:
        x, y, w, h = it["thumb"]
        assert (img[y + h // 2, x + w // 2] == (120, 140, 110)).all()
    x0, y, x1 = lay["sofa"]
    assert tuple(img[y, (x0 + x1) // 2]) != pdf.PAPER


# ---- a size page ----

SIZE_PAGES = [("three", 3, 70, 17, 2.0), ("three", 3, 55, 22, 2.0), ("two", 2, 46, 17, 2.0),
              ("11x17", 1, 11, 17, 0.0), ("11x17", 1, 17, 11, 0.0), ("17x22", 1, 17, 22, 0.0),
              ("17x22", 1, 22, 17, 0.0)]


@pytest.mark.parametrize("names", [NAMES, LONG_NAMES], ids=["names", "long names"])
@pytest.mark.parametrize("key,panels,w,h,gap", SIZE_PAGES)
def test_a_size_page_holds_the_map_and_its_caption(tmp_path, key, panels, w, h, gap, names):
    e = _entry(tmp_path, key, panels, w, h, gap)
    box = pdf.content_box("Lassen walk", names[key]["name"], False)
    lay = pdf.size_layout(e, names, box)
    assert _inside(lay["map"], box) and _inside(lay["caption"], box)
    assert not _cross(lay["map"], lay["caption"])
    x, y, mw, mh = lay["map"]
    assert mw / mh == pytest.approx(w / h, rel=0.01)           # the map keeps its shape
    # the map takes most of the page, one way or the other
    assert mw >= 0.9 * (box[2] - box[0]) - lay["caption"][2] or mh >= 0.9 * (box[3] - box[1])
    img = pdf.size_page(e, names, "Lassen walk" if names is NAMES else "W" * 200, 2, 5)
    assert img.size == PAGE
    _margins_are_clean(img)


def test_a_size_page_never_enlarges_past_what_the_page_can_hold(tmp_path):
    e = _entry(tmp_path, "11x17", 1, 11, 17)
    box = pdf.content_box("Lassen walk", "11 × 17 in", False)
    lay = pdf.size_layout(e, NAMES, box)
    assert lay["map"][3] <= box[3] - box[1]
    # a tall map: the caption sits beside it, so the map gets the full height
    assert lay["caption"][0] >= lay["map"][0] + lay["map"][2]
    wide = pdf.size_layout(_entry(tmp_path, "three", 3, 70, 17, 2.0), NAMES, box)
    assert wide["caption"][1] >= wide["map"][1] + wide["map"][3]   # a wide map: below it


# ---- the words ----

def test_a_long_line_wraps_inside_its_width():
    font = pdf._font(pdf.MUTED_PT)
    lines = pdf.wrap(pdf.NOTE, font, pdf._px(3.0))
    assert len(lines) > 1 and " ".join(lines) == pdf.NOTE
    assert all(font.getlength(line) <= pdf._px(3.0) for line in lines)
    assert pdf.wrap(pdf.NOTE, font, pdf._px(40.0)) == [pdf.NOTE]
    # one word wider than the width is cut, never left to run off the page
    cut = pdf.wrap("W" * 200, font, pdf._px(3.0))
    assert "".join(cut) == "W" * 200 and all(font.getlength(c) <= pdf._px(3.0) for c in cut)


def test_the_note_and_the_page_number_are_on_every_page(tmp_path):
    # the footer's height is the same with one line or two, so its text is read back
    # from the layout, not from the pixels
    foot = pdf.footer_lines("Lassen walk", 2, 5)
    assert " ".join(foot["note"]) == pdf.NOTE
    assert foot["page"] == "Lassen walk  ·  2 of 5"
    width = pdf._px(pdf.PAGE_IN[0] - 2 * pdf.MARGIN_IN)
    font = pdf._font(pdf.MUTED_PT)
    for line in foot["note"]:
        assert font.getlength(line) + pdf._px(0.3) + font.getlength(foot["page"]) <= width
    long = pdf.footer_lines("W" * 200, 2, 5)
    assert long["page"] == "2 of 5"                             # a long title leaves the footer


# ---- the file ----

def test_a_failed_write_leaves_no_half_file(tmp_path, monkeypatch):
    out = tmp_path / "out" / "preview" / "lassen-preview.pdf"
    pdf.write(str(out), _entries(tmp_path), NAMES, "Lassen walk")
    good = out.read_bytes()
    real = Image.Image.save

    def half(self, fp, format=None, **kw):
        if format == "PDF":
            with open(fp, "wb") as f:
                f.write(b"%PDF-1.4 half a file")
            raise OSError("disk full")
        return real(self, fp, format, **kw)
    monkeypatch.setattr(Image.Image, "save", half)
    with pytest.raises(OSError, match="disk full"):
        pdf.write(str(out), _entries(tmp_path), NAMES, "Lassen walk")
    assert out.read_bytes() == good                             # the last good preview stays
    assert sorted(p.name for p in out.parent.iterdir()) == ["lassen-preview.pdf"]
    fresh = tmp_path / "new" / "preview" / "x.pdf"
    with pytest.raises(OSError, match="disk full"):
        pdf.write(str(fresh), _entries(tmp_path), NAMES, "Lassen walk")
    assert list(fresh.parent.iterdir()) == []
