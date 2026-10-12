# tests/test_previewpdf.py
# The preview PDF, from flat test images: no plate, no renderer, no network.
import os
import re
import time

import numpy as np
import pytest
from PIL import Image, ImageDraw, PdfParser

from app import previewpdf as pdf
from app.order import OrderError

NAMES = {"11x17": {"name": "11 × 17 in", "price": "$69"},
         "17x22": {"name": "17 × 22 in", "price": "$99"},
         "two": {"name": "Two panels", "price": "Price on request"},
         "three": {"name": "Three panels", "price": "Price on request"}}
LONG_NAMES = {"11x17": {"name": "The small sheet, for a hallway or a desk", "price": "$69"},
              "17x22": {"name": "The large sheet, for a living room wall", "price": "$99"},
              "two": {"name": "Two panels side by side", "price": "Price on request"},
              "three": {"name": "Three panels, the whole route across one long wall",
                        "price": "Price on request, and it depends on the frames you choose"}}
PAGE = (3300, 2550)                 # 11 x 8.5 in at 300 dpi
# one flat colour for each size's test map, so a page can be searched for its pixels
COLOURS = {"11x17": (200, 30, 120), "17x22": (30, 120, 200), "two": (230, 160, 20),
           "three": (20, 160, 90)}


def _entry(tmp_path, key, panels, w, h, gap=0.0, offered=True):
    path = tmp_path / f"{key}.png"
    Image.new("RGB", (round(w * 20), round(h * 20)), COLOURS[key]).save(path)
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
    # 300 dpi: at 150 the place names of a three-panel map were about 4 px tall
    assert pdf.PAGE_DPI == 300
    assert (pdf._px(pdf.PAGE_IN[0]), pdf._px(pdf.PAGE_IN[1])) == PAGE == (3300, 2550)
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


# ---- a size page ----

SIZE_PAGES = [("three", 3, 70, 17, 2.0), ("three", 3, 55, 22, 2.0), ("two", 2, 46, 17, 2.0),
              ("11x17", 1, 11, 17, 0.0), ("11x17", 1, 17, 11, 0.0), ("17x22", 1, 17, 22, 0.0),
              ("17x22", 1, 22, 17, 0.0)]


@pytest.mark.parametrize("names", [NAMES, LONG_NAMES], ids=["names", "long names"])
@pytest.mark.parametrize("key,panels,w,h,gap", SIZE_PAGES)
def test_a_size_page_holds_the_map_and_its_caption(tmp_path, key, panels, w, h, gap, names):
    e = _entry(tmp_path, key, panels, w, h, gap)
    box = pdf.content_box("Lassen walk", pdf.size_label(2, 5), False)
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
    box = pdf.content_box("Lassen walk", pdf.size_label(2, 5), False)
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
    assert all(font.getlength(c + "W") > pdf._px(3.0) for c in cut[:-1])   # each line is full
    # words after a cut word go on with its last piece
    assert pdf.wrap("W" * 60 + " i i", font, pdf._px(3.0))[-1].endswith("W i i")
    assert pdf.wrap("", font, pdf._px(3.0)) == [""]


def test_one_long_word_wraps_in_linear_time():
    # an unbroken 5,000-character string took over five minutes: each cut measured
    # every shorter prefix of all that was left. The bound is 10 s, not 1: the linear
    # wrap is 0.25 s on the Mac and was 1.2 s on the Linux CI runner, which failed a
    # bound of 1 s on the first push. The old wrap is still 30 times over it.
    font = pdf._font(pdf.MUTED_PT)
    for track in (0.0, 2.0):
        word = "Wi" * 2500
        started = time.process_time()                      # this process only: a busy machine does not fail it
        cut = pdf.wrap(word, font, pdf._px(3.0), track)
        assert time.process_time() - started < 10.0
        assert "".join(cut) == word and len(cut) > 20
        assert all(pdf._width(c, font, track) <= pdf._px(3.0) for c in cut)
        assert all(pdf._width(c + "W", font, track) > pdf._px(3.0) for c in cut[:-1])


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


