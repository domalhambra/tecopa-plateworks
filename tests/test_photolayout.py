"""Photo layout (order photos, Task 6): boxes in open ground, or the gallery band.
Pure geometry on hand-built Occupancy objects: no render, no plate."""
import math

import numpy as np

from app import photolayout, render
from app.render import Occupancy

DPI = 100.0
W = H = 2000      # a 20 x 20 in canvas at 100 dpi
BOX = 1.0


def occ(route_rects=(), rects=(), trim=None, size=(W, H)):
    route = np.zeros((size[1], size[0]), dtype=bool)
    for x0, y0, x1, y1 in route_rects:
        route[y0:y1, x0:x1] = True
    return Occupancy(size_px=size, route=route, rects=list(rects), dpi=DPI, trim_px=trim)


def box_px(spot, off, box=BOX):
    cx, cy = (spot[0] + off[0]) * DPI, (spot[1] + off[1]) * DPI
    h = box * DPI / 2
    return cx - h, cy - h, cx + h, cy + h


def overlaps(a, b, pad=0.0):
    return (a[0] < b[2] + pad and b[0] < a[2] + pad
            and a[1] < b[3] + pad and b[1] < a[3] + pad)


def leader(spot, off):
    ax, ay = spot[0] * DPI, spot[1] * DPI
    end = render._leader_end(ax, ay, box_px(spot, off))
    return None if end is None else ((ax, ay), end)


def _ccw(a, b, c):
    return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_cross(p, q):
    (a, b), (c, d) = p, q
    return (_ccw(a, c, d) * _ccw(b, c, d) < 0) and (_ccw(a, b, c) * _ccw(a, b, d) < 0)


def test_one_photo_takes_the_shortest_clear_leader():
    spot = (10.0, 10.0)
    out = photolayout.layout([spot], BOX, occ())
    assert out["layout"] == "open"
    assert out["unplaced"] == []
    # nothing in the way: north, the first direction, at the shortest step (0.6 in of air)
    dx, dy = out["boxes"][0]
    assert math.isclose(dx, 0.0, abs_tol=1e-6)
    assert math.isclose(dy, -(0.6 + BOX / 2), abs_tol=1e-6)
    # a rect over the northern approach: the shortest leader that is still clear wins
    blocked = occ(rects=[(900, 0, 1100, 890)])
    dx, dy = photolayout.layout([spot], BOX, blocked)["boxes"][0]
    assert math.isclose(dx, 0.6 + BOX / 2, abs_tol=1e-6)      # east, step 0.6
    assert math.isclose(dy, 0.0, abs_tol=1e-6)


def test_boxes_never_overlap_routes_or_furniture():
    spots = [(4.0, 4.0), (6.0, 4.5), (5.0, 7.0), (12.0, 8.0), (13.0, 12.0), (8.0, 14.0)]
    o = occ(route_rects=[(300, 300, 700, 330), (500, 500, 540, 900), (1000, 700, 1400, 740)],
            rects=[(0, 1500, 600, 1700), (1100, 1000, 1500, 1100)],
            trim=(100, 100, 1800, 1800))
    out = photolayout.layout(spots, BOX, o)
    assert out["layout"] == "open"
    assert sorted(out["boxes"]) == list(range(len(spots)))
    tx0, ty0, tx1, ty1 = o.trim_px
    placed = []
    for i, off in out["boxes"].items():
        b = box_px(spots[i], off)
        assert b[0] >= tx0 and b[1] >= ty0 and b[2] <= tx1 and b[3] <= ty1
        x0, y0, x1, y1 = (math.floor(b[0]), math.floor(b[1]), math.ceil(b[2]), math.ceil(b[3]))
        assert not o.route[y0:y1, x0:x1].any()
        assert not any(overlaps(b, r) for r in o.rects)
        for other in placed:
            assert not overlaps(b, other, pad=render.BAND_PAD_IN * DPI - 1e-6)
        placed.append(b)


