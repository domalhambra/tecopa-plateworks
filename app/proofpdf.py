# app/proofpdf.py
"""The client's proof as a PDF: one Letter page with the title, the map fitted and the
lines the client reads under it.

Pillow writes it, as app/previewpdf.py does, and the page uses that module's measures
and type: the engine's own font chain (no font is in the repo), black text on white
paper, 0.5 in margins, every length in inches or points. The page is landscape when the
map is wider than tall."""
import os

from PIL import Image

from app import previewpdf as pp
from app.order import OrderError

TITLE_GAP_IN = 0.15      # between the title and the map
LINES_GAP_IN = 0.2       # between the map and the lines under it


def _page_size(image) -> tuple:
    """Letter in px, landscape when the map is wider than tall."""
    w, h = pp.PAGE_IN
    if image.width <= image.height:
        w, h = h, w
    return pp._px(w), pp._px(h)


def layout(image, title, lines) -> dict:
    """Where everything goes, in px: the page, the title lines, the lines under the map,
    and the box the map is fitted into (centred, never enlarged past the page)."""
    page_w, page_h = _page_size(image)
    margin = pp._px(pp.MARGIN_IN)
    width = page_w - 2 * margin
    head_font, body_font = pp._font(pp.TITLE_PT), pp._font(pp.BODY_PT)
    head_lead, body_lead = pp._pt(pp.LEADING[pp.TITLE_PT]), pp._pt(pp.LEADING[pp.BODY_PT])
    head = [pp.shorten(title or "", head_font, width)]
    body = [part for line in lines for part in pp.wrap(line, body_font, width)]
    y = margin
    head_boxes = [(margin, y + k * head_lead, text) for k, text in enumerate(head)]
    y += head_lead * len(head) + pp._px(TITLE_GAP_IN)
    body_h = body_lead * len(body)
    map_h = page_h - margin - body_h - pp._px(LINES_GAP_IN) - y
    scale = min(width / image.width, map_h / image.height)
    mw, mh = max(1, int(image.width * scale)), max(1, int(image.height * scale))
    mx, my = margin + (width - mw) // 2, y + (map_h - mh) // 2
    by = page_h - margin - body_h
    body_boxes = [(margin, by + k * body_lead, text) for k, text in enumerate(body)]
    return {"page": (page_w, page_h), "head": head_boxes, "body": body_boxes,
            "map": (mx, my, mw, mh)}


def write(path, image, title, lines) -> None:
    """Write the PDF. The file is written under a temporary name in its own folder and
    renamed, so a write that fails leaves no half file and keeps the last good proof.
    A folder or a file that cannot be written is an OrderError that names the path."""
    from PIL import ImageDraw
    lay = layout(image, title, lines)
    page = Image.new("RGB", lay["page"], pp.PAPER)
    x, y, w, h = lay["map"]
    page.paste(image.convert("RGB").resize((w, h), Image.LANCZOS), (x, y))
    d = ImageDraw.Draw(page)
    for bx, by, text in lay["head"]:
        d.text((bx, by), text, fill=pp.INK_STRONG, font=pp._font(pp.TITLE_PT))
    for bx, by, text in lay["body"]:
        d.text((bx, by), text, fill=pp.INK, font=pp._font(pp.BODY_PT))
    path = os.path.abspath(path)
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        page.save(tmp, "PDF", resolution=pp.PAGE_DPI, quality=pp.JPEG_QUALITY,
                  subsampling=0, title=title or pp.BRAND, author=pp.BRAND)
        os.replace(tmp, path)
    except BaseException as ex:
        try:
            os.remove(tmp)
        except OSError:
            pass
        if isinstance(ex, OSError):
            raise OrderError(f"The proof PDF cannot be written to {path}: "
                             f"{ex.strerror or ex}") from ex
        raise