def test_a_long_title_is_cut_at_a_word_so_every_page_names_its_order():
    # a title of 59 characters or more was left out of the footer, and a size page has
    # no other place for it
    font, width = pdf._font(pdf.MUTED_PT), pdf._px(pdf.PAGE_IN[0] - 2 * pdf.MARGIN_IN)
    title = "The long way round from Lassen Peak to the Pacific Crest and home again"
    assert len(title) >= 59
    foot = pdf.footer_lines(title, 2, 5)
    assert foot["page"].endswith("…  ·  2 of 5")
    kept = foot["page"][:-len("…  ·  2 of 5")]
    assert title.startswith(kept + " ") and len(kept) > 30      # whole words, and most of the room
    assert font.getlength(foot["page"]) <= pdf.FOOT_LABEL_SHARE * width
    assert font.getlength(f"{kept} {title[len(kept) + 1:].split()[0]}…  ·  2 of 5") \
        > pdf.FOOT_LABEL_SHARE * width                          # the next word would not fit
    assert len(foot["note"]) == 1                               # the footer stays one line
    # one word with no break is cut inside the word
    long = pdf.footer_lines("W" * 200, 2, 5)
    assert re.fullmatch(r"W{10,}…  ·  2 of 5", long["page"]) and len(long["note"]) == 1
    assert font.getlength(long["page"]) <= pdf.FOOT_LABEL_SHARE * width
    # a title that fits is whole, to the character
    assert pdf.shorten("Lassen walk", font, pdf._px(3.0)) == "Lassen walk"
    assert pdf.shorten("Lassen walk", font, font.getlength("Lassen walk")) == "Lassen walk"
    assert pdf.shorten("Lassen walk", font, font.getlength("Lassen walk") - 1) == "Lassen…"


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
    # an OrderError that names the file: the command prints it as one sentence
    with pytest.raises(OrderError, match=rf"cannot be written to {re.escape(str(out))}: disk full"):
        pdf.write(str(out), _entries(tmp_path), NAMES, "Lassen walk")
    assert out.read_bytes() == good                             # the last good preview stays
    assert sorted(p.name for p in out.parent.iterdir()) == ["lassen-preview.pdf"]
    fresh = tmp_path / "new" / "preview" / "x.pdf"
    with pytest.raises(OrderError, match="disk full"):
        pdf.write(str(fresh), _entries(tmp_path), NAMES, "Lassen walk")
    assert list(fresh.parent.iterdir()) == []


def test_a_failed_rename_leaves_no_temporary_file(tmp_path, monkeypatch):
    out = tmp_path / "out" / "preview" / "lassen-preview.pdf"

    def refuse(src, dst):
        raise PermissionError(13, "Permission denied", dst)
    monkeypatch.setattr(pdf.os, "replace", refuse)
    with pytest.raises(OrderError, match=rf"cannot be written to {re.escape(str(out))}: "
                                         rf".*Permission denied"):
        pdf.write(str(out), _entries(tmp_path), NAMES, "Lassen walk")
    assert list(out.parent.iterdir()) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to a read-only folder")
def test_a_read_only_folder_is_an_order_error_and_not_a_traceback(tmp_path):
    out = tmp_path / "order" / "out"
    out.mkdir(parents=True)
    target = out / "preview" / "lassen-preview.pdf"
    try:
        out.chmod(0o555)                                        # out/preview cannot be made
        with pytest.raises(OrderError, match=rf"The preview PDF cannot be written to "
                                             rf"{re.escape(str(target))}: .*Permission denied"):
            pdf.write(str(target), _entries(tmp_path), NAMES, "Lassen walk")
        assert list(out.iterdir()) == []
        out.chmod(0o755)
        target.parent.mkdir()
        target.parent.chmod(0o555)                              # the file cannot be made
        with pytest.raises(OrderError, match=rf"cannot be written to {re.escape(str(target))}"):
            pdf.write(str(target), _entries(tmp_path), NAMES, "Lassen walk")
        assert list(target.parent.iterdir()) == []
    finally:
        out.chmod(0o755)
        if target.parent.exists():
            target.parent.chmod(0o755)


# ---- what the file says of itself ----

