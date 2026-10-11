# app/orderpreview.py
"""The size preview of an order: frame the tracks at every size, offer the sizes that
suit them, show each one on a coarse plate, and write the PDF and the report.

Every size is framed as Prepare frames it (app/orderprep.py, prepare), by the same
decisions in the same order. First curated_fit: when a curated plate holds the sheet
as a print, the size is in that plate's projection, on its nestled frame with no
widening, and it is drawn on that plate. Else the projection is order_epsg of the
tracks at that sheet's aspect, the frame is nestled on the tracks' box in it, and the
2x rule can widen it. So a size's map is the ground its print will show, and the fit
rule judges the frame Prepare will make. (Prepare skips curated_fit for a `manual`
frame of state.json. The preview has no manual frame.)

A plate has one projection (invariant 4), so the offered sizes are grouped by plate:
the curated plate of their fit, or the projection of the plate to build. Almost always
that is one plate. It is two when a set is wide enough for Albers while a single sheet
is not, or when a curated plate holds a single sheet and is too coarse for a set.

Spec: docs/superpowers/specs/2026-10-11-print-sizes-panel-sets-and-size-preview-design.md,
section 5. This file never imports app.main, and it imports the renderer only inside
render_maps, so the framing can be tested with no DEM."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import numpy as np

from app import panels as panel_geo
from app import previewpdf, sizes
from app.geo import RegionGeo
from app.ingest import load_tracks, lonlat_extent
from app.order import (ORIENTATIONS, SIZE_KEYS, OrderError, load, orders_root,
                       parse_order_size, refuse_inside_repo)
from app.orderplate import (MAX_UPSAMPLE, PLATE_PAD_M, CoverageError, PlateError,
                            choose_grid, conus_covered, curated_fit, nestled_frame,
                            order_epsg, plate_bounds, project_bbox, to_lonlat_bbox,
                            track_shares)
from app.regionbuild import slugify
from app.spec import TITLE_MAX_CHARS, CompositionSpec, SpecError

SET_MIN_FILL = 0.30        # a set is offered when the tracks span this share of its width
PREVIEW_GAP_IN = 2.0       # every set is framed and shown at this gap


@dataclass(frozen=True)
class Candidate:
    key: str               # "11x17", "17x22", "two" or "three"
    panels: int
    orientation: str       # "portrait" or "landscape"
    print_in: tuple        # (width, height) in inches: for a set, the hung sheet
    gap: float

    @property
    def aspect(self) -> float:
        return self.print_in[0] / self.print_in[1]


def candidates(key) -> list:
    """The two orientations of one size. Landscape on a set is panels 22 in across."""
    (short, long_), panels = parse_order_size(key)
    gap = PREVIEW_GAP_IN if panels > 1 else 0.0
    out = []
    for orientation in ORIENTATIONS:
        landscape = orientation == "landscape"
        if panels > 1:
            across = long_ if landscape else short
            size = (panels * across + (panels - 1) * gap, short if landscape else long_)
        else:
            size = (long_, short) if landscape else (short, long_)
        out.append(Candidate(key, panels, orientation, size, gap))
    return out


class Ground:
    """The tracks in one projection: the ground a size is framed and judged on.
    `tracks_m` is each track's vertices, or a function that gives them. The function
    is called when the fit rule first needs the tracks: choosing an orientation reads
    only the box, `bounds_m`. `curated` is the curated plate that holds the sheet as
    a print (a dict of orderprep.curated_regions), or None: Prepare reuses that plate
    and does not widen the frame."""

    def __init__(self, epsg, bounds_m, tracks_m, curated=None):
        self.epsg, self.bounds_m, self._tracks_m = epsg, bounds_m, tracks_m
        self.curated = curated

    @property
    def tracks_m(self) -> list:
        if callable(self._tracks_m):
            self._tracks_m = self._tracks_m()
        return self._tracks_m


class OrderGround:
    """The ground of each candidate as Prepare makes it. Prepare first asks
    curated_fit with the sheet's aspect and print width: a fit gives the curated
    plate and its projection. Else the projection is order_epsg of the tracks at the
    candidate's aspect. The box is project_bbox of the tracks' lon/lat box in that
    projection, and nestled_frame of it is the frame curated_fit returns. Call it
    with a Candidate. `regions` is orderprep.curated_regions. The track files are
    read once for each projection that a chosen size uses."""

    def __init__(self, payloads, tracks_lonlat, regions=()):
        self.payloads, self.tracks_lonlat = payloads, tracks_lonlat
        self.regions = list(regions)
        self._where, self._grounds, self._tracks = {}, {}, {}

    def tracks(self, epsg) -> list:
        """The order's tracks (app.ingest.Track) in one projection."""
        if epsg not in self._tracks:
            self._tracks[epsg] = load_tracks_m(self.payloads, epsg)
        return self._tracks[epsg]

    def __call__(self, cand) -> Ground:
        sheet = (cand.aspect, cand.print_in[0])
        if sheet not in self._where:
            fit = curated_fit(self.tracks_lonlat, cand.aspect, cand.print_in[0], self.regions)
            self._where[sheet] = ((fit["epsg"], fit["region"]) if fit else
                                  (order_epsg(self.tracks_lonlat, cand.aspect), None))
        epsg, region = self._where[sheet]
        key = (epsg, region["id"] if region else None)
        if key not in self._grounds:
            self._grounds[key] = Ground(epsg, project_bbox(self.tracks_lonlat, epsg),
                                        lambda: [t.coords for t in self.tracks(epsg)],
                                        curated=region)
        return self._grounds[key]


