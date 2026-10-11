# app/orderpreview.py
"""The size preview of an order: frame the tracks at every size, offer the sizes that
suit them, and show each one on a coarse plate.

Spec: docs/superpowers/specs/2026-10-11-print-sizes-panel-sets-and-size-preview-design.md,
section 5. This file never imports app.main, and it imports the renderer only inside
render_maps, so the framing can be tested with no DEM."""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass

import numpy as np

from app import panels as panel_geo
from app.geo import RegionGeo
from app.ingest import load_tracks, lonlat_extent
from app.order import (ORIENTATIONS, SIZE_KEYS, OrderError, load, orders_root,
                       parse_order_size, refuse_inside_repo)
from app.orderplate import (ALBERS_EPSG, MAX_UPSAMPLE, PLATE_PAD_M, PlateError, choose_grid,
                            conus_covered, nestled_frame, order_epsg, plate_bounds,
                            project_bbox, to_lonlat_bbox, track_shares)
from app.regionbuild import slugify
from app.spec import CompositionSpec

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


def choose(cands, bounds_m) -> Candidate:
    """The orientation with less wasted ground: the one whose nestled frame the
    tracks fill more on their weaker side. A tie keeps the first, portrait."""
    return max(cands, key=lambda c: min(track_shares(bounds_m, nestled_frame(bounds_m, c.aspect))))


def _samples(tracks_m, step) -> np.ndarray:
    """Points along every track, at most `step` metres apart, so a long straight
    leg counts on every panel it crosses."""
    out = []
    for t in tracks_m:
        t = np.asarray(t, float).reshape(-1, 2)
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
            entry.update(offered=False, why=f"the tracks span {w_share:.0%} of the sheet's "
                                            f"width, under {SET_MIN_FILL:.0%}")
        elif empty:
            entry.update(offered=False, why=f"panel {' and '.join(empty)} holds no track")
    return entry


def plan_sizes(bounds_m, tracks_m, widen=None, forced=()) -> list:
    """One entry for each size, in menu order.

    `widen(cand, frame)` returns the frame the real print would get under the 2x
    rule, or raises PlateError when the terrain cannot hold the size. `forced` is
    the `sizes` list of order.toml: it overrides the fit rule, never the terrain."""
    entries = []
    for key in SIZE_KEYS:
        cand = choose(candidates(key), bounds_m)
        frame = nestled_frame(bounds_m, cand.aspect)
        try:
            if widen is not None:
                frame = widen(cand, frame)
            entry = judge(cand, frame, bounds_m, tracks_m)
        except PlateError as ex:
            entry = judge(cand, frame, bounds_m, tracks_m)
            entry.update(offered=False, why=str(ex), blocked=True)
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


def preview_epsg(tracks_lonlat) -> int:
    """One projection for every size: Albers when any size's frame needs it, else
    the tracks' own UTM zone."""
    codes = [order_epsg(tracks_lonlat, c.aspect) for key in SIZE_KEYS for c in candidates(key)]
    return ALBERS_EPSG if ALBERS_EPSG in codes else codes[0]


