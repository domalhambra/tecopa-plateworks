# The farm frames the whole region as the poster -- but a corridor-scale plate's
# UTM rectangle can bulge past its 4326 fetch bbox, leaving nodata strips along the
# frame edges (elko_bonneville: ~4%, north and south). The engine's off-DEM guard
# rightly refuses to fabricate that terrain, so the FARM must frame the renderable
# region: full bounds shrunk to the DEM's finite-data envelope. Full-coverage plates
# must come through byte-identical -- their frame is their bounds.
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds

from scripts.render_asset_farm import _frame

BOUNDS = (500_000.0, 4_400_000.0, 530_000.0, 4_420_000.0)   # 30 x 20 km
RES = 100.0                                                  # metres/px -> 300 x 200 px


class _StubRegion:
    def __init__(self, tmpdir, dem):
        self.id = "stub"
        self.dir = str(tmpdir)
        self.cfg = {"bounds": list(BOUNDS), "native_resolution_m": RES}
        if dem is not None:
            with rasterio.open(
                    str(tmpdir / "dem.tif"), "w", driver="GTiff", dtype="float32",
                    width=dem.shape[1], height=dem.shape[0], count=1, nodata=np.nan,
                    crs="EPSG:32611", transform=from_bounds(*BOUNDS, dem.shape[1],
                                                            dem.shape[0])) as ds:
                ds.write(dem.astype("float32"), 1)


def _dem(h=200, w=300):
    return np.linspace(500, 2500, h * w).reshape(h, w)


def test_full_coverage_frame_is_the_bounds(tmp_path):
    crop, pw, ph = _frame(_StubRegion(tmp_path, _dem()))
    assert crop == BOUNDS
    assert pw == pytest.approx((BOUNDS[2] - BOUNDS[0]) / (RES * 300.0))
    assert ph == pytest.approx((BOUNDS[3] - BOUNDS[1]) / (RES * 300.0))


def test_nodata_edge_strips_shrink_the_frame_to_finite_data(tmp_path):
    dem = _dem()
    dem[:20, :] = np.nan          # north strip: top 10% of rows -> 2000 m
    dem[:, -30:] = np.nan         # east strip: right 10% of cols -> 3000 m
    crop, pw, ph = _frame(_StubRegion(tmp_path, dem))
    w0, s0, e0, n0 = BOUNDS
    assert crop[0] == pytest.approx(w0, abs=RES)                 # west untouched
    assert crop[1] == pytest.approx(s0, abs=RES)                 # south untouched
    assert crop[2] == pytest.approx(e0 - 3000.0, abs=3 * RES)    # east trimmed
    assert crop[3] == pytest.approx(n0 - 2000.0, abs=3 * RES)    # north trimmed
    # the print size follows the shrunken crop, still landing on the data floor
    assert pw == pytest.approx((crop[2] - crop[0]) / (RES * 300.0))
    assert ph == pytest.approx((crop[3] - crop[1]) / (RES * 300.0))
    # and every pixel inside the crop is finite -- the off-DEM guard has nothing to refuse
    with rasterio.open(str(tmp_path / "dem.tif")) as ds:
        win = rasterio.windows.from_bounds(*crop, transform=ds.transform)
        assert np.isfinite(ds.read(1, window=win)).all()


def test_no_dem_on_disk_falls_back_to_the_bounds(tmp_path):
    crop, _, _ = _frame(_StubRegion(tmp_path, None))
    assert crop == BOUNDS