def choose(cands, ground) -> Candidate:
    """The orientation with less wasted ground: the one whose nestled frame the
    tracks fill more on their weaker side, each judged on its own ground. A tie
    keeps the first, portrait."""
    def weaker_side(c):
        box = ground(c).bounds_m
        return min(track_shares(box, nestled_frame(box, c.aspect)))
    return max(cands, key=weaker_side)


def _samples(tracks_m, step) -> np.ndarray:
    """Points along every track, at most `step` metres apart, so a long straight
    leg counts on every panel it crosses."""
    out = []
    for t in tracks_m:
        t = np.asarray(t, float).reshape(-1, 2)
        t = t[np.isfinite(t).all(axis=1)]      # ingest drops such a vertex already
        if len(t) < 2:
            out.append(t)
            continue
        dist = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(t, axis=0).T))])
        at = np.linspace(0.0, dist[-1], max(2, int(dist[-1] / step) + 1))
        out.append(np.column_stack([np.interp(at, dist, t[:, 0]), np.interp(at, dist, t[:, 1])]))
    return np.concatenate(out) if out else np.empty((0, 2))


def panels_with_track(tracks_m, frame, cand) -> list:
    """For each panel of a set, True when some part of a track lies on it."""
    w_in = cand.print_in[0]
    pts = _samples(tracks_m, (frame[2] - frame[0]) / 500.0)
    xs = (pts[:, 0] - frame[0]) / (frame[2] - frame[0]) * w_in
    ys = (pts[:, 1] - frame[1]) / (frame[3] - frame[1])
    inside = (ys >= 0.0) & (ys <= 1.0)
    across = (w_in - (cand.panels - 1) * cand.gap) / cand.panels
    step = across + cand.gap
    return [bool(np.any(inside & (xs >= k * step) & (xs <= k * step + across)))
            for k in range(cand.panels)]


def gaps_hiding_ends(tracks_m, frame, cand) -> list:
    """The gaps of a window set, numbered from 1, that hide a route end: the first
    or the last point of a track. A route end is tied to the ground, so only the
    frame can move it. A cut set and a single sheet hide nothing."""
    if cand.panels == 1 or not cand.gap:
        return []
    w_in = cand.print_in[0]
    step = (w_in - (cand.panels - 1) * cand.gap) / cand.panels + cand.gap
    hidden = set()
    for t in tracks_m:
        t = np.asarray(t, float).reshape(-1, 2)
        for x, y in ((t[0], t[-1]) if len(t) else ()):
            if not frame[1] <= y <= frame[3]:
                continue
            at = (x - frame[0]) / (frame[2] - frame[0]) * w_in
            hidden.update(k for k in range(1, cand.panels) if k * step - cand.gap < at < k * step)
    return sorted(hidden)


def _no_track(numbers) -> str:
    """'panel 2 holds no track', 'panels 1 and 3 hold no track'."""
    if len(numbers) == 1:
        return f"panel {numbers[0]} holds no track"
    return f"panels {', '.join(numbers[:-1])} and {numbers[-1]} hold no track"


