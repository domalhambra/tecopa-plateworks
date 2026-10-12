# tests/test_render_memory.py
"""The live memory of a final, in bytes for each output pixel.

A final holds its whole padded window in memory, and the largest sheet a set renders
is 116.8 megapixels, so the bytes a render holds for each pixel decide whether that
sheet fits in the 16 GB agreed for it. On 2026-10-11 the relief was trimmed from 115
to 140 live bytes a pixel to 75 to 81 (docs/relief-passes.md, "Memory"). Nothing else
would notice if that were lost: an array kept alive one stage too long, or a banded
block written back as a whole-sheet expression, moves no pixel and fails no other
test. These tests render a small sheet and hold the numbers.

Why tracemalloc, and not the footprint of the process. tracemalloc counts the Python
and NumPy allocations that are live, which is exactly what the trim changes, and with
one relief worker the count is the same on every run. The footprint is not: the macOS
allocator keeps freed large blocks counted against the process, so it reads about
60 bytes a pixel above the live figure and moves from run to run, and on Linux the
number means something else again. tracemalloc does not see memory that a C library
takes for itself (Pillow's images, scipy's line buffers, GDAL's block cache), so the
bounds below are for the engine's own arrays and are not a size for the process.

Why more than one number. The peak of the whole render is the fan-out of the relief
passes and the light they build. Everything the trim frees later sits under that
peak, so a release lost there does not move it: the peak alone caught 6 of 20 single
reverts. So the render is cut into SEGMENTS at marks that already exist (the four
stages of the relief registry, and the entry and exit of a few functions), and two
numbers are held for each segment:

    peak   the most that was live in the segment, above the level at its first mark
    end    the level at its last mark, above the level at its first

`peak` holds a banded block and a plane that is freed inside the segment. `end` holds
a plane that should be gone by the next mark: a lost `del` raises it by the size of
the plane and may not move any peak.

The bounds. Each segment number is bounded at the value in MEASURED plus SLACK, 2 bytes
a pixel. The smallest full-sheet plane is a float32 scalar, 4 bytes for each pixel of
the padded window and 5.02 for each output pixel here, so one lost plane of any kind
fails. tracemalloc counts a NumPy buffer exactly, so on one platform the numbers
repeat to 0.01. A number that falls more than SLACK below the table fails too: the
table is then stale, and a stale table hides the next lost plane. The peak of the
whole render keeps its looser bound (CASES), about 15 % above the measured value: it
also covers the painters after the relief, which this file does not hold tightly.

When a bound must move. A change that needs one more full-sheet plane, or that frees
one, changes the table in the same commit and says why. A new NumPy, SciPy or Python
may also allocate differently (a temporary reused where it was not, or the reverse).
Measure again and paste the table that this prints over MEASURED:

    .venv/bin/python -m tests.test_render_memory

One relief worker, so no number depends on which passes happen to overlap."""
import contextlib
import json
import os
import tracemalloc

import numpy as np
import pytest

from app import relief, render
from app.spec import CompositionSpec
from tests.conftest import synthetic_region

REGION_DIR = synthetic_region("lassen_ca")
DPI = 300
SHEET_IN = (9.0, 12.0)              # 2700 x 3600 px: 9.7 megapixels
SLACK = 2.0                         # bytes a pixel a segment may read above the table


def _cfg():
    with open(os.path.join(REGION_DIR, "region.json")) as f:
        return json.load(f)


def _spec(width_m, **kw):
    """A 9 x 12 in sheet centred on the plate, `width_m` of ground across. Place names
    are off and every look is at its spec default unless `kw` says otherwise."""
    cfg = _cfg()
    b = cfg["bounds"]
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    w, h = width_m, width_m * SHEET_IN[1] / SHEET_IN[0]
    crop = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    d = dict(region_id=cfg["id"], crs=cfg["crs"], crop=crop,
             print_w_in=SHEET_IN[0], print_h_in=SHEET_IN[1],
             native_resolution_m=cfg["native_resolution_m"],
             tracks=[np.array([[crop[0] + 2000, crop[1] + 2000],
                               [crop[2] - 2000, crop[3] - 2000]])],
             hotspots=[], seed=7, title_text="Memory")
    d.update(kw)
    return CompositionSpec(**d)


