# tests/test_orderpreview_render.py
# The preview's real map painter, once, on the synthetic lassen_ca plate. The stub
# plates of tests/test_orderpreview.py cannot be rendered.
import json
import os

import numpy as np
from PIL import Image

from app import orderpreview as opv
from app import panels
from app.ingest import Track
from tests.conftest import synthetic_region

REGION_DIR = synthetic_region("lassen_ca")


def _tracks():
    b = json.load(open(os.path.join(REGION_DIR, "region.json")))["bounds"]
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    coords = np.array([[cx - 15000.0, cy - 2000.0], [cx, cy + 2000.0], [cx + 15000.0, cy - 2000.0]])
    return [Track("t-0", coords, "2024-06-01")]


def test_each_offered_size_is_drawn_at_screen_size_with_its_gaps(tmp_path, monkeypatch):
    from app import render
    real, words = render.rasterize, []

    def spy(spec, **kw):                    # the real painter, and what it was asked for
        words.append((kw.get("watermark"), kw.get("watermark_text")))
        return real(spec, **kw)
    monkeypatch.setattr(render, "rasterize", spy)
    tracks = _tracks()
    pts = tracks[0].coords
    bounds = (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())
    entries = opv.plan_sizes(bounds, [t.coords for t in tracks])
    by_key = {e["key"]: e for e in entries}
    assert by_key["three"]["offered"] and by_key["three"]["orientation"] == "landscape"
    opv.render_maps(entries, tracks, REGION_DIR, "Lassen walk", str(tmp_path))
    for e in entries:
        if not e["offered"]:
            assert "image" not in e
            continue
        img = Image.open(e["image"])
        w_in, h_in = e["print_in"]
        if e["panels"] == 1:
            assert max(img.size) == 1600
        else:
            assert img.size == (round(w_in * 50), round(h_in * 50))
        assert abs(img.size[0] / img.size[1] - w_in / h_in) < 0.01
    three = np.asarray(Image.open(by_key["three"]["image"]).convert("RGB"))
    assert three.shape == (850, 3500, 3)
    assert (three[:, 1100:1200] == panels.WALL_TONE).all()      # 22 in, then a 2 in strip
    assert (three[:, 2300:2400] == panels.WALL_TONE).all()      # and the second strip
    assert not (three[:, 1000:1100] == panels.WALL_TONE).all()
    assert not (three[:, 2400:2500] == panels.WALL_TONE).all()
    assert words == [(True, "PREVIEW")] * 4                     # every map says PREVIEW
    plain = np.asarray(Image.open(by_key["17x22"]["image"]).convert("RGB"))
    assert len(np.unique(plain.reshape(-1, 3), axis=0)) > 500   # a real picture, not a flat fill
