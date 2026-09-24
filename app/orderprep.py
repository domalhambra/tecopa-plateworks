# app/orderprep.py
"""Prepare, step 1 of an order (order pipeline spec, section 2). Sub-project 1 ships
the plate: read the tracks, frame them nestled, reuse a curated plate that already
holds the print, or build one under work/plate/. Writes work/state.json and
work/report.txt. Later sub-projects add the paper table, photos and the proof.

The fetch stack runs only as .venv-prep subprocesses (invariant 13): the coverage
query (scripts/dem_coverage.py) and the build (region_prep.py and
scripts/build_labels.py, through regionbuild.run_build). Tests swap in stubs."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass

from app.ingest import lonlat_extent
from app.order import OrderError, cache_path, load, read_state, write_state
from app.orderplate import (FILL_WARN, MAX_UPSAMPLE, PLATE_PAD_M, PlateError,
                            choose_grid, conus_covered, curated_fit, needed_resolution,
                            nestled_frame, order_epsg, plate_bounds, project_bbox,
                            to_lonlat_bbox, track_fill, widen_for_upsample)
from app.regionbuild import run_build


@dataclass(frozen=True)
class Tools:
    """The subprocesses Prepare calls, and where the curated plates live."""
    prep_python: str
    prep_script: str
    labels_script: str
    coverage_script: str
    repo_root: str
    curated_root: str


def default_tools(repo_root: str) -> Tools:
    return Tools(prep_python=os.path.join(repo_root, ".venv-prep", "bin", "python"),
                 prep_script=os.path.join(repo_root, "region_prep.py"),
                 labels_script=os.path.join(repo_root, "scripts", "build_labels.py"),
                 coverage_script=os.path.join(repo_root, "scripts", "dem_coverage.py"),
                 repo_root=repo_root,
                 curated_root=os.path.join(repo_root, "regions"))


def curated_regions(root: str) -> list:
    """Curated plates with a DEM on disk, as the dicts curated_fit reads."""
    out = []
    if not os.path.isdir(root):
        return out
    for rid in sorted(os.listdir(root)):
        path = os.path.join(root, rid, "region.json")
        if not os.path.isfile(path):
            continue
        with open(path) as f:
            cfg = json.load(f)
        if not os.path.exists(os.path.join(root, rid, cfg.get("dem_path", "dem.tif"))):
            continue
        out.append({"id": rid, "crs": cfg["crs"], "bounds": cfg["bounds"],
                    "native_resolution_m": cfg["native_resolution_m"]})
    return out


def read_coverage(tools: Tools, bbox, env) -> dict:
    run = subprocess.run([tools.prep_python, tools.coverage_script, *map(str, bbox)],
                         cwd=tools.repo_root, capture_output=True, text=True, env=env)
    if run.returncode != 0:
        raise PlateError("The 3DEP coverage check failed:\n" + run.stderr[-800:])
    try:
        raw = json.loads(run.stdout.strip().splitlines()[-1])
        return {int(k): float(v) for k, v in raw.items()}
    except (ValueError, IndexError) as ex:
        raise PlateError(f"The 3DEP coverage check printed no result: {ex}") from ex


def _plate_present(plate) -> bool:
    return bool(plate) and os.path.isfile(
        os.path.join(plate["root"], plate["id"], "region.json"))


def _plan_grid(tools, frame, epsg, print_w_in, env):
    """The grid for the frame, widening the frame once if the data is too coarse.
    Coverage is read again for the widened plate, which covers more ground."""
    for _ in range(2):
        cov = read_coverage(tools, to_lonlat_bbox(plate_bounds(frame), epsg,
                                                  pad_m=PLATE_PAD_M), env)
        grid = choose_grid(needed_resolution(frame, print_w_in), cov)
        if not grid["widen"]:
            return frame, grid
        frame = widen_for_upsample(frame, grid["layer_m"], print_w_in)
    raise PlateError("The terrain data is still too coarse for this print size "
                     "after the frame was widened.")


def prepare(order_dir: str, tools: Tools, log=print) -> dict:
    order = load(order_dir)
    tracks = lonlat_extent(order.payloads())["bbox"]
    if tracks is None:
        raise OrderError(f"no track points in {order.in_dir}")
    if not conus_covered(tracks):
        raise PlateError("These tracks are outside the lower 48. "
                         "Alaska and Hawaii come later.")
    state = read_state(order)
    manual = state.get("manual", {})
    inputs = order.inputs_hash()
    frame_current = ("frame" not in manual
                     or list(manual["frame"]) == list(state.get("frame", [])))
    if (state.get("inputs_hash") == inputs and frame_current
            and _plate_present(state.get("plate"))):
        log(f"Plate is current: {state['plate']['id']}. Nothing to build.")
        return state

    pw, ph = order.print_in()
    warnings = []
    fit = None if "frame" in manual else curated_fit(
        tracks, pw / ph, pw, curated_regions(tools.curated_root))
    if fit:
        epsg, frame = fit["epsg"], fit["frame"]
        region = fit["region"]
        plate = {"id": region["id"], "root": tools.curated_root, "kind": "curated",
                 "grid_m": float(region["native_resolution_m"]), "upsample": 1.0}
        log(f"Reusing curated plate {region['id']}.")
    else:
        if "frame" in manual:
            epsg = state.get("epsg") or order_epsg(tracks, pw / ph)
            planned = tuple(manual["frame"])
        else:
            epsg = order_epsg(tracks, pw / ph)
            planned = nestled_frame(project_bbox(tracks, epsg), pw / ph)
        env = dict(os.environ, HYRIVER_CACHE_NAME=cache_path())
        os.makedirs(os.path.dirname(cache_path()), exist_ok=True)
        frame, grid = _plan_grid(tools, planned, epsg, pw, env)
        if frame != planned:
            fill = track_fill(project_bbox(tracks, epsg), frame)
            note = (f"The terrain here is {grid['layer_m']:g} m data, too coarse for a "
                    f"nestled {pw:g}x{ph:g}. The frame was widened, and the tracks now "
                    f"fill {fill:.0%} of it.")
            if fill < FILL_WARN:
                note += " A smaller print would keep them nestled."
            warnings.append(note)
        if grid["upsample"] > 1.0:
            warnings.append(f"Terrain is upsampled {grid['upsample']:.2f}x "
                            f"(the limit is {MAX_UPSAMPLE:g}x).")
        plate, labels_note = _build(order, tools, frame, epsg, grid, env, log)
        if labels_note:
            warnings.append(labels_note)

    track_m = project_bbox(tracks, epsg)
    state = write_state(order, {
        "inputs_hash": inputs, "epsg": epsg, "print_in": [pw, ph],
        "frame": list(frame), "track_bounds_m": list(track_m),
        "fill": round(track_fill(track_m, frame), 3),
        "need_m": round(needed_resolution(frame, pw), 3),
        "plate": plate, "warnings": warnings})
    write_report(order, state)
    return state


def _build(order, tools, frame, epsg, grid, env, log):
    rid = order.id
    params = {"id": rid, "name": order.title,
              "bbox": to_lonlat_bbox(plate_bounds(frame), epsg, pad_m=PLATE_PAD_M),
              "epsg": epsg, "resolution": grid["grid_m"],
              "out_root": order.plate_root}
    os.makedirs(order.plate_root, exist_ok=True)
    shutil.rmtree(os.path.join(order.plate_root, rid), ignore_errors=True)
    log(f"Building plate {rid}: {grid['grid_m']:g} m grid from the "
        f"{grid['layer_m']:g} m 3DEP layer.")
    started = time.monotonic()
    # work/build.log keeps every line of the build, so a failure can be read after
    # run_build sweeps the partial plate.
    with open(os.path.join(order.work_dir, "build.log"), "w") as build_log:
        def progress(line):
            build_log.write(line + "\n")
            log(line)
        result = run_build(params, repo_root=tools.repo_root,
                           regions_root=order.plate_root,
                           prep_python=tools.prep_python, prep_script=tools.prep_script,
                           labels_script=tools.labels_script, set_progress=progress,
                           env=env)
    plate = {"id": rid, "root": order.plate_root, "kind": "built",
             "grid_m": grid["grid_m"], "layer_m": grid["layer_m"],
             "upsample": round(grid["upsample"], 3),
             "build_seconds": round(time.monotonic() - started, 1)}
    return plate, result["labels_note"]


def write_report(order, state) -> str:
    plate, frame = state["plate"], state["frame"]
    grid = f"{plate['grid_m']:g} m grid"
    if plate.get("layer_m") is not None:
        grid += f" from the {plate['layer_m']:g} m 3DEP layer"
    lines = [f"Order: {order.title}",
             f"Print: {state['print_in'][0]:g} x {state['print_in'][1]:g} in",
             f"Plate: {plate['id']} ({plate['kind']}), {grid}",
             f"Frame: {(frame[2] - frame[0]) / 1000:.1f} x "
             f"{(frame[3] - frame[1]) / 1000:.1f} km, tracks fill {state['fill']:.0%}",
             f"Upsampling: {plate['upsample']:.2f}x (limit {MAX_UPSAMPLE:g}x)"]
    if plate.get("build_seconds") is not None:
        lines.append(f"Build time: {plate['build_seconds']:.0f} s")
    if state["warnings"]:
        lines.append("Warnings:")
        lines += [f"- {w}" for w in state["warnings"]]
    else:
        lines.append("Warnings: none")
    text = "\n".join(lines) + "\n"
    with open(os.path.join(order.work_dir, "report.txt"), "w") as f:
        f.write(text)
    return text
