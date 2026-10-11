# app/previewpdf.py
"""The preview PDF of an order: one wall page, then one page for each offered size.

Pillow writes it, so there is no new dependency and no link in the file. The client
answers with a choice. Names and prices come from config/sizes.toml.

The look is the workspace's print standard (00 Resources/print-documents.md, section
2): black text on white paper, the canon inks, 0.5 in margins on a Letter piece, the
standard's type sizes, a rule under the section label and a rule over the footer. The
standard's faces are licensed and this repo is public (invariant 10), so the type is
the engine's own font chain: the operator's TECOPA_FONT bindings, else Georgia or
DejaVu. Colour is in the maps only.

Each page is laid out first, as boxes, and drawn second. The tests read the boxes:
nothing leaves the margins, no caption sits on another, every size is at one scale."""
import os

from PIL import Image, ImageDraw

PAGE_IN = (11.0, 8.5)        # US Letter, landscape
PAGE_DPI = 150
MARGIN_IN = 0.5              # print-documents.md: a Letter piece
PAPER = (255, 255, 255)      # black text on white paper
INK = (0x1B, 0x1E, 0x26)     # body, canon --text
INK_STRONG = (0x02, 0x03, 0x06)   # title and labels, canon --text-strong
MUTED = (0x56, 0x5B, 0x67)   # captions and the footer, canon --text-muted
TITLE_PT = 22                # page 1 only
BODY_PT = 11
LABEL_PT = 9                 # a section label: capitals, spaced 8 percent
MUTED_PT = 8
LABEL_TRACK = 0.08
LABEL_RULE_PT = 0.75         # the rule under a section label
FOOT_RULE_PT = 1.0           # the rule over the footer
LEADING = {TITLE_PT: 27, BODY_PT: 16, LABEL_PT: 13, MUTED_PT: 12}   # points, line to line

ROW_IN = 100.0               # a row of wall holds this many real inches
SPACING_IN = 8.0             # between two sizes on the wall
SOFA_IN = 84.0               # a 7 ft sofa, for scale
MIN_GAP_IN = 0.25            # on the page: the least space between two sizes' captions
CAPTION_GAP_IN = 0.08        # between a map and its caption
ROW_GAP_IN = 0.22            # between two rows of wall
WALL_CAPTION_IN = 3.2        # a caption on the wall wraps at this width
SIDE_CAPTION_IN = 2.6        # a caption beside a tall map wraps at this width
BRAND = "Tecopa Plateworks"
WALL_LABEL = "Every size on one wall, at one scale"
SOFA_LABEL = "A 7 ft sofa, for scale"
NOTE = ("This is a preview. The final map is drawn from finer terrain data, "
        "and a place name can sit in another position.")


def _px(inches) -> int:
    return round(inches * PAGE_DPI)


def _pt(points) -> int:
    return round(points * PAGE_DPI / 72.0)


def _font(pt, role="body"):
    from app import render       # the engine's own font chain; no font is in the repo
    return render._font(max(8, _pt(pt)), role)


def _width(text, font, track=0.0) -> float:
    """The drawn width of one line. Spaced text is drawn glyph by glyph."""
    if not track:
        return font.getlength(text)
    return sum(font.getlength(ch) for ch in text) + track * max(0, len(text) - 1)


def wrap(text, font, width, track=0.0) -> list:
    """`text` as lines no wider than `width` px. A word wider than the width is cut,
    so nothing runs off the page."""
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}" if line else word
        if _width(trial, font, track) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        line = word
        while _width(line, font, track) > width and len(line) > 1:
            n = len(line) - 1
            while n > 1 and _width(line[:n], font, track) > width:
                n -= 1
            lines.append(line[:n])
            line = line[n:]
    if line:
        lines.append(line)
    return lines or [""]


def _draw(d, x, y, text, font, fill, track=0.0) -> None:
    if not track:
        d.text((x, y), text, fill=fill, font=font)
        return
    for ch in text:
        d.text((x, y), ch, fill=fill, font=font)
        x += font.getlength(ch) + track


def _hung(entry) -> str:
    return f"{entry['print_in'][0]:g} × {entry['print_in'][1]:g} in"