# ---- the marks ------------------------------------------------------------------------
# A SPAN is a function that marks its entry ("<name> in") and its exit ("<name> out").
# A POINT is a function that marks its first call inside one span, and is used where
# the span has no other seam at the place that matters. Each is replaced for the
# length of one measurement and put back (see `seams`).
SPANS = (
    (render, "shaded_relief", "relief"),        # the name render calls the relief by
    (render, "_biome_layers", "land cover"),    # called once, inside base_colour
    (relief, "hillshade", "hillshade"),         # the archival light, and the journey sun
    (relief, "_shadow_terms", "shadow"),
    (relief, "_depth_atmosphere", "depth"),
    (render, "_draw_contours", "contours"),
    (render, "_contour_distance", "distance"),
)
POINTS = (
    # the pre-smooth is the first reader of the window in _shadow_terms: a copy made
    # before it is live here and gone before the span's own peak
    (relief, "gaussian_filter", "pre-smooth", "shadow"),
    # the contour blend asks for its bands once: the planes that built the coverage
    # must be gone by then
    (render, "_bands", "blend", "contours"),
)
PROBE = "memory-probe"              # the registered pass that marks each relief stage
# A segment that starts at one of these is outside the relief and the contours: the
# window read before them and the painters after them. Only the whole peak holds it.
NOT_HELD_FROM = ("start", "relief out", "contours out")


class Gauge:
    """The marks of one render: (name, live bytes at the mark, peak since the last)."""

    def __init__(self):
        self.marks = []
        self.open = []                              # [span name, points marked in it]

    def mark(self, name):
        live, peak = tracemalloc.get_traced_memory()
        n = sum(1 for m in self.marks if m[0].split(" #")[0] == name)
        self.marks.append((f"{name} #{n + 1}" if n else name, live, peak))
        tracemalloc.reset_peak()

    def span(self, real, name):
        def marked(*a, **kw):
            self.mark(name + " in")
            self.open.append([name, set()])
            try:
                return real(*a, **kw)
            finally:
                self.open.pop()
                self.mark(name + " out")
        return marked

    def point(self, real, name, within):
        def marked(*a, **kw):
            if self.open and self.open[-1][0] == within and name not in self.open[-1][1]:
                self.open[-1][1].add(name)
                self.mark(name)
            return real(*a, **kw)
        return marked

    def probe(self, stage):
        def marked(arr, frame):                     # a pass that changes nothing
            self.mark(stage)
            return arr
        return marked


@contextlib.contextmanager
def seams(gauge):
    """Put the marks in, with one relief worker, and take them out again."""
    saved = []

    def patch(module, name, new):
        saved.append((module, name, getattr(module, name)))
        setattr(module, name, new)

    try:
        patch(relief, "RELIEF_WORKERS", 1)
        for module, name, label in SPANS:
            patch(module, name, gauge.span(getattr(module, name), label))
        for module, name, label, within in POINTS:
            patch(module, name, gauge.point(getattr(module, name), label, within))
        for stage in relief.RELIEF_STAGES:
            relief.register_relief_pass(stage, PROBE, gauge.probe(stage))
        yield
    finally:
        for stage in relief.RELIEF_STAGES:
            relief.unregister_relief_pass(stage, PROBE)
        for module, name, old in reversed(saved):
            setattr(module, name, old)


def measure(spec, dpi=DPI):
    """One `rasterize` under tracemalloc: (the peak of the whole render, the segments),
    in bytes for each pixel of the sheet it returns. The segments are a dict, in the
    order of the render: "first mark -> last mark" -> (peak, end)."""
    cfg = _cfg()
    gauge = Gauge()
    already = tracemalloc.is_tracing()              # e.g. python -X tracemalloc
    if not already:
        tracemalloc.start()
    try:
        with seams(gauge):
            gauge.mark("start")
            img = render.rasterize(spec, dpi=dpi, region_dir=REGION_DIR, cfg=cfg)
            gauge.mark("end")
    finally:
        if not already:
            tracemalloc.stop()
    px = img.size[0] * img.size[1]
    marks = gauge.marks
    whole = (max(m[2] for m in marks[1:]) - marks[0][1]) / px
    segments = {}
    for (first, level, _), (last, live, peak) in zip(marks, marks[1:]):
        if first not in NOT_HELD_FROM:
            # (+ 0.0 turns the -0.0 that rounding can give into 0.0)
            segments[f"{first} -> {last}"] = (round((peak - level) / px, 2) + 0.0,
                                              round((live - level) / px, 2) + 0.0)
    return whole, segments