def _share_under(share, limit) -> str:
    """A share that is under its limit, for a refusal: "24%". The rule compares at
    three places, so a share that prints as the limit gets one decimal: "29.6%",
    never "30% ..., under 30%"."""
    share = round(share, 3)
    whole = f"{share:.0%}"
    return whole if whole != f"{limit:.0%}" else f"{share:.1%}"


def judge(cand, frame, bounds_m, tracks_m) -> dict:
    """One size's entry: its frame, its shares, and the fit rule's answer."""
    w_share, h_share = track_shares(bounds_m, frame)
    entry = {"key": cand.key, "panels": cand.panels, "orientation": cand.orientation,
             "print_in": [float(v) for v in cand.print_in], "gap": cand.gap,
             "frame": [float(v) for v in frame],
             "fill": round(max(w_share, h_share), 3), "width_share": round(w_share, 3),
             "offered": True, "why": "", "warning": "", "blocked": False,
             "ends_behind": gaps_hiding_ends(tracks_m, frame, cand)}
    if cand.panels > 1:
        empty = [str(k + 1) for k, has in enumerate(panels_with_track(tracks_m, frame, cand))
                 if not has]
        if round(w_share, 3) < SET_MIN_FILL:
            entry.update(offered=False,
                         why=f"the tracks span {_share_under(w_share, SET_MIN_FILL)} of the "
                             f"sheet's width, under {SET_MIN_FILL:.0%}")
        elif empty:
            entry.update(offered=False, why=_no_track(empty))
    return entry


def plan_sizes(bounds_m=None, tracks_m=None, widen=None, forced=(), ground=None) -> list:
    """One entry for each size, in menu order.

    `ground(cand)` gives the Ground a candidate is framed and judged on, and each
    entry records the `epsg` of its own and, as `curated`, the id of the curated plate
    that holds the sheet as a print (or None). The preview passes an OrderGround:
    Prepare chooses a projection for each sheet, so one size can be in UTM and the
    next in Albers. With no `ground`, every candidate is on `bounds_m` and `tracks_m`,
    in the one projection the caller works in, and `epsg` and `curated` are None.

    `widen(cand, frame)` returns the frame the real print would get under the 2x
    rule, or raises PlateError when the terrain cannot hold the size. `forced` is
    the `sizes` list of order.toml: it overrides the fit rule, never the terrain.
    A CoverageError from `widen` is not caught: the 3DEP index did not answer, which
    says nothing about the size, so the whole preview stops.

    A size on a curated plate is never widened, and `widen` is not called for it:
    Prepare reuses the plate with the nestled frame, and asks nothing of the 3DEP index.

    `widen` is a query of the 3DEP index, so only a size that can still be offered
    pays for it: one in the list, or with no list one the fit rule accepts on its
    nestled frame. A wider frame has less of its width under the tracks, so the 2x
    rule never brings back a set that the width rule refuses. It could bring back a
    set with an empty middle panel (two walks far apart, pulled toward the middle of
    a wider frame). That set stays refused, and the list can ask for it."""
    if ground is None:
        one = Ground(None, bounds_m, tracks_m)

        def ground(cand):
            return one
    entries = []
    for key in SIZE_KEYS:
        cand = choose(candidates(key), ground)
        here = ground(cand)
        frame = nestled_frame(here.bounds_m, cand.aspect)
        entry = judge(cand, frame, here.bounds_m, here.tracks_m)
        if (here.curated is None and widen is not None
                and (key in forced if forced else entry["offered"])):
            try:
                entry = judge(cand, widen(cand, frame), here.bounds_m, here.tracks_m)
            except CoverageError:
                raise
            except PlateError as ex:
                entry.update(offered=False, why=str(ex), blocked=True)
        entry["epsg"] = here.epsg
        entry["curated"] = here.curated["id"] if here.curated else None
        if forced and not entry["blocked"]:
            if key in forced:
                entry.update(offered=True, warning=entry["why"], why="")
            else:
                entry.update(offered=False, why="it is not in the sizes list of order.toml")
        entries.append(entry)
    return entries