def caption(entry, names) -> list:
    """The lines under a size: its name, what hangs, its price. A single sheet named
    by its own size ("11 × 17 in") does not say the size twice."""
    row = names[entry["key"]]
    what = _hung(entry)
    if entry["panels"] > 1:
        what = (f"{entry['panels']} panels of 17 × 22 in, {what} hung, "
                f"{entry['gap']:g} in {'gaps' if entry['panels'] > 2 else 'gap'}")
    return [row["name"]] + ([what] if what != row["name"] else []) + [row["price"]]


def _caption_block(entry, names, max_w) -> dict:
    """The caption as wrapped lines with their sizes and inks, and the block's box:
    the name in the strong ink, the price in the body ink, the rest muted."""
    texts = caption(entry, names)
    styles = [(BODY_PT, INK_STRONG)] + [(MUTED_PT, MUTED)] * (len(texts) - 2) + [(BODY_PT, INK)]
    lines, w, h = [], 0, 0
    for text, (pt, fill) in zip(texts, styles):
        font = _font(pt)
        for part in wrap(text, font, max_w):
            lines.append((part, pt, fill))
            w = max(w, font.getlength(part))
            h += _pt(LEADING[pt])
    return {"lines": lines, "w": int(w) + 1, "h": h}


def _draw_caption(d, x, y, block) -> None:
    for text, pt, fill in block["lines"]:
        d.text((x, y), text, fill=fill, font=_font(pt))
        y += _pt(LEADING[pt])


def wall_rows(offered, row_in=ROW_IN) -> list:
    """Pack the sizes left to right into rows of wall, in menu order."""
    rows, row, used = [], [], 0.0
    for e in offered:
        w = e["print_in"][0]
        if row and used + SPACING_IN + w > row_in:
            rows.append(row)
            row, used = [], 0.0
        used += (SPACING_IN if row else 0.0) + w
        row.append(e)
    if row:
        rows.append(row)
    return rows


# ---- the page: its header, its footer and the box between them ----

def _content_width() -> int:
    return _px(PAGE_IN[0]) - 2 * _px(MARGIN_IN)


def _header(d, title, label, first) -> int:
    """Draw the header (or only measure it, with d=None) and return the y where the
    page's content starts. Page 1: the product's name, the order's title, the section
    label and its rule. A later page has no title (print-documents.md: page 1 only)."""
    x, y, width = _px(MARGIN_IN), _px(MARGIN_IN), _content_width()

    def block(text, pt, fill, role="body", track=0.0):
        nonlocal y
        font = _font(pt, role)
        gap = track * _pt(pt)
        for line in wrap(text, font, width, gap):
            if d is not None:
                _draw(d, x, y, line, font, fill, gap)
            y += _pt(LEADING[pt])

    block(BRAND.upper(), LABEL_PT, INK_STRONG, track=LABEL_TRACK)
    if first:
        y += _px(0.06)
        block(title, TITLE_PT, INK_STRONG, role="title")
    y += _px(0.10)
    block(label.upper(), LABEL_PT, INK_STRONG, track=LABEL_TRACK)
    y += _px(0.03)
    rule = max(1, _pt(LABEL_RULE_PT))
    if d is not None:
        d.rectangle([x, y, x + width - 1, y + rule - 1], fill=INK_STRONG)
    return y + rule + _px(0.18)


def footer_lines(title, page=None, pages=None) -> dict:
    """The footer's words: the note, wrapped to the left of the page label. The label
    is the standard's "title · page"; a title too long for it leaves the number."""
    font, width = _font(MUTED_PT), _content_width()
    label = ""
    if page is not None:
        number = f"{page} of {pages}" if pages else f"{page}"
        label = f"{title}  ·  {number}"
        if font.getlength(label) > 0.35 * width:
            label = number
    room = width - (font.getlength(label) + _px(0.3) if label else 0)
    return {"note": wrap(NOTE, font, room), "page": label}


def _footer_height(foot) -> int:
    return (max(1, _pt(FOOT_RULE_PT)) + _px(0.06)
            + _pt(LEADING[MUTED_PT]) * max(1, len(foot["note"])))