# case -> (ground width in metres, spec fields, bound on the whole peak, bytes a pixel).
# The whole peak, measured 2026-10-11 on this synthetic plate with one relief worker,
# at the commit before the trim (4a28e58) and after it; the same to 0.01 on a second run:
#   the default look            115.41 ->  75.27
#   land cover and contours     135.48 ->  75.26
#   the golden grade            140.49 ->  80.52
#   terrain depth               115.41 ->  75.26
CASES = {
    "the default look": (27_000.0, {}, 87.0),
    "land cover and contours": (27_000.0, dict(biome=True, contours=True), 87.0),
    "the golden grade": (27_000.0, dict(light_mode="journey", sun_azimuth_deg=250.0,
                                        sun_altitude_deg=18.0, golden_strength=0.7), 93.0),
    # 57 km on 9 in is 1:249,000, where the scale-keyed depth pass is on
    "terrain depth": (57_000.0, {}, 87.0),
}

# case -> segment -> (peak, end), bytes a pixel. Printed by this file (see the top).
MEASURED = {
    "the default look": {    # the whole peak: 75.27
        "relief in -> color": (26.36, 25.09),
        "color -> hillshade in": (25.09, 10.04),
        "hillshade in -> hillshade out": (20.07, 5.02),
        "hillshade out -> shadow in": (25.09, 10.04),
        "shadow in -> pre-smooth": (0.00, 0.00),
        "pre-smooth -> shadow out": (11.06, 10.04),
        "shadow out -> light": (10.04, 0.00),
        "light -> finish": (0.00, -14.81),
        "finish -> grade": (3.03, 0.00),
        "grade -> relief out": (15.34, -41.63),
    },
    "land cover and contours": {    # the whole peak: 75.26
        "relief in -> land cover in": (15.05, 10.04),
        "land cover in -> land cover out": (42.65, 20.07),
        "land cover out -> color": (20.15, -5.02),
        "color -> hillshade in": (25.09, 10.04),
        "hillshade in -> hillshade out": (20.07, 5.02),
        "hillshade out -> shadow in": (25.09, 10.04),
        "shadow in -> pre-smooth": (0.00, 0.00),
        "pre-smooth -> shadow out": (11.06, 10.04),
        "shadow out -> light": (10.04, 0.00),
        "light -> finish": (0.00, -14.81),
        "finish -> grade": (3.03, 0.00),
        "grade -> relief out": (15.34, -41.63),
        "contours in -> distance in": (5.00, 4.00),
        "distance in -> distance out": (28.00, 12.00),
        "distance out -> blend": (9.00, 0.00),
        "blend -> contours out": (3.00, -13.00),
    },
    "the golden grade": {    # the whole peak: 80.52
        "relief in -> color": (26.36, 25.09),
        "color -> hillshade in": (25.09, 10.04),
        "hillshade in -> hillshade out": (20.07, 5.02),
        "hillshade out -> shadow in": (25.09, 10.04),
        "shadow in -> pre-smooth": (0.00, 0.00),
        "pre-smooth -> shadow out": (11.06, 10.04),
        "shadow out -> light": (10.04, 0.00),
        "light -> hillshade in #2": (0.00, -4.78),
        "hillshade in #2 -> hillshade out #2": (20.07, 5.02),
        "hillshade out #2 -> finish": (5.02, -15.05),
        "finish -> grade": (3.03, 0.00),
        "grade -> relief out": (15.34, -41.63),
    },
    "terrain depth": {    # the whole peak: 75.26
        "relief in -> color": (26.36, 25.09),
        "color -> hillshade in": (25.09, 10.04),
        "hillshade in -> hillshade out": (20.07, 5.02),
        "hillshade out -> shadow in": (30.11, 10.04),
        "shadow in -> pre-smooth": (0.00, 0.00),
        "pre-smooth -> shadow out": (11.06, 10.04),
        "shadow out -> light": (10.04, 0.00),
        "light -> depth in": (0.00, -14.81),
        "depth in -> depth out": (20.12, 0.00),
        "depth out -> finish": (0.00, 0.00),
        "finish -> grade": (3.03, 0.00),
        "grade -> relief out": (15.34, -41.63),
    },
}


