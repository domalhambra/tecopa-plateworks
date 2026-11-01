# The marketing farm renders with the look a customer's poster carries by default
# (orderspec.ORDER_LOOK), so the page shows what an order ships. A plate may override
# one field of the look; the rest stays the customer's.
import json
import os
import shutil

from conftest import synthetic_region
from app import render
from app.orderspec import ORDER_LOOK
from app.regions import Region
from scripts.render_asset_farm import _base_spec


def _region(rid="lassen_ca"):
    plate = synthetic_region(rid)
    return Region(rid, root=os.path.dirname(plate))


def test_farm_renders_the_order_look():
    spec = _base_spec(_region(), [], [])
    for k, v in ORDER_LOOK.items():
        assert getattr(spec, k) == v


def test_a_plate_look_overrides_one_field_only():
    spec = _base_spec(_region(), [], [], look={"haze_strength": 0.4})
    assert spec.haze_strength == 0.4
    assert spec.soft_light == ORDER_LOOK["soft_light"]
    assert spec.biome is True


def test_full_look_renders_on_a_plate_with_no_landcover_labels_or_playa(tmp_path):
    src = synthetic_region("lassen_ca")
    with open(os.path.join(src, "region.json")) as f:
        cfg = json.load(f)
    dst = tmp_path / "bare_plate"
    dst.mkdir()
    shutil.copy(os.path.join(src, "region.json"), dst / "region.json")
    dem = cfg.get("dem_path", "dem.tif")
    shutil.copy(os.path.join(src, dem), dst / dem)
    assert sorted(os.listdir(dst)) == sorted(["region.json", dem])
    region = Region("bare_plate", root=str(tmp_path))
    spec = _base_spec(region, [], [])
    img = render.rasterize(spec, dpi=40, region_dir=region.dir, watermark=False,
                           cfg=region.cfg)
    assert img.size[0] > 0 and img.size[1] > 0