def _footer(d, foot) -> None:
    font, x, width = _font(MUTED_PT), _px(MARGIN_IN), _content_width()
    y = _px(PAGE_IN[1]) - _px(MARGIN_IN) - _footer_height(foot)
    rule = max(1, _pt(FOOT_RULE_PT))
    d.rectangle([x, y, x + width - 1, y + rule - 1], fill=INK_STRONG)
    y += rule + _px(0.06)
    if foot["page"]:
        d.text((x + width - font.getlength(foot["page"]), y), foot["page"], fill=MUTED, font=font)
    for line in foot["note"]:
        d.text((x, y), line, fill=MUTED, font=font)
        y += _pt(LEADING[MUTED_PT])


def content_box(title, label, first, page=None, pages=None) -> tuple:
    """(x0, y0, x1, y1) in px: the part of the page between the header and the footer."""
    m = _px(MARGIN_IN)
    foot = footer_lines(title, page, pages)
    return (m, _header(None, title, label, first), m + _content_width(),
            _px(PAGE_IN[1]) - m - _footer_height(foot) - _px(0.12))


def _page(title, label, first, page=None, pages=None):
    img = Image.new("RGB", (_px(PAGE_IN[0]), _px(PAGE_IN[1])), PAPER)
    d = ImageDraw.Draw(img)
    _header(d, title, label, first)
    _footer(d, footer_lines(title, page, pages))
    return img, d, content_box(title, label, first, page, pages)


# ---- the wall page ----