def load_tracks_m(payloads, epsg) -> list:
    """Every track of the order in the preview's projection. A file that does not
    parse is left out, as Prepare leaves it out."""
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
    out_dir/<key>.png, and record `image` and `dpi` on its entry."""
    from app import render          # here, so the framing needs no renderer
    with open(os.path.join(plate_dir, "region.json")) as f:
        cfg = json.load(f)
    labels = os.path.isfile(os.path.join(plate_dir, "labels.json"))
    os.makedirs(out_dir, exist_ok=True)
    for e in entries:
        if not e["offered"]:
            continue
        dpi = preview_dpi(e)
        spec = CompositionSpec(
            region_id=cfg["id"], crs=cfg["crs"], crop=tuple(e["frame"]),
            print_w_in=e["print_in"][0], print_h_in=e["print_in"][1],
            native_resolution_m=cfg["native_resolution_m"],
            tracks=[t.coords for t in tracks], track_days=[t.day for t in tracks],
            hotspots=[], seed=7, title_text=title, labels=labels,
            panels=e["panels"], panel_gap_in=e["gap"], **PREVIEW_LOOK)
        img = render.rasterize(spec, dpi=dpi, region_dir=plate_dir, watermark=True,
                               watermark_text="PREVIEW", cfg=cfg)
        img = panel_geo.paint_gaps(img, spec, dpi)
        path = os.path.join(out_dir, f"{e['key']}.png")
        img.save(path, "PNG")
        e["image"], e["dpi"] = path, round(dpi, 2)


def _preview_plate(order, tools, union, epsg, need, env, cache_dir, log) -> dict:
    """A curated plate when one holds the frames in this projection, else one coarse
    plate built under work/preview/plate/."""
    from app.orderprep import (COARSE_LAYERS_M, COARSE_NEED_M, _build, curated_regions,
                               read_coverage)
    bounds = plate_bounds(union)
    for r in curated_regions(tools.curated_root):
        b = r["bounds"]
        if (int(str(r["crs"]).split(":")[1]) == epsg
                and bounds[0] >= b[0] and bounds[1] >= b[1]
                and bounds[2] <= b[2] and bounds[3] <= b[3]
                and r["native_resolution_m"] <= need * MAX_UPSAMPLE):
            log(f"Reusing curated plate {r['id']} for the preview.")
            return {"id": r["id"], "root": tools.curated_root, "kind": "curated",
                    "grid_m": float(r["native_resolution_m"])}
    cov = read_coverage(tools, to_lonlat_bbox(bounds, epsg, pad_m=PLATE_PAD_M), env,
                        layers=COARSE_LAYERS_M if need >= COARSE_NEED_M else None)
    grid = choose_grid(need, cov)
    if grid["widen"]:
        raise PlateError("The terrain data here is too coarse even for a preview.")
    plate, _ = _build(order, tools, union, epsg, grid, env, log, cwd=cache_dir,
                      root=os.path.join(order.work_dir, "preview", "plate"),
                      rid="preview_" + order.id[len("order_"):])
    return plate


def _dump(path, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def preview(order_dir, tools, log=print, render=None, write_pdf=None) -> dict:
    """Frame every size, build one coarse plate, draw the offered sizes and write the
    PDF. `render` and `write_pdf` are for tests: stand-ins for the two slow steps."""
    from app.orderprep import PREP_VENV_HELP, _plan_grid, cache_env
    refuse_inside_repo(orders_root())
    order = load(order_dir)
    payloads = order.payloads()
    tracks_ll = lonlat_extent(payloads)["bbox"]
    if tracks_ll is None:
        raise OrderError(f"no track points in {order.in_dir}")
    if not conus_covered(tracks_ll):
        raise PlateError("These tracks are outside the lower 48 states.")
    if not os.path.exists(tools.prep_python):
        raise PlateError(f"The prep venv is missing: {tools.prep_python}. "
                         f"Set it up with {PREP_VENV_HELP}.")
    started = time.monotonic()
    epsg = preview_epsg(tracks_ll)
    bounds_m = project_bbox(tracks_ll, epsg)
    tracks = load_tracks_m(payloads, epsg)
    if not tracks:
        raise OrderError(f"no track points in {order.in_dir}")
    env, cache_dir = cache_env()

    def widen(cand, frame):
        return _plan_grid(tools, frame, epsg, cand.print_in[0], env)[0]

    entries = plan_sizes(bounds_m, [t.coords for t in tracks], widen=widen, forced=order.sizes)
    offered = [e for e in entries if e["offered"]]
    if not offered:
        raise PlateError("No size can be offered: " + "; ".join(
            f"{e['key']}: {e['why']}" for e in entries))
    log(f"Offering {', '.join(e['key'] for e in offered)}.")
    plate = _preview_plate(order, tools, union_frame(entries), epsg,
                           preview_need_m(entries), env, cache_dir, log)
    work = os.path.join(order.work_dir, "preview")
    (render or render_maps)(entries, tracks, os.path.join(plate["root"], plate["id"]),
                            order.title, work)
    pdf = os.path.join(order.dir, "out", "preview", f"{slugify(order.title)}-preview.pdf")
    if write_pdf is not None:
        write_pdf(pdf, entries, None, order.title)
    state = {"epsg": epsg, "plate": plate, "sizes": entries, "pdf": pdf,
             "seconds": round(time.monotonic() - started, 1)}
    _dump(os.path.join(work, "preview.json"), state)
    return state