def _saves(monkeypatch):
    """Every Image.save of a PDF, as its keywords. The real save still runs."""
    seen, real = [], Image.Image.save

    def save(self, fp, format=None, **kw):
        if format == "PDF":
            seen.append(dict(kw, fp=fp))
        return real(self, fp, format, **kw)
    monkeypatch.setattr(Image.Image, "save", save)
    return seen


def test_the_pdf_is_titled_by_its_order_and_not_by_its_temporary_file(tmp_path, monkeypatch):
    # Pillow takes the document title from the path: it was "lassen-preview.pdf.45500"
    seen = _saves(monkeypatch)
    out = tmp_path / "out" / "preview" / "lassen-preview.pdf"
    pdf.write(str(out), _entries(tmp_path), NAMES, "Lassen walk (2026)")
    data = out.read_bytes()
    title = "Lassen walk (2026): size preview"
    assert pdf.document_title("Lassen walk (2026)") == title
    with PdfParser.PdfParser(str(out)) as doc:
        assert doc.info.Title == title and doc.info.Author == "Tecopa Plateworks" == pdf.BRAND
    # the bytes: Pillow writes the text as UTF-16 with its mark
    assert b"/Title (" in data and b"/Author (" in data
    for name in (".tmp", str(os.getpid()), "lassen-preview"):
        assert name.encode() not in data and name.encode("utf-16-be") not in data
    assert "Lassen walk".encode("utf-16-be") in data
    assert seen[0]["title"] == title and seen[0]["author"] == pdf.BRAND


def test_the_pages_are_saved_at_the_page_dpi_and_a_quality_a_map_can_take(tmp_path, monkeypatch):
    seen = _saves(monkeypatch)
    pdf.write(str(tmp_path / "x.pdf"), _entries(tmp_path), NAMES, "Lassen walk")
    assert len(seen) == 1 and len(seen[0]["append_images"]) == 3
    assert seen[0]["quality"] >= 85 and seen[0]["quality"] == pdf.JPEG_QUALITY
    assert seen[0]["resolution"] == pdf.PAGE_DPI == 300
    assert seen[0]["subsampling"] == 0                          # no colour blur on a track


# ---- the drawing: each page's pixels are where its layout says ----

def _extent(img, colour):
    """(x, y, w, h) of the pixels of exactly this colour."""
    hit = (np.asarray(img) == colour).all(axis=2)
    ys, xs = np.nonzero(hit.any(axis=1))[0], np.nonzero(hit.any(axis=0))[0]
    assert len(xs), f"no pixel of {colour}"
    return (int(xs[0]), int(ys[0]), int(xs[-1] - xs[0] + 1), int(ys[-1] - ys[0] + 1))


def _ink(img, box) -> bool:
    """True when anything is drawn inside the (x, y, w, h) box."""
    x, y, w, h = (int(v) for v in box)
    assert w > 0 and h > 0
    return bool((np.asarray(img)[y:y + h, x:x + w] != pdf.PAPER).any())


def _line_boxes(caption, block) -> list:
    """The box of each line of a caption block placed at `caption`."""
    x, y, out = caption[0], caption[1], []
    for text, pt, _ in block["lines"]:
        out.append((text, (x, y, block["w"], pdf._pt(pdf.LEADING[pt]))))
        y += pdf._pt(pdf.LEADING[pt])
    return out


@pytest.mark.parametrize("wall", list(WALLS))
def test_each_map_of_the_wall_fills_its_box_to_the_pixel(tmp_path, wall):
    offered = _wall(tmp_path, WALLS[wall])
    img = pdf.wall_page(offered, NAMES, "Lassen walk", 1, 1 + len(offered))
    lay = pdf.wall_layout(offered, NAMES, pdf.content_box(
        "Lassen walk", pdf.WALL_LABEL, True, 1, 1 + len(offered)))
    for it in lay["items"]:
        assert _extent(img, COLOURS[it["key"]]) == tuple(it["thumb"]), it["key"]
        patch = np.asarray(img)[it["thumb"][1]:it["thumb"][1] + it["thumb"][3],
                                it["thumb"][0]:it["thumb"][0] + it["thumb"][2]]
        assert (patch == COLOURS[it["key"]]).all()               # all of the box, no hole