def _place_wall(rows, blocks, scale, box):
    """The boxes of a wall at `scale` px for each real inch, or None when a row or the
    whole wall does not fit `box`. A size's cell is as wide as the wider of its map
    and its caption, so no caption reaches the next size."""
    x0, y0, x1, y1 = box
    gap = max(round(SPACING_IN * scale), _px(MIN_GAP_IN))
    items, y = [], y0
    for r, row in enumerate(rows):
        row_h = max(round(e["print_in"][1] * scale) for e in row)
        cap_y = y + row_h + _px(CAPTION_GAP_IN)
        x = x0
        for e in row:
            w, h = round(e["print_in"][0] * scale), round(e["print_in"][1] * scale)
            if w < 1 or h < 1:
                return None
            block = blocks[e["key"]]
            items.append({"key": e["key"], "row": r, "block": block,
                          "thumb": (x, y + (row_h - h) // 2, w, h),
                          "caption": (x, cap_y, block["w"], block["h"])})
            x += max(w, block["w"]) + gap
        if x - gap > x1:
            return None
        y = cap_y + max(blocks[e["key"]]["h"] for e in row) + _px(ROW_GAP_IN)
    tick = _px(0.06)
    line_y = y + tick
    sofa = round(SOFA_IN * scale)
    label = _font(MUTED_PT)
    label_box = (x0, line_y + tick + _px(0.05), int(label.getlength(SOFA_LABEL)) + 1,
                 _pt(LEADING[MUTED_PT]))
    if x0 + sofa > x1 or label_box[1] + label_box[3] > y1:
        return None
    return {"scale": scale, "items": items, "sofa": (x0, line_y, x0 + sofa),
            "sofa_label": label_box, "rows": len(rows)}


def wall_layout(offered, names, box) -> dict:
    """Every offered size on one wall at one scale, as large as the page allows, with
    a 7 ft sofa for scale. The sizes stay in menu order; the rows are the packing
    that gives the largest prints."""
    blocks = {e["key"]: _caption_block(e, names, min(_px(WALL_CAPTION_IN), box[2] - box[0]))
              for e in offered}
    widths = [e["print_in"][0] for e in offered]
    runs = sorted({sum(widths[i:j]) + SPACING_IN * (j - i - 1)
                   for i in range(len(widths)) for j in range(i + 1, len(widths) + 1)})
    best, seen = None, set()
    for run in runs:
        rows = wall_rows(offered, run)
        shape = tuple(len(r) for r in rows)
        if shape in seen:
            continue
        seen.add(shape)
        lo, hi, fit = 0.0, float(box[2] - box[0]), None
        for _ in range(40):                    # the largest scale that fits, by halving
            mid = (lo + hi) / 2
            placed = _place_wall(rows, blocks, mid, box)
            if placed:
                lo, fit = mid, placed
            else:
                hi = mid
        if fit and (best is None or fit["scale"] > best["scale"] * 1.001):
            best = fit
    if best is None:
        raise ValueError("the wall page cannot hold these sizes and their captions")
    return best


def wall_page(offered, names, title, page=None, pages=None):
    """Every offered size on one wall at one scale, with a sofa for scale."""
    img, d, box = _page(title, WALL_LABEL, True, page, pages)
    lay = wall_layout(offered, names, box)
    by_key = {e["key"]: e for e in offered}
    for it in lay["items"]:
        x, y, w, h = it["thumb"]
        thumb = Image.open(by_key[it["key"]]["image"]).convert("RGB")
        img.paste(thumb.resize((w, h), Image.LANCZOS), (x, y))
        _draw_caption(d, it["caption"][0], it["caption"][1], it["block"])
    x0, y, x1 = lay["sofa"]
    weight, tick = max(1, _pt(FOOT_RULE_PT)), _px(0.06)
    d.rectangle([x0, y, x1 - 1, y + weight - 1], fill=INK)
    for end in (x0, x1 - weight):
        d.rectangle([end, y - tick, end + weight - 1, y + tick], fill=INK)
    d.text(lay["sofa_label"][:2], SOFA_LABEL, fill=MUTED, font=_font(MUTED_PT))
    return img


# ---- a size page ----

def _fit(aspect, w, h) -> tuple:
    """The largest (width, height) of that shape inside w x h."""
    if w <= 0 or h <= 0:
        return (0, 0)
    return (round(h * aspect), h) if h * aspect <= w else (w, round(w / aspect))


def size_layout(entry, names, box) -> dict:
    """One size, its map as large as the page allows: the caption goes below a wide
    map and beside a tall one, whichever leaves the map larger."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    aspect = entry["print_in"][0] / entry["print_in"][1]
    gap = _px(CAPTION_GAP_IN)
    below = _caption_block(entry, names, w)
    beside = _caption_block(entry, names, min(_px(SIDE_CAPTION_IN), w // 3))
    map_below = _fit(aspect, w, h - gap - below["h"])
    map_beside = _fit(aspect, w - _px(MIN_GAP_IN) - beside["w"], h)
    if map_beside[0] * map_beside[1] > map_below[0] * map_below[1]:
        mw, mh = map_beside
        return {"map": (x0, y0, mw, mh), "block": beside,
                "caption": (x0 + mw + _px(MIN_GAP_IN), y0, beside["w"], beside["h"])}
    mw, mh = map_below
    return {"map": (x0, y0, mw, mh), "block": below,
            "caption": (x0, y0 + mh + gap, below["w"], below["h"])}


def size_page(entry, names, title, page=None, pages=None):
    """One size, its map as large as the page allows."""
    img, d, box = _page(title, names[entry["key"]]["name"], False, page, pages)
    lay = size_layout(entry, names, box)
    x, y, w, h = lay["map"]
    art = Image.open(entry["image"]).convert("RGB")
    img.paste(art.resize((w, h), Image.LANCZOS), (x, y))
    _draw_caption(d, lay["caption"][0], lay["caption"][1], lay["block"])
    return img


def write(path, entries, names, title) -> int:
    """Write the PDF and return its page count. A size that is not offered has no page.
    The file is written under a temporary name in its own folder and then renamed, so
    a write that fails leaves no half file and keeps the last good preview."""
    offered = [e for e in entries if e["offered"]]
    count = 1 + len(offered)
    pages = [wall_page(offered, names, title, 1, count)]
    pages += [size_page(e, names, title, k, count) for k, e in enumerate(offered, start=2)]
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # not mkstemp: its file is owner-only, and this one goes to a client
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        pages[0].save(tmp, "PDF", save_all=True, append_images=pages[1:],
                      resolution=PAGE_DPI, quality=90, subsampling=0)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass
        raise
    return count
