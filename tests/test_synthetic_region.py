"""synthetic_region: a test that asserts on synthetic terrain must construct it.
Seven render tests read regions/lassen_ca directly. conftest only hydrates a DEM
that is missing, so on a machine with real 3DEP data they ran on real terrain and
failed thresholds tuned to the synthetic surface (misread for weeks as a Georgia
font-metric gap). The mirror gives them CI's condition on every host."""
import json
import os

from conftest import dem_is_synthetic, synthetic_region


def test_the_mirror_carries_a_synthetic_dem_and_the_real_plate_files():
    rd = synthetic_region("lassen_ca")
    cfg = json.load(open(os.path.join(rd, "region.json")))
    assert os.path.basename(rd) == "lassen_ca"
    assert dem_is_synthetic(os.path.join(rd, cfg.get("dem_path", "dem.tif")))
    for name in ("region.json", "labels.json", "hydro.json", "sources.json"):
        assert (open(os.path.join(rd, name), "rb").read()
                == open(os.path.join("regions/lassen_ca", name), "rb").read())


def test_the_mirror_is_built_once_per_process():
    assert synthetic_region("lassen_ca") == synthetic_region("lassen_ca")
