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


def _make_order(tmp_path, bbox=SMALL, size="12x18"):
    d = tmp_path / "orders" / "2026-10-001-smith"
    (d / "in").mkdir(parents=True, exist_ok=True)
    (d / "in" / "trip.gpx").write_text(_gpx(*bbox))
    (d / "order.toml").write_text(f'title = "Smith home ground"\nsize = "{size}"\n')
    return d


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
    assert f"cache={od.cache_path()}" in lines
    assert state["fill"] == pytest.approx(opl.NESTLE_FILL, abs=0.01)
    assert _snapshot(d / "in") == before
    report = (d / "work" / "report.txt").read_text()
    assert "Plate: order_2026_10_001_smith (built), 1.5 m grid" in report


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


def test_second_prepare_builds_nothing(tmp_path, tools):
    d = _make_order(tmp_path)
    op.prepare(str(d), tools, log=lambda s: None)
    lines = []
    op.prepare(str(d), tools, log=lines.append)
    assert len(_builds(d)) == 1
    assert any("Plate is current" in l for l in lines)


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


def test_reuses_a_curated_plate(tmp_path, tools):
    big = tmp_path / "curated" / "big"
    big.mkdir()
    json.dump({"crs": "EPSG:32611", "bounds": [400000.0, 3800000.0, 700000.0, 4200000.0],
               "native_resolution_m": 10}, open(big / "region.json", "w"))
    (big / "dem.tif").write_bytes(b"")
    d = _make_order(tmp_path, bbox=WIDE)
    state = op.prepare(str(d), tools, log=lambda s: None)
    assert state["plate"]["kind"] == "curated" and state["plate"]["id"] == "big"
    assert _builds(d) == []


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
    bad.write_text('import sys\nprint("Fetching 3DEP DEM...")\nsys.exit(3)\n')
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