PREVIEW_SINGLE_PX = 1600   # the long side of a single sheet's map
PREVIEW_SET_DPI = 50.0     # a set: 1,100 px along a panel's long side
# the look of a new poster in the studio (the defaults in app/static/store.js)
PREVIEW_LOOK = dict(soft_light=0.35, haze_strength=0.15, water_depth=0.5,
                    label_place="smart", track_weave=True)


def preview_dpi(entry) -> float:
    if entry["panels"] > 1:
        return PREVIEW_SET_DPI
    return PREVIEW_SINGLE_PX / max(entry["print_in"])


def union_frame(entries) -> tuple:
    """The box that holds every offered frame."""
    frames = [e["frame"] for e in entries if e["offered"]]
    return (min(f[0] for f in frames), min(f[1] for f in frames),
            max(f[2] for f in frames), max(f[3] for f in frames))


def preview_need_m(entries) -> float:
    """Metres of ground per pixel of the finest preview map."""
    return min((e["frame"][2] - e["frame"][0]) / (e["print_in"][0] * preview_dpi(e))
               for e in entries if e["offered"])


def plate_groups(entries) -> dict:
    """The offered entries by the plate that shows them, in menu order. The key is the
    id of the curated plate that holds the entry as a print, else the projection the
    entry is framed in: a plate has one projection, so each projection with a size
    to build for gets a plate of its own."""
    groups = {}
    for e in entries:
        if e["offered"]:
            groups.setdefault(e.get("curated") or e["epsg"], []).append(e)
    return groups


def load_tracks_m(payloads, epsg) -> list:
    """Every track of the order in one projection. A file that does not parse is
    left out, as Prepare leaves it out."""
    geo = RegionGeo(crs=f"EPSG:{epsg}", bounds=(0.0, 0.0, 1.0, 1.0), overview_size=(1, 1))
    tracks = []
    for data, name in payloads:
        try:
            tracks += load_tracks(data, geo, filename=name)
        except Exception:
            continue
    return tracks


def render_maps(entries, tracks, plate_dir, title, out_dir) -> None:
    """Draw each offered size at screen size with the word PREVIEW, as
    out_dir/<key>.png, and record `image` and `dpi` on its entry.

    A size the painter refuses (SpecError: for one, OffDemError, a frame with too
    much of its ground past the terrain data) gets no image. Its entry becomes
    `offered` False with the refusal as `why`, and the other sizes are still drawn:
    one refusal must not lose a preview whose plate is already built."""
    from app import render          # here, so the framing needs no renderer
    with open(os.path.join(plate_dir, "region.json")) as f:
        cfg = json.load(f)
    labels = os.path.isfile(os.path.join(plate_dir, "labels.json"))
    os.makedirs(out_dir, exist_ok=True)
    for e in entries:
        if not e["offered"]:
            continue
        dpi = preview_dpi(e)
        try:
            spec = CompositionSpec(
                region_id=cfg["id"], crs=cfg["crs"], crop=tuple(e["frame"]),
                print_w_in=e["print_in"][0], print_h_in=e["print_in"][1],
                native_resolution_m=cfg["native_resolution_m"],
                tracks=[t.coords for t in tracks], track_days=[t.day for t in tracks],
                hotspots=[], seed=7, title_text=title, labels=labels,
                panels=e["panels"], panel_gap_in=e["gap"], **PREVIEW_LOOK)
            img = render.rasterize(spec, dpi=dpi, region_dir=plate_dir, watermark=True,
                                   watermark_text="PREVIEW", cfg=cfg)
        except SpecError as ex:
            e.update(offered=False, why=str(ex))
            continue
        img = panel_geo.paint_gaps(img, spec, dpi)
        path = os.path.join(out_dir, f"{e['key']}.png")
        img.save(path, "PNG")
        e["image"], e["dpi"] = path, round(dpi, 2)


def _curated_plate(tools, region) -> dict:
    return {"id": region["id"], "root": tools.curated_root, "kind": "curated",
            "grid_m": float(region["native_resolution_m"])}