def test_the_sofa_line_is_84_inches_at_the_walls_scale(tmp_path):
    offered = _wall(tmp_path, WALLS["an east-west route, single sheets upright"])
    img = pdf.wall_page(offered, NAMES, "Lassen walk", 1, 5)
    box = pdf.content_box("Lassen walk", pdf.WALL_LABEL, True, 1, 5)
    lay = pdf.wall_layout(offered, NAMES, box)
    x0, y, x1 = lay["sofa"]
    assert x1 - x0 == round(pdf.SOFA_IN * lay["scale"])
    row = np.asarray(img)[y]
    assert (row[x0:x1] == pdf.INK).all()                        # one unbroken line, end to end
    assert (row[:x0] == pdf.PAPER).all() and (row[x1:] == pdf.PAPER).all()
    assert _ink(img, lay["sofa_label"])
    # the sofa is longer than the widest single sheet and shorter than the widest set
    widths = {it["key"]: it["thumb"][2] for it in lay["items"]}
    assert widths["17x22"] < x1 - x0 and widths["two"] < x1 - x0 < widths["three"] * 2


@pytest.mark.parametrize("page", ["the wall", "a size page"])
def test_every_line_of_a_caption_is_drawn_and_the_price_is_its_own_line(tmp_path, page):
    offered = _wall(tmp_path, WALLS["an east-west route, single sheets upright"])
    no_price = {k: dict(row, price="") for k, row in NAMES.items()}

    def drawn(names):
        """(page image, [(key, caption box, block)])"""
        if page == "the wall":
            lay = pdf.wall_layout(offered, names, pdf.content_box(
                "Lassen walk", pdf.WALL_LABEL, True, 1, 5))
            return (pdf.wall_page(offered, names, "Lassen walk", 1, 5),
                    [(it["key"], it["caption"], it["block"]) for it in lay["items"]])
        lay = pdf.size_layout(offered[3], names, pdf.content_box(
            "Lassen walk", pdf.size_label(5, 5), False, 5, 5))
        return (pdf.size_page(offered[3], names, "Lassen walk", 5, 5),
                [("three", lay["caption"], lay["block"])])
    img, captions = drawn(NAMES)
    for key, box, block in captions:
        entry = [e for e in offered if e["key"] == key][0]
        lines = _line_boxes(box, block)
        # the block holds the caption's lines, the price last and in the body ink
        assert [text for text, _ in lines] == pdf.caption(entry, NAMES)
        assert block["lines"][-1] == (NAMES[key]["price"], pdf.BODY_PT, pdf.INK)
        assert block["lines"][0][1:] == (pdf.BODY_PT, pdf.INK_STRONG)
        for text, line in lines:
            assert _ink(img, line), (key, text)
    # with no price to print, the same line of the same page is bare paper: the ink
    # found above is the price's own
    bare, captions = drawn(no_price)
    for key, box, block in captions:
        lines = _line_boxes(box, block)
        assert lines[-1][0] == "" and not _ink(bare, lines[-1][1]), key
        assert all(_ink(bare, line) for _, line in lines[:-1])


@pytest.mark.parametrize("key,panels,w,h,gap", SIZE_PAGES)
def test_the_map_of_a_size_page_fills_its_box_to_the_pixel(tmp_path, key, panels, w, h, gap):
    e = _entry(tmp_path, key, panels, w, h, gap)
    img = pdf.size_page(e, NAMES, "Lassen walk", 2, 5)
    lay = pdf.size_layout(e, NAMES, pdf.content_box("Lassen walk", pdf.size_label(2, 5), False, 2, 5))
    assert _extent(img, COLOURS[key]) == tuple(lay["map"])
    x, y, mw, mh = lay["map"]
    assert (np.asarray(img)[y:y + mh, x:x + mw] == COLOURS[key]).all()


