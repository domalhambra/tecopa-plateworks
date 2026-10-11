# app/panels.py
"""Panel geometry for a set: the one source of where a panel and a gap strip are.

A set is one sheet in the spec (its hung size, gaps included), painted once and then
cut. Every caller that needs a seam asks this module: the cut, the proof's wall tone,
the label keep-out, the furniture and the studio's restore. It imports nothing from
`app`, so `app.spec` can use it in validate()."""
from PIL import ImageDraw

PANEL_SHORT_IN = 17.0          # the roll's width
PANEL_LONG_IN = 22.0
PANEL_COUNTS = (1, 2, 3)
GAPS_IN = (0.0, 2.0, 4.0)      # 0 is a cut set: every part of the map is printed
WALL_TONE = (236, 232, 224)    # a gap strip in a proof or a preview


def sheet_sizes(panels, gap_in) -> list:
    """The two sheets a set can have, as (width, height) in inches: panels 22 in
    across, then panels 17 in across."""
    n, g = int(panels), float(gap_in)
    return [(n * PANEL_LONG_IN + (n - 1) * g, PANEL_SHORT_IN),
            (n * PANEL_SHORT_IN + (n - 1) * g, PANEL_LONG_IN)]


def is_set(spec) -> bool:
    return spec.panels > 1


def panel_size_in(spec) -> tuple:
    """(width, height) of one panel in inches. A single sheet is its own panel."""
    if not is_set(spec):
        return (spec.print_w_in, spec.print_h_in)
    h = float(spec.print_h_in)
    across = PANEL_LONG_IN if abs(h - PANEL_SHORT_IN) < 1e-6 else PANEL_SHORT_IN
    return (across, h)


def panel_spans_in(spec) -> list:
    """[(x0, x1)] in inches from the sheet's left edge, one for each panel."""
    pw, _ = panel_size_in(spec)
    step = pw + (float(spec.panel_gap_in) if is_set(spec) else 0.0)
    return [(k * step, k * step + pw) for k in range(spec.panels)]


def panel_rects_px(spec, dpi) -> list:
    """[(x0, y0, x1, y1)] in sheet pixels, right and bottom exclusive. Each edge is
    rounded on its own, so the panels and the gap strips tile the sheet at any dpi."""
    h = round(spec.print_h_in * dpi)
    return [(round(x0 * dpi), 0, round(x1 * dpi), h) for x0, x1 in panel_spans_in(spec)]


def gap_rects_px(spec, dpi) -> list:
    """The strips between panels. A cut set has none."""
    rects = panel_rects_px(spec, dpi)
    return [(a[2], 0, b[0], a[3]) for a, b in zip(rects, rects[1:]) if b[0] > a[2]]


def seam_bands_px(spec, dpi, edge) -> list:
    """What a place name must stay clear of: each gap strip, or each seam of a cut
    set, grown by `edge` pixels on both sides."""
    rects = panel_rects_px(spec, dpi)
    return [(a[2] - edge, 0, b[0] + edge, a[3]) for a, b in zip(rects, rects[1:])]


def span_px_at(spec, x_px, dpi, out_w) -> tuple:
    """(lo, hi) in pixels of the panel that holds x, or of the nearest panel when x
    is behind a gap. A single sheet is the whole canvas."""
    if not is_set(spec):
        return (0, out_w)

    def distance(r):
        return 0 if r[0] <= x_px < r[2] else min(abs(x_px - r[0]), abs(x_px - r[2]))
    best = min(panel_rects_px(spec, dpi), key=distance)
    return (best[0], best[2])


def furniture_trim_px(spec, dpi, trim) -> tuple:
    """The box the furniture is placed in: panel 1 of a set, else the trim box."""
    return panel_rects_px(spec, dpi)[0] if is_set(spec) else tuple(trim)


def frame_rects_px(spec, dpi, trim) -> list:
    """One box for each printed piece: the panels of a set, else the trim box."""
    return panel_rects_px(spec, dpi) if is_set(spec) else [tuple(trim)]


def cut(img, spec, dpi) -> list:
    """The sheet as one image for each panel. The gap strips are dropped."""
    return [img.crop(r) for r in panel_rects_px(spec, dpi)]


def paint_gaps(img, spec, dpi, tone=WALL_TONE):
    """A copy of the sheet with each gap strip in the wall tone, so a proof shows the
    set as it hangs. A single sheet and a cut set come back unchanged."""
    gaps = gap_rects_px(spec, dpi) if is_set(spec) else []
    if not gaps:
        return img
    out = img.copy()
    d = ImageDraw.Draw(out)
    for x0, y0, x1, y1 in gaps:
        d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=tone)
    return out