def _preview_plate(order, tools, union, epsg, need, env, cache_dir, log, suffix="",
                   regions=None) -> dict:
    """The plate for sizes that no curated plate holds as prints: a curated plate when
    one holds their frames in this projection at the preview's pixels, else one coarse
    plate built under work/preview/plate/. `suffix` names the plate and the build
    log of a later plate: preview_<order>_5070 and build_5070.log. `regions` is
    orderprep.curated_regions, read again when it is not given."""
    from app.orderprep import (COARSE_LAYERS_M, COARSE_NEED_M, _build, curated_regions,
                               read_coverage)
    bounds = plate_bounds(union)
    for r in curated_regions(tools.curated_root) if regions is None else regions:
        b = r["bounds"]
        if (int(str(r["crs"]).split(":")[1]) == epsg
                and bounds[0] >= b[0] and bounds[1] >= b[1]
                and bounds[2] <= b[2] and bounds[3] <= b[3]
                and r["native_resolution_m"] <= need * MAX_UPSAMPLE):
            log(f"Reusing curated plate {r['id']} for the preview.")
            return _curated_plate(tools, r)
    cov = read_coverage(tools, to_lonlat_bbox(bounds, epsg, pad_m=PLATE_PAD_M), env,
                        layers=COARSE_LAYERS_M if need >= COARSE_NEED_M else None)
    grid = choose_grid(need, cov)
    if grid["widen"]:
        raise PlateError("The terrain data here is too coarse even for a preview.")
    plate, _ = _build(order, tools, union, epsg, grid, env, log, cwd=cache_dir,
                      root=os.path.join(order.work_dir, "preview", "plate"),
                      rid="preview_" + order.id[len("order_"):] + suffix,
                      build_log=os.path.join(order.work_dir, "preview", f"build{suffix}.log"))
    return plate


