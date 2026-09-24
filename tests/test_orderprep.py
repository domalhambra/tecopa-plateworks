# tests/test_orderprep.py
# Prepare end to end with stub subprocesses (no network): the same trick as the
# stub region_prep in tests/test_regionbuild.py.
import json
import os
import sys

import pytest

from app import order as od
from app import orderplate as opl
from app import orderprep as op

LIDAR = {"1": 1.0, "3": 0.0, "10": 1.0, "30": 1.0, "60": 1.0}
NO_LIDAR = {"1": 0.0, "3": 0.0, "10": 1.0, "30": 1.0, "60": 1.0}
SMALL = (-116.21, 35.89, -116.17, 35.93)       # ~3.6 x 4.4 km near Tecopa
WIDE = (-116.4, 35.7, -116.0, 36.1)            # ~36 x 44 km

STUB_PREP = """
import argparse, json, os
ap = argparse.ArgumentParser()
for a in ("--id", "--name", "--epsg", "--resolution", "--out-root"):
    ap.add_argument(a, required=True)
ap.add_argument("--bbox", nargs=4, type=float, required=True)
a = ap.parse_args()
out = os.path.join(a.out_root, a.id)
os.makedirs(out, exist_ok=True)
json.dump({"id": a.id, "crs": "EPSG:" + a.epsg, "bbox": a.bbox,
           "native_resolution_m": float(a.resolution)},
          open(os.path.join(out, "region.json"), "w"))
with open(os.path.join(a.out_root, "builds.log"), "a") as f:
    f.write(a.id + "\\n")
print("cache=" + os.environ.get("HYRIVER_CACHE_NAME", ""))
"""
STUB_COVERAGE = 'import os\nprint(os.environ["STUB_COVERAGE"])\n'
STUB_LABELS = "import sys\nsys.exit(0)\n"
# Coverage that depends on the box it is asked about: past WIDE_DEG of longitude the
# 10 m layer stops covering the plate. Every box asked about is logged, so a test can
# see exactly which 4 numbers reached the coverage script.
WIDE_DEG = 0.2
STUB_EDGE_COVERAGE = """
import json, os, sys
w, s, e, n = map(float, sys.argv[1:5])
with open(os.environ["STUB_COVERAGE_LOG"], "a") as f:
    f.write(json.dumps([w, s, e, n]) + "\\n")
narrow = {"1": 0.0, "3": 0.0, "10": 1.0, "30": 1.0, "60": 1.0}
wide = {"1": 0.0, "3": 0.0, "10": 0.9, "30": 1.0, "60": 1.0}
print(json.dumps(wide if e - w > %r else narrow))
""" % WIDE_DEG


def _gpx(w, s, e, n):
    pts = "".join(f'<trkpt lat="{lat}" lon="{lon}"/>' for lon, lat in ((w, s), (e, n)))
    return ('<?xml version="1.0"?><gpx version="1.1" creator="t" '
            'xmlns="http://www.topografix.com/GPX/1/1"><trk><name>t</name>'
            f"<trkseg>{pts}</trkseg></trk></gpx>")


@pytest.fixture
def tools(tmp_path, monkeypatch):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in (("prep.py", STUB_PREP), ("coverage.py", STUB_COVERAGE),
                       ("labels.py", STUB_LABELS)):
        (stubs / name).write_text(body)
    (tmp_path / "curated").mkdir()
    monkeypatch.setenv("TECOPA_ORDERS_DIR", str(tmp_path / "orders"))
    monkeypatch.setenv("STUB_COVERAGE", json.dumps(LIDAR))
    return op.Tools(prep_python=sys.executable, prep_script=str(stubs / "prep.py"),
                    labels_script=str(stubs / "labels.py"),
                    coverage_script=str(stubs / "coverage.py"),
                    repo_root=str(tmp_path), curated_root=str(tmp_path / "curated"))


def _make_order(tmp_path, bbox=SMALL, size="12x18", title="Smith home ground"):
    d = tmp_path / "orders" / "2026-10-001-smith"
    (d / "in").mkdir(parents=True, exist_ok=True)
    (d / "in" / "trip.gpx").write_text(_gpx(*bbox))
    (d / "order.toml").write_text(f'title = "{title}"\nsize = "{size}"\n')
    return d


BIG_BOUNDS = [400000.0, 3800000.0, 700000.0, 4200000.0]