def test_leaders_never_cross():
    # photo 0 is fixed far east of its spot: a long horizontal leader along y = 5 in.
    # Photo 1's shortest candidate (north) would cross it, so it must go elsewhere.
    spots = [(5.0, 5.0), (7.0, 6.0)]
    out = photolayout.layout(spots, BOX, occ(), fixed={0: (4.0, 0.0)})
    assert out["layout"] == "open"
    lead0, lead1 = leader(spots[0], out["boxes"][0]), leader(spots[1], out["boxes"][1])
    assert not segments_cross(lead0, lead1)
    assert out["boxes"][1] != (0.0, -(0.6 + BOX / 2))
    # a crowd of near neighbours: no two leaders cross
    crowd = [(8.0, 8.0), (10.5, 8.3), (13.0, 8.0), (8.4, 11.0), (11.0, 11.2), (13.5, 11.0)]
    out = photolayout.layout(crowd, BOX, occ())
    assert out["layout"] == "open"
    leads = [leader(crowd[i], out["boxes"][i]) for i in sorted(out["boxes"])]
    for a in range(len(leads)):
        for b in range(a + 1, len(leads)):
            assert not segments_cross(leads[a], leads[b])


def test_a_fixed_box_is_kept():
    spots = [(5.0, 5.0), (6.6, 5.0), (12.0, 12.0)]
    mine = (0.3, 0.2)                                    # right on top of photo 1's spot
    o = occ(route_rects=[(450, 450, 650, 650)])          # and on the route, so invalid
    out = photolayout.layout(spots, BOX, o, fixed={0: mine})
    assert out["layout"] == "open"
    assert out["boxes"][0] == mine
    fixed_box = box_px(spots[0], mine)
    for i in (1, 2):
        b = box_px(spots[i], out["boxes"][i])
        assert not overlaps(b, fixed_box, pad=render.BAND_PAD_IN * DPI - 1e-6)
    # the fixed box does not make the layout fall to the band by itself
    assert out["unplaced"] == []


def test_nine_photos_use_the_band():
    spots = [(2.0 + 2 * i, 3.0) for i in range(9)]
    assert photolayout.OPEN_MAX == 8
    out = photolayout.layout(spots, BOX, occ())
    assert out == {"layout": "band", "boxes": {}, "unplaced": []}
    assert photolayout.layout(spots[:8], BOX, occ())["layout"] == "open"


def test_a_blocked_photo_sends_all_to_the_band():
    spots = [(5.0, 5.0), (14.0, 14.0)]
    # photo 1 sits in a route-covered field wider than every ring step
    o = occ(route_rects=[(900, 900, 1900, 1900)])
    out = photolayout.layout(spots, BOX, o)
    assert out == {"layout": "band", "boxes": {}, "unplaced": []}


def test_no_box_straddles_a_seam():
    seam = (990, 0, 1010, H)                 # a vertical seam band, 9.9 to 10.1 in
    spots = [(9.5, 5.0), (10.5, 9.0), (9.7, 13.0), (10.3, 16.0)]
    out = photolayout.layout(spots, BOX, occ(rects=[seam]))
    assert out["layout"] == "open"
    assert len(out["boxes"]) == 4
    for i, off in out["boxes"].items():
        assert not overlaps(box_px(spots[i], off), seam)


def test_same_inputs_same_layout():
    spots = [(4.0, 4.0), (6.0, 4.5), (5.0, 7.0), (12.0, 8.0), (13.0, 12.0)]
    o = occ(route_rects=[(300, 300, 700, 330)], rects=[(0, 1500, 600, 1700)])
    a = photolayout.layout(spots, BOX, o, fixed={3: (1.0, 1.0), 1: (-1.5, 0.5)})
    b = photolayout.layout(spots, BOX, o, fixed={1: (-1.5, 0.5), 3: (1.0, 1.0)})
    c = photolayout.layout(list(spots), BOX, o, fixed={1: (-1.5, 0.5), 3: (1.0, 1.0)})
    assert a == b == c
    assert list(a["boxes"]) == list(b["boxes"])