def _dump(path, data) -> None:
    """Write through a temp file, so a reader never sees half a file. open() gives
    the file the mode of report.txt and the PDF; mkstemp would give it 0600."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def write_preview_report(order, state, names) -> str:
    """What the preview decided, and the lines to write in order.toml for each size
    the client can choose. Prepare then frames that size with the same rule. Each
    key is on a line of its own, so the lines can be pasted into order.toml as they
    are: TOML takes the indent, and it does not take two keys on one line. An offered
    size has the price the PDF prints for it, in quotes, so the prices can be checked
    without opening the PDF."""
    def sentence(text):          # one line, and the report adds the full stop
        return " ".join(str(text).split()).rstrip(".")
    plates = state.get("plates") or [state["plate"]]
    lines = [f"Order: {order.title}", f"Preview: {state['pdf']}"]
    for plate in plates:
        line = f"Plate: {plate['id']} ({plate['kind']}), {plate['grid_m']:g} m grid"
        if len(plates) > 1:       # two projections: say which sizes each plate shows
            line += f", EPSG:{plate['epsg']}, for {', '.join(plate['sizes'])}"
        lines.append(line)
    lines.append("Sizes:")
    for e in state["sizes"]:
        what = (f"{names[e['key']]['name']}, {e['orientation']}, "
                f"{e['print_in'][0]:g} x {e['print_in'][1]:g} in")
        if not e["offered"]:
            lines.append(f"- {what}: not offered, {sentence(e['why'])}.")
            continue
        lines += [f"- {what}: offered, price \"{names[e['key']]['price']}\", "
                  f"tracks fill {e['fill']:.0%}. In order.toml:",
                  f'    size = "{e["key"]}"', f'    orientation = "{e["orientation"]}"']
        if e["panels"] > 1:
            lines.append(f"    gap = {e['gap']:g}")
        if e["warning"]:
            lines.append(f"  Warning: {sentence(e['warning'])}.")
        for k in e["ends_behind"]:
            lines.append(f"  Warning: a route end is behind gap {k}.")
    lines.append(f"Time: {state['seconds']:g} s")
    text = "\n".join(lines) + "\n"
    path = os.path.join(order.work_dir, "preview", "report.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return text


def preview(order_dir, tools, log=print, render=None, write_pdf=None) -> dict:
    """Frame every size as Prepare does, find the plate of each offered size (the
    curated plate Prepare reuses for it, else one coarse plate for each projection),
    draw the offered sizes, and write the PDF, work/preview/preview.json and
    work/preview/report.txt. `render` and `write_pdf` are for tests: stand-ins for
    the two slow steps. A size that the painter refuses is left out, with its reason,
    and the PDF and the report show the sizes that were drawn.

    preview.json: `sizes` holds every entry, each with the `epsg` it is framed in,
    the id of the `curated` plate that holds it as a print (or null) and, when it was
    drawn, the id of its `plate`. `plates` holds each plate once, with its `epsg` and
    the keys of the `sizes` drawn on it. `plate` and
    `epsg` are the first plate and its projection. `names` holds the name and the
    price of every size as the PDF was given them, from config/sizes.toml."""
    from app.orderprep import PREP_VENV_HELP, _plan_grid, cache_env, curated_regions
    refuse_inside_repo(orders_root())
    order = load(order_dir)
    if len(order.title) > TITLE_MAX_CHARS:      # the painter's limit, before any plate
        raise OrderError(f"the title in order.toml has {len(order.title)} characters, "
                         f"and a map holds at most {TITLE_MAX_CHARS}")
    names = sizes.load()         # before the plate: a wrong file must not cost a build
    payloads = order.payloads()
    tracks_ll = lonlat_extent(payloads)["bbox"]
    if tracks_ll is None:
        raise OrderError(f"no track points in {order.in_dir}")
    if not conus_covered(tracks_ll):
        raise PlateError("These tracks are outside the lower 48 states.")
    regions = curated_regions(tools.curated_root)
    ground = OrderGround(payloads, tracks_ll, regions)
    # as Prepare, after the curated check: a sheet on a curated plate needs no prep venv
    on_curated = all(ground(c).curated for key in SIZE_KEYS for c in candidates(key))
    if not on_curated and not os.path.exists(tools.prep_python):
        raise PlateError(f"The prep venv is missing: {tools.prep_python}. "
                         f"Set it up with {PREP_VENV_HELP}.")
    started = time.monotonic()
    if not ground.tracks(ground(candidates(SIZE_KEYS[0])[0]).epsg):
        raise OrderError(f"no track points in {order.in_dir}")
    env, cache_dir = cache_env()

    def widen(cand, frame):
        return _plan_grid(tools, frame, ground(cand).epsg, cand.print_in[0], env)[0]

    entries = plan_sizes(ground=ground, widen=widen, forced=order.sizes)
    offered = [e for e in entries if e["offered"]]
    if not offered:
        raise PlateError("No size can be offered: " + "; ".join(
            f"{e['key']}: {e['why']}" for e in entries))
    log(f"Offering {', '.join(e['key'] for e in offered)}.")
    by_id = {r["id"]: r for r in regions}
    shown = []                               # (plate, its sizes): every plate before any map
    for group in plate_groups(entries).values():
        epsg, on_plate = group[0]["epsg"], group[0]["curated"]
        if on_plate:
            plate = _curated_plate(tools, by_id[on_plate])
            log(f"Reusing curated plate {on_plate} for "
                f"{', '.join(e['key'] for e in group)}, as Prepare does.")
        else:
            plate = _preview_plate(order, tools, union_frame(group), epsg,
                                   preview_need_m(group), env, cache_dir, log,
                                   suffix=f"_{epsg}" if shown else "", regions=regions)
        plate["epsg"] = epsg
        same = [g for p, g in shown if (p["root"], p["id"]) == (plate["root"], plate["id"])]
        if same:                             # one curated plate shows both groups: list it once
            same[0][:] = sorted(same[0] + group, key=lambda e: SIZE_KEYS.index(e["key"]))
        else:
            shown.append((plate, list(group)))
    work = os.path.join(order.work_dir, "preview")
    plates = []
    for plate, group in shown:
        (render or render_maps)(group, ground.tracks(plate["epsg"]),
                                os.path.join(plate["root"], plate["id"]), order.title, work)
        drawn = [e for e in group if e["offered"]]      # the painter can refuse a size
        plate["sizes"] = [e["key"] for e in drawn]
        for e in drawn:
            e["plate"] = plate["id"]
        if drawn:
            plates.append(plate)
    if not plates:
        raise PlateError("No size could be drawn: " + "; ".join(
            f"{e['key']}: {e['why']}" for e in offered))
    pdf = os.path.join(order.dir, "out", "preview", f"{slugify(order.title)}-preview.pdf")
    (write_pdf or previewpdf.write)(pdf, entries, names, order.title)
    state = {"epsg": plates[0]["epsg"], "plate": plates[0], "plates": plates, "sizes": entries,
             "names": names, "pdf": pdf, "seconds": round(time.monotonic() - started, 1)}
    _dump(os.path.join(work, "preview.json"), state)
    write_preview_report(order, state, names)
    return state