def _curated(tmp_path, dem_bounds=BIG_BOUNDS, synthetic=False, rid="big"):
    """A curated plate in EPSG:32611 with a real (tiny) GeoTIFF DEM. `synthetic` tags
    it the way tests/conftest.py tags its stand-ins."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_bounds
    rdir = tmp_path / "curated" / rid
    rdir.mkdir()
    json.dump({"crs": "EPSG:32611", "bounds": BIG_BOUNDS, "overview_size": [30, 40],
               "native_resolution_m": 10}, open(rdir / "region.json", "w"))
    w, s, e, n = dem_bounds
    with rasterio.open(rdir / "dem.tif", "w", driver="GTiff", dtype="float32", count=1,
                       width=30, height=40, crs="EPSG:32611", nodata=np.nan,
                       transform=from_bounds(w, s, e, n, 30, 40)) as ds:
        ds.write(np.full((40, 30), 900.0, dtype="float32"), 1)
        if synthetic:
            ds.update_tags(synthetic="1")
    return rdir


def _builds(d):
    log = d / "work" / "plate" / "builds.log"
    return log.read_text().split() if log.exists() else []


def _snapshot(folder):
    return {p.name: p.read_bytes() for p in folder.iterdir()}


def test_builds_a_lidar_plate(tmp_path, tools):
    d = _make_order(tmp_path)
    before = _snapshot(d / "in")
    lines = []
    state = op.prepare(str(d), tools, log=lines.append)
    plate = state["plate"]
    assert plate["kind"] == "built" and plate["id"] == "order_2026_10_001_smith"
    assert (plate["grid_m"], plate["layer_m"]) == (1.5, 1)
    region = json.load(open(d / "work" / "plate" / plate["id"] / "region.json"))
    assert region["native_resolution_m"] == 1.5
    assert f"cache={os.path.abspath(od.cache_path())}" in lines
    assert state["fill"] == pytest.approx(opl.NESTLE_FILL, abs=0.01)
    assert _snapshot(d / "in") == before
    report = (d / "work" / "report.txt").read_text()
    assert "Plate: order_2026_10_001_smith (built), 1.5 m grid" in report
    assert state["frame_from_manual"] is None


def test_no_lidar_widens_the_frame(tmp_path, tools, monkeypatch):
    monkeypatch.setenv("STUB_COVERAGE", json.dumps(NO_LIDAR))
    d = _make_order(tmp_path)
    state = op.prepare(str(d), tools, log=lambda s: None)
    frame = state["frame"]
    assert frame[2] - frame[0] == pytest.approx(18000.0, rel=1e-3)
    assert state["plate"]["grid_m"] == 10.0
    assert state["plate"]["upsample"] <= opl.MAX_UPSAMPLE
    assert any("widened" in w for w in state["warnings"])
    assert any("smaller print" in w for w in state["warnings"])


def test_widening_steps_to_a_coarser_layer_at_a_coverage_edge(tmp_path, tools,
                                                               monkeypatch):
    edge = tmp_path / "stubs" / "edge_coverage.py"
    edge.write_text(STUB_EDGE_COVERAGE)
    asked = tmp_path / "coverage_asks.jsonl"
    monkeypatch.setenv("STUB_COVERAGE_LOG", str(asked))
    tools = op.Tools(**{**tools.__dict__, "coverage_script": str(edge)})
    d = _make_order(tmp_path)
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert state["plate"]["grid_m"] == 30.0
    assert state["plate"]["upsample"] <= opl.MAX_UPSAMPLE
    frame = state["frame"]
    assert frame[2] - frame[0] == pytest.approx(54000.0, rel=1e-3)
    # the warning names the layer that first forced the widening
    assert any("10 m data" in w for w in state["warnings"])
    boxes = [json.loads(l) for l in asked.read_text().splitlines()]
    assert len(boxes) == 3
    assert boxes[0][2] - boxes[0][0] < WIDE_DEG < boxes[1][2] - boxes[1][0]
    # the coverage script sees the padded box the build fetches
    want = opl.to_lonlat_bbox(opl.plate_bounds(frame), state["epsg"],
                              pad_m=opl.PLATE_PAD_M)
    assert boxes[-1] == pytest.approx(list(want))
    built = json.load(open(d / "work" / "plate" / state["plate"]["id"] / "region.json"))
    assert built["bbox"] == pytest.approx(list(want))


def test_a_widening_that_does_not_grow_the_frame_refuses(tmp_path, tools, monkeypatch):
    monkeypatch.setenv("STUB_COVERAGE", json.dumps(NO_LIDAR))
    monkeypatch.setattr(op, "widen_for_upsample", lambda frame, layer, w: tuple(frame))
    d = _make_order(tmp_path)
    with pytest.raises(opl.PlateError, match="did not grow"):
        op.prepare(str(d), tools, log=lambda s: None)


def test_second_prepare_builds_nothing(tmp_path, tools):
    d = _make_order(tmp_path)
    op.prepare(str(d), tools, log=lambda s: None)
    lines = []
    op.prepare(str(d), tools, log=lines.append)
    assert len(_builds(d)) == 1
    assert any("Plate is current" in l for l in lines)


def test_current_plate_still_rewrites_the_report(tmp_path, tools):
    d = _make_order(tmp_path)
    op.prepare(str(d), tools, log=lambda s: None)
    (d / "work" / "report.txt").unlink()
    _make_order(tmp_path, title="Smith family ground")
    lines = []
    op.prepare(str(d), tools, log=lines.append)
    assert any("Plate is current" in l for l in lines)
    assert len(_builds(d)) == 1
    assert "Order: Smith family ground" in (d / "work" / "report.txt").read_text()


def test_relative_orders_root_gives_the_build_an_absolute_cache(tmp_path, tools,
                                                                monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TECOPA_ORDERS_DIR", "orders")
    d = _make_order(tmp_path)
    lines = []
    op.prepare(str(d), tools, log=lines.append)
    cache = [l for l in lines if l.startswith("cache=")]
    assert cache == ["cache=" + str(tmp_path / "orders" / "_cache" / "aiohttp_cache.sqlite")]


def test_missing_prep_venv_is_a_plate_error(tmp_path, tools):
    tools = op.Tools(**{**tools.__dict__,
                        "prep_python": str(tmp_path / "no-venv" / "bin" / "python")})
    d = _make_order(tmp_path)
    with pytest.raises(opl.PlateError, match="The prep venv is missing: .*no-venv"):
        op.prepare(str(d), tools, log=lambda s: None)
    assert not (d / "work" / "plate").exists()


def test_curated_reuse_needs_no_prep_venv(tmp_path, tools):
    _curated(tmp_path)
    tools = op.Tools(**{**tools.__dict__,
                        "prep_python": str(tmp_path / "no-venv" / "bin" / "python")})
    d = _make_order(tmp_path, bbox=WIDE)
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert state["plate"]["kind"] == "curated"


def test_default_tools_honour_tecopa_prep_python(tmp_path, monkeypatch):
    monkeypatch.delenv("TECOPA_PREP_PYTHON", raising=False)
    assert op.default_tools("/repo").prep_python == "/repo/.venv-prep/bin/python"
    monkeypatch.setenv("TECOPA_PREP_PYTHON", "/opt/prep/bin/python")
    assert op.default_tools("/repo").prep_python == "/opt/prep/bin/python"
    monkeypatch.setenv("TECOPA_PREP_PYTHON", "venvs/prep/bin/python")
    assert op.default_tools("/repo").prep_python == "/repo/venvs/prep/bin/python"


def test_changed_size_rebuilds_once(tmp_path, tools):
    d = _make_order(tmp_path)
    op.prepare(str(d), tools, log=lambda s: None)
    _make_order(tmp_path, size="8x10")
    op.prepare(str(d), tools, log=lambda s: None)
    op.prepare(str(d), tools, log=lambda s: None)
    assert len(_builds(d)) == 2


def test_manual_frame_is_kept(tmp_path, tools):
    d = _make_order(tmp_path)
    first = op.prepare(str(d), tools, log=lambda s: None)
    f = first["frame"]
    manual = [f[0] - 2000.0, f[1] - 3000.0, f[2] + 2000.0, f[3] + 3000.0]
    od.set_manual(od.load(str(d)), "frame", manual)
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert state["frame"] == pytest.approx(manual)
    assert state["manual"]["frame"] == manual
    op.prepare(str(d), tools, log=lambda s: None)
    assert len(_builds(d)) == 2


def test_widened_manual_frame_stays_current(tmp_path, tools, monkeypatch):
    monkeypatch.setenv("STUB_COVERAGE", json.dumps(NO_LIDAR))
    d = _make_order(tmp_path)
    epsg = opl.order_epsg(SMALL, 12 / 18)
    small = [float(v) for v in opl.nestled_frame(opl.project_bbox(SMALL, epsg), 12 / 18)]
    od.set_manual(od.load(str(d)), "frame", small)
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert state["frame"][2] - state["frame"][0] == pytest.approx(18000.0, rel=1e-3)
    assert state["manual"]["frame"] == small
    assert state["frame_from_manual"] == small
    lines = []
    op.prepare(str(d), tools, log=lines.append)
    assert any("Plate is current" in l for l in lines)
    assert len(_builds(d)) == 1


def test_cli_reports_a_corrupt_state(tmp_path, tools, capsys):
    from scripts import order as order_cli
    d = _make_order(tmp_path)
    (d / "work").mkdir()
    (d / "work" / "state.json").write_text("{not json")
    assert order_cli.main(["prepare", str(d)]) == 1
    assert "prepare stopped: work/state.json is not readable" in capsys.readouterr().err


def test_reuses_a_curated_plate(tmp_path, tools):
    _curated(tmp_path)
    d = _make_order(tmp_path, bbox=WIDE)
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert state["plate"]["kind"] == "curated" and state["plate"]["id"] == "big"
    assert _builds(d) == []
    lines = []
    op.prepare(str(d), tools, log=lines.append)
    assert any("Plate is current" in l for l in lines)


def test_synthetic_curated_plate_is_not_reused(tmp_path, tools):
    _curated(tmp_path, synthetic=True)
    d = _make_order(tmp_path, bbox=WIDE)
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert state["plate"]["kind"] == "built"


def test_curated_plate_whose_dem_misses_its_bounds_is_not_reused(tmp_path, tools):
    shifted = [b + 50000.0 for b in BIG_BOUNDS]
    _curated(tmp_path, dem_bounds=shifted)
    d = _make_order(tmp_path, bbox=WIDE)
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert state["plate"]["kind"] == "built"


def test_a_curated_plate_that_turns_synthetic_is_rebuilt(tmp_path, tools):
    import rasterio
    rdir = _curated(tmp_path)
    d = _make_order(tmp_path, bbox=WIDE)
    assert op.prepare(str(d), tools, log=lambda s: None)["plate"]["kind"] == "curated"
    with rasterio.open(rdir / "dem.tif", "r+") as ds:
        ds.update_tags(synthetic="1")
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert state["plate"]["kind"] == "built"


def test_curated_plate_without_a_dem_is_not_reused(tmp_path, tools):
    big = tmp_path / "curated" / "big"
    big.mkdir()
    json.dump({"crs": "EPSG:32611", "bounds": [400000.0, 3800000.0, 700000.0, 4200000.0],
               "native_resolution_m": 10}, open(big / "region.json", "w"))
    d = _make_order(tmp_path, bbox=WIDE)
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert state["plate"]["kind"] == "built"


def test_outside_the_lower_48(tmp_path, tools):
    d = _make_order(tmp_path, bbox=(-150.1, 61.1, -149.9, 61.2))
    with pytest.raises(opl.PlateError, match="lower 48"):
        op.prepare(str(d), tools, log=lambda s: None)


def test_coverage_failure_is_a_plate_error(tmp_path, tools):
    bad = tmp_path / "stubs" / "bad_coverage.py"
    bad.write_text('import sys\nsys.exit("boom")\n')
    tools = op.Tools(**{**tools.__dict__, "coverage_script": str(bad)})
    d = _make_order(tmp_path)
    with pytest.raises(opl.PlateError, match="coverage"):
        op.prepare(str(d), tools, log=lambda s: None)


def test_failed_build_keeps_the_log(tmp_path, tools):
    bad = tmp_path / "stubs" / "bad_prep.py"
    bad.write_text("import os, sys\n"
                   "a = sys.argv\n"
                   "os.makedirs(os.path.join(a[a.index('--out-root') + 1],"
                   " a[a.index('--id') + 1]))\n"
                   'print("Fetching 3DEP DEM...")\nsys.exit(3)\n')
    tools = op.Tools(**{**tools.__dict__, "prep_script": str(bad)})
    d = _make_order(tmp_path)
    with pytest.raises(RuntimeError, match="exit 3"):
        op.prepare(str(d), tools, log=lambda s: None)
    assert "Fetching 3DEP DEM" in (d / "work" / "build.log").read_text()
    assert not (d / "work" / "plate" / "order_2026_10_001_smith").exists()


def test_cli_reports_a_missing_order(tmp_path, capsys):
    from scripts import order as order_cli
    assert order_cli.main(["prepare", str(tmp_path / "nope")]) == 1
    assert "no order.toml" in capsys.readouterr().err


def test_cli_prepares_an_order(tmp_path, tools, capsys):
    from scripts import order as order_cli
    d = _make_order(tmp_path)
    assert order_cli.main(["prepare", str(d)], tools=tools) == 0
    out = capsys.readouterr().out
    assert "Plate: order_2026_10_001_smith (built), 1.5 m grid" in out
