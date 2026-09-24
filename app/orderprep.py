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
from app.regions import Region

# One pass per 3DEP layer (region_prep.COVERAGE_LAYERS_M: 1, 3, 10, 30, 60). That
# module needs the prep stack, so it is counted here, not imported (invariant 13).
MAX_PLAN_PASSES = 5
# At a need of COARSE_NEED_M or more, only the 10, 30 and 60 m layers can shape the
# grid: the fine layers matter just above 10 m, through choose_grid's step-down
# when the 10 m layer is uncovered, and not past 20 m. Asking for 1 m lidar over a
# corridor-sized box times out (acceptance, Reno to Salt Lake).
COARSE_NEED_M = 20.0
COARSE_LAYERS_M = (10, 30, 60)
# A built plate is complete only with all three. Land cover is optional to
# region_prep (the in-app build carries on without it), but a customer plate must
# not quietly lose the biome look. Hydro with no lakes or rivers is real (desert).
BUILT_PLATE_FILES = ("region.json", "dem.tif", "landcover.tif")
LANDCOVER_WARNING = ("Land cover did not download, so the biome look is not "
                     "available on this plate. Run Prepare again to retry.")
PREP_VENV_HELP = "docs/changing-things.md › Set up a machine"


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
    """The real tools. TECOPA_PREP_PYTHON, TECOPA_PREP_SCRIPT and TECOPA_LABELS_SCRIPT
    move them, with app/main.py's names and defaults. main.py's paths are relative to
    the server's cwd, the repo root; here a relative path is joined to `repo_root`."""
    def env_path(var, default):
        return os.path.join(repo_root, os.environ.get(var, default))
    return Tools(prep_python=env_path("TECOPA_PREP_PYTHON", ".venv-prep/bin/python"),
                 prep_script=env_path("TECOPA_PREP_SCRIPT", "region_prep.py"),
                 labels_script=env_path("TECOPA_LABELS_SCRIPT", "scripts/build_labels.py"),
                 coverage_script=os.path.join(repo_root, "scripts", "dem_coverage.py"),
                 repo_root=repo_root,
                 curated_root=os.path.join(repo_root, "regions"))


def _real_terrain(root: str, rid: str):
    """The plate's Region if its DEM is ready (present, bounds and CRS matching
    region.json) and real, else None. A customer must never get invented terrain:
    tests/conftest.py hydrates synthetic stand-ins into a checkout missing its real
    DEMs, marked with the GeoTIFF tag synthetic=1, and a stand-in reads as ready."""
    try:
        region = Region(rid, root)
        if not region.readiness().get("ready"):
            return None
        import rasterio
        dem = os.path.join(region.dir, region.cfg.get("dem_path", "dem.tif"))
        with rasterio.open(dem) as ds:
            if ds.tags().get("synthetic") == "1":   # tests/conftest.py's mark
                return None
    except Exception:            # a malformed region.json or an unreadable DEM
        return None
    return region


def curated_regions(root: str) -> list:
    """Curated plates with real, ready terrain, as the dicts curated_fit reads."""
    out = []
    if not os.path.isdir(root):
        return out
    for rid in sorted(os.listdir(root)):
        if not os.path.isfile(os.path.join(root, rid, "region.json")):
            continue
        region = _real_terrain(root, rid)
        if region is None:
            continue
        cfg = region.cfg
        out.append({"id": rid, "crs": cfg["crs"], "bounds": cfg["bounds"],
                    "native_resolution_m": cfg["native_resolution_m"]})
    return out


def read_coverage(tools: Tools, bbox, env, layers=None) -> dict:
    """{layer metres: covered share}, for `layers` only when given. choose_grid
    reads a layer left out as uncovered."""
    cmd = [tools.prep_python, tools.coverage_script, *map(str, bbox)]
    if layers:
        cmd += ["--layers", ",".join(str(r) for r in layers)]
    run = subprocess.run(cmd, cwd=tools.repo_root, capture_output=True, text=True,
                         env=env)
    if run.returncode != 0:
        raise PlateError("The 3DEP coverage check failed:\n" + run.stderr[-800:])
    try:
        raw = json.loads(run.stdout.strip().splitlines()[-1])
        return {int(k): float(v) for k, v in raw.items()}
    except (ValueError, IndexError) as ex:
        raise PlateError(f"The 3DEP coverage check printed no result: {ex}") from ex