def test_the_footer_is_drawn_on_every_page(tmp_path):
    offered = _wall(tmp_path, WALLS["an east-west route, single sheets upright"])
    pages = {1: pdf.wall_page(offered, NAMES, "Lassen walk", 1, 5),
             4: pdf.size_page(offered[2], NAMES, "Lassen walk", 4, 5)}
    for number, img in pages.items():
        foot = pdf.footer_lines("Lassen walk", number, 5)
        lay = pdf.footer_layout(foot)
        assert foot["page"] == f"Lassen walk  ·  {number} of 5"
        x, y, w, h = lay["rule"]
        assert (np.asarray(img)[y:y + h, x:x + w] == pdf.INK_STRONG).all()
        assert len(lay["note"]) == len(foot["note"]) == 1
        for line in lay["note"]:
            assert _ink(img, line)
        assert _ink(img, lay["page"])
        # the note is on the left, the page label on the right, and they do not meet
        between = (lay["note"][0][0] + lay["note"][0][2] + 2, lay["page"][1],
                   lay["page"][0] - lay["note"][0][0] - lay["note"][0][2] - 4, lay["page"][3])
        assert not _ink(img, between)
        bottom = lay["page"][1] + lay["page"][3]
        assert bottom <= pdf._px(pdf.PAGE_IN[1] - pdf.MARGIN_IN)


def test_the_two_rules_have_the_standards_two_weights(tmp_path):
    # print-documents.md: 0.75 pt under a section label, 1 pt over the footer. At
    # 150 dpi both were 2 px.
    assert pdf._rule(pdf.LABEL_RULE_PT) == 3 and pdf._rule(pdf.FOOT_RULE_PT) == 4
    e = _entry(tmp_path, "three", 3, 70, 17, 2.0)
    img = np.asarray(pdf.size_page(e, NAMES, "Lassen walk", 5, 5))
    head = pdf.header_layout("Lassen walk", pdf.size_label(5, 5), False)["rule"]
    foot = pdf.footer_layout(pdf.footer_lines("Lassen walk", 5, 5))["rule"]
    assert (head[3], foot[3]) == (3, 4)
    for x, y, w, h in (head, foot):
        assert (x, w) == (pdf._px(pdf.MARGIN_IN), pdf._px(pdf.PAGE_IN[0] - 2 * pdf.MARGIN_IN))
        assert (img[y:y + h, x:x + w] == pdf.INK_STRONG).all()
        column = img[:, x + w - 4]                               # the right end: no text there
        assert (column[y - 3:y] == pdf.PAPER).all() and (column[y + h:y + h + 3] == pdf.PAPER).all()


def _drawn(monkeypatch) -> list:
    """Every (position, string) a page draws, in order. The real text is still drawn."""
    calls, real = [], ImageDraw.ImageDraw.text

    def text(self, xy, text, *a, **kw):
        calls.append((tuple(xy), text))
        return real(self, xy, text, *a, **kw)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", text)
    return calls


def _strings(calls) -> list:
    """The drawn lines. Spaced capitals are drawn glyph by glyph, left to right on one
    line: those glyphs are joined into the line they make."""
    runs = []
    for (x, y), text in calls:
        if runs and runs[-1][0] == y and x > runs[-1][1] and len(text) == 1:
            runs[-1][1], runs[-1][2] = x, runs[-1][2] + text
        else:
            runs.append([y, x, text])
    return [text for _, _, text in runs]


def test_every_page_carries_the_products_name_in_full(tmp_path, monkeypatch):
    # invariant 14: Tecopa Plateworks in full, never bare Plateworks
    assert pdf.BRAND == "Tecopa Plateworks"
    offered = _wall(tmp_path, WALLS["an east-west route, single sheets upright"])
    calls = _drawn(monkeypatch)
    for make in (lambda: pdf.wall_page(offered, NAMES, "Lassen walk", 1, 5),
                 lambda: pdf.size_page(offered[3], NAMES, "Lassen walk", 5, 5)):
        calls.clear()
        make()
        lines = _strings(calls)
        named = [line for line in lines if "plateworks" in line.casefold()]
        assert [" ".join(line.split()).casefold() for line in named] == [pdf.BRAND.casefold()], lines
        assert named[0] == pdf.BRAND.upper()