def problems(case, whole, segments):
    """What is wrong with one render of `case`: a line for each number over its bound.
    An empty list is a pass. A number UNDER the table is reported only when none is
    over: a plane that outlives its segment is freed in a later one, and that later
    segment then ends lower than it was measured, which is the same fault seen twice."""
    want = MEASURED[case]
    over, under = [], []
    if whole >= CASES[case][2]:
        over.append(f"the whole render: peak {whole:.2f}, bound {CASES[case][2]:.2f}")
    if list(segments) != list(want):
        gone = [s for s in want if s not in segments]
        new = [s for s in segments if s not in want]
        over.append(f"the marks are not the ones measured (gone: {gone}; new: {new}): a "
                    f"function this test marks is no longer called where it was")
    for name, got in segments.items():
        for what, g, w in zip(("peak", "end"), got, want.get(name, got)):
            if g > w + SLACK:
                over.append(f"{name}: {what} {g:+.2f}, bound {w + SLACK:+.2f}")
            elif g < w - SLACK:
                under.append(f"{name}: {what} {g:+.2f} is under the measured {w:+.2f}. "
                             f"The table is stale: measure again")
    return over or under


@pytest.mark.parametrize("case", list(CASES))
def test_a_final_holds_few_live_bytes_for_each_pixel(case):
    width_m, fields, _bound = CASES[case]
    spec = _spec(width_m, **fields)
    if case == "terrain depth":
        assert render._terrain_depth(spec) > 0.2, "this crop must switch the depth pass on"
    wrong = problems(case, *measure(spec))
    assert not wrong, (
        f"{case}: live bytes for each output pixel of a 9 x 12 in final, by segment of "
        f"the render (peak: above the level at the segment's first mark; end: the level "
        f"at its last mark):\n  " + "\n  ".join(wrong) + "\nA full-sheet array is alive "
        "longer than it is read, or a per-pixel block builds sheet-sized temporaries "
        "again (docs/relief-passes.md, Memory). If the change is meant, measure again: "
        "see the top of this file.")


def test_the_gauge_sees_one_scalar_plane(monkeypatch):
    """The gauge itself. The smallest plane a render can lose track of is one float32
    scalar plane, 5 bytes for each output pixel. Kept alive from the valley pass on,
    it must break the bound of the segment it is made in, and of no segment before
    that one. If it did not, the test above could not fail for a lost `del`."""
    case = "the default look"
    real = relief.valley_pass
    held = []

    def hoarding(*a, **kw):
        out = real(*a, **kw)
        held.append(out.copy())                     # a plane nothing reads, never freed
        return out

    monkeypatch.setattr(relief, "valley_pass", hoarding)
    whole, segments = measure(_spec(CASES[case][0]))
    held.clear()
    wrong = problems(case, whole, segments)
    assert len(wrong) == 1 and wrong[0].startswith("hillshade out -> shadow in: end"), wrong
    # and the peak of the whole render does not see it: that bound alone is not enough
    assert whole < CASES[case][2]


def test_the_marks_are_taken_out_again():
    before = {(m, n): getattr(m, n) for m, n, *_ in SPANS + POINTS}
    workers = relief.RELIEF_WORKERS
    with seams(Gauge()):
        assert relief.registered_relief_passes("grade")[-1] == PROBE
        assert relief.RELIEF_WORKERS == 1
    assert all(getattr(m, n) is f for (m, n), f in before.items())
    assert relief.RELIEF_WORKERS == workers
    assert all(PROBE not in names for names in relief.registered_relief_passes().values())


def _table():
    """MEASURED, measured now, as the text of the literal."""
    lines = ["MEASURED = {"]
    for case, (width_m, fields, _bound) in CASES.items():
        whole, segments = measure(_spec(width_m, **fields))
        lines.append(f'    "{case}": {{    # the whole peak: {whole:.2f}')
        lines += [f'        "{name}": ({peak:.2f}, {end:.2f}),'
                  for name, (peak, end) in segments.items()]
        lines.append("    },")
    return "\n".join(lines + ["}"])


if __name__ == "__main__":
    print(_table())