def _plate_present(plate) -> bool:
    if not plate:
        return False
    if plate.get("kind") == "curated":
        return _real_terrain(plate["root"], plate["id"]) is not None
    return _built_complete(plate["root"], plate["id"])


def _built_complete(root, rid) -> bool:
    """A built plate is current only with every BUILT_PLATE_FILES file, so one that
    lost its land cover is rebuilt by the next Prepare."""
    return all(os.path.isfile(os.path.join(root, rid, name))
               for name in BUILT_PLATE_FILES)


def _plan_grid(tools, frame, epsg, print_w_in, env):
    """The grid for the frame, widening the frame until the data holds it.

    Coverage is read again for each widened plate, which covers more ground. At a
    coverage edge the wider plate can lose a layer, and the next coarser layer then
    asks for another widening (the spec's Errors table). Each widening moves to a
    coarser layer, so one pass per layer is enough. Returns the frame, the grid and
    the layer that first forced a widening (None if none did): the warning names
    that one, since a finer layer can come back into cover on the larger plate."""
    forced_by = None
    for _ in range(MAX_PLAN_PASSES):
        need = needed_resolution(frame, print_w_in)
        cov = read_coverage(tools, to_lonlat_bbox(plate_bounds(frame), epsg,
                                                  pad_m=PLATE_PAD_M), env,
                            layers=COARSE_LAYERS_M if need >= COARSE_NEED_M else None)
        grid = choose_grid(need, cov)
        if not grid["widen"]:
            return frame, grid, forced_by
        if forced_by is None:
            forced_by = grid["layer_m"]
        wider = widen_for_upsample(frame, grid["layer_m"], print_w_in)
        if wider[2] - wider[0] <= frame[2] - frame[0]:
            raise PlateError(f"The frame did not grow when widened for the "
                             f"{grid['layer_m']:g} m layer, so the terrain data "
                             f"stays too coarse for this print size.")
        frame = wider
    raise PlateError("The terrain data is still too coarse for this print size "
                     f"after {MAX_PLAN_PASSES} widenings.")


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
    # A manual frame is current when it is the one the last plan started from. It is
    # not compared with state["frame"]: planning may have widened it for coarse data.
    frame_current = ("frame" not in manual
                     or list(manual["frame"]) == state.get("frame_from_manual"))
    if (state.get("inputs_hash") == inputs and frame_current
            and _plate_present(state.get("plate"))):
        log(f"Plate is current: {state['plate']['id']}. Nothing to build.")
        write_report(order, state)   # the title may have changed; it is not an input
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
        # after the curated check: reusing a curated plate needs no prep venv
        if not os.path.exists(tools.prep_python):
            raise PlateError(f"The prep venv is missing: {tools.prep_python}. "
                             f"Set it up with {PREP_VENV_HELP}.")
        if "frame" in manual:
            epsg = state.get("epsg") or order_epsg(tracks, pw / ph)
            planned = tuple(manual["frame"])
        else:
            epsg = order_epsg(tracks, pw / ph)
            planned = nestled_frame(project_bbox(tracks, epsg), pw / ph)
        # absolute: a relative TECOPA_ORDERS_DIR would resolve against the
        # subprocess's cwd (the repo root), not ours
        cache = os.path.abspath(cache_path())
        env = dict(os.environ, HYRIVER_CACHE_NAME=cache)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        frame, grid, forced_by = _plan_grid(tools, planned, epsg, pw, env)
        if forced_by is not None:
            fill = track_fill(project_bbox(tracks, epsg), frame)
            note = (f"The terrain here is {forced_by:g} m data, too coarse for a "
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
        if not os.path.isfile(os.path.join(plate["root"], plate["id"], "landcover.tif")):
            warnings.append(LANDCOVER_WARNING)

    track_m = project_bbox(tracks, epsg)
    state = write_state(order, {
        "inputs_hash": inputs, "epsg": epsg, "print_in": [pw, ph],
        "frame": list(frame), "track_bounds_m": list(track_m),
        "frame_from_manual": list(manual["frame"]) if "frame" in manual else None,
        "fill": round(track_fill(track_m, frame), 3),
        "need_m": round(needed_resolution(frame, pw), 3),
        "plate": plate, "warnings": warnings})
    write_report(order, state)
    return state


def _build(order, tools, frame, epsg, grid, env, log):
    """Build the order's plate under work/plate/<order id>/. region.json keeps the
    name as it was at build time, and a title change does not rebuild the plate, so
    later steps must take the title from order.title, never from region.json."""
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