def test_the_orders_title_heads_page_1_only(tmp_path, monkeypatch):
    offered = _wall(tmp_path, WALLS["an east-west route, single sheets upright"])
    calls = _drawn(monkeypatch)
    wall = pdf.wall_page(offered, NAMES, "Lassen walk", 1, 5)
    assert "Lassen walk" in _strings(calls)
    head = pdf.header_layout("Lassen walk", pdf.WALL_LABEL, True)
    title = [line for line in head["lines"] if line["part"] == "title"]
    assert len(title) == 1 and title[0]["text"] == "Lassen walk" and title[0]["pt"] == pdf.TITLE_PT
    assert _ink(wall, title[0]["box"])
    assert ((tuple(title[0]["box"][:2])), "Lassen walk") in calls
    # a size page: no title line in its header, and the header does not change with the
    # title. The footer names the order (its own test).
    calls.clear()
    one = pdf.size_page(offered[3], NAMES, "Lassen walk", 5, 5)
    assert "Lassen walk" not in _strings(calls)
    assert "Lassen walk  ·  5 of 5" in _strings(calls)
    later = pdf.header_layout("Lassen walk", pdf.size_label(5, 5), False)
    assert [line["part"] for line in later["lines"]] == ["brand", "label"]
    assert later["bottom"] < head["bottom"]
    other = pdf.size_page(offered[3], NAMES, "Another order", 5, 5)
    top = later["bottom"]
    assert (np.asarray(one)[:top] == np.asarray(other)[:top]).all()
    assert not (np.asarray(wall)[:head["bottom"]] == np.asarray(
        pdf.wall_page(offered, NAMES, "Another order", 1, 5))[:head["bottom"]]).all()


def test_the_label_of_a_size_page_is_its_place_in_the_menu(tmp_path, monkeypatch):
    # the label was the size's name in capitals, "11 × 17 IN": it upper-cased the unit
    # and said the caption's first line twice
    assert pdf.size_label(2, 5) == "Size 1 of 4" and pdf.size_label(5, 5) == "Size 4 of 4"
    assert pdf.size_label(2, 2) == "Size 1 of 1" and pdf.size_label() == "One size"
    e = _entry(tmp_path, "11x17", 1, 11, 17)
    calls = _drawn(monkeypatch)
    pdf.size_page(e, NAMES, "Lassen walk", 2, 5)
    lines = _strings(calls)
    assert "SIZE 1 OF 4" in lines
    assert lines.count("11 × 17 in") == 1 and "11 × 17 IN" not in lines   # the caption says it once
    assert "$69" in lines


def test_names_and_prices_at_their_limits_still_make_a_wall(tmp_path):
    # app/sizes.py holds a name to 40 characters and a price to 24: the worst wall
    # keeps its smallest sheet at least 0.75 in across on the page.
    #
    # That number is Georgia's, the face of the Mac that makes the preview. No font is
    # in the repo, so the Linux CI draws with DejaVu Serif, which is wider: one name
    # of 40 characters takes a third line, and the smallest sheet is 0.49 in (146 px).
    # Every wall is still made. So the floor follows the face: 0.75 in with Georgia,
    # and 0.45 in with any other face, measured with DejaVu Serif.
    from app import sizes
    names = {"11x17": {"name": "The small sheet, for a hallway or a desk", "price": "$1,250 framed, $950 bare"},
             "17x22": {"name": "The large sheet for a living room wall..", "price": "$1,250 framed, $950 bare"},
             "two": {"name": "Two panels side by side over a long sofa", "price": "Price on request, framed"},
             "three": {"name": "Three panels, the whole route on one wall", "price": "Price on request, framed"}}
    names["three"]["name"] = names["three"]["name"][:40]
    assert {len(r["name"]) for r in names.values()} == {sizes.NAME_MAX_CHARS}
    assert {len(r["price"]) for r in names.values()} == {sizes.PRICE_MAX_CHARS}
    face = pdf._font(pdf.MUTED_PT).getname()[0]
    floor_in = 0.75 if face == "Georgia" else 0.45
    for wall in WALLS:
        offered = _wall(tmp_path, WALLS[wall])
        lay = pdf.wall_layout(offered, names, pdf.content_box("Lassen walk", pdf.WALL_LABEL, True, 1, 5))
        assert min(it["thumb"][2] for it in lay["items"]) >= pdf._px(floor_in), (wall, face)
        _margins_are_clean(pdf.wall_page(offered, names, "Lassen walk", 1, 5))
