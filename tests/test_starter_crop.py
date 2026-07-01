# tests/test_starter_crop.py
# Pure geometry, no DEM: the starter crop must match the print aspect and clear the
# 300-dpi zoom-cap floor on entry, so the first "Render proof" never trips the cap.
from app.geo import RegionGeo, starter_crop, crop_px_to_crs_window

LASSEN = RegionGeo(crs="EPSG:32610",
                   bounds=(663529.83, 4447315.73, 726539.83, 4525515.73),
                   overview_size=(1128, 1400))


def _tracks_px():
    # a tight cluster near region center (overview px), the hard case for the cap
    cx, cy = 1128 * 0.5, 1400 * 0.5
    return [[[cx - 20, cy - 20], [cx + 20, cy + 25], [cx + 10, cy - 15]]]


def test_starter_crop_matches_print_aspect_and_clears_floor():
    x0, y0, x1, y1 = starter_crop(LASSEN, _tracks_px(), 18, 24,
                                  native_resolution_m=10, dpi=300)
    # a valid, ordered overview-px box inside the overview
    assert 0 <= x0 < x1 <= 1128 and 0 <= y0 < y1 <= 1400
    win = crop_px_to_crs_window(LASSEN, x0, y0, x1, y1)          # CRS metres
    ground_w = win[2] - win[0]
    # zoom cap: ground_per_pixel(300) = ground_w / round(18*300) >= 10
    assert ground_w / round(18 * 300) >= 10.0 - 1e-6
    # aspect (CRS metres) locked to the print aspect 18/24 within a small tolerance
    ground_h = win[3] - win[1]
    assert abs((ground_w / ground_h) - (18 / 24)) < 0.02


def test_starter_crop_is_centered_on_tracks():
    x0, y0, x1, y1 = starter_crop(LASSEN, _tracks_px(), 18, 24,
                                  native_resolution_m=10, dpi=300)
    cx = (x0 + x1) / 2; cy = (y0 + y1) / 2
    assert abs(cx - 1128 * 0.5) < 60 and abs(cy - 1400 * 0.5) < 60   # near centroid


def test_starter_crop_clamps_into_region():
    # tracks near an edge: the aspect box must slide inside, never spill out
    tracks = [[[40, 40], [70, 90]]]
    x0, y0, x1, y1 = starter_crop(LASSEN, tracks, 18, 24, native_resolution_m=10, dpi=300)
    assert 0 <= x0 < x1 <= 1128 and 0 <= y0 < y1 <= 1400


def test_starter_crop_no_tracks_centers_region():
    x0, y0, x1, y1 = starter_crop(LASSEN, [], 18, 24, native_resolution_m=10, dpi=300)
    assert 0 <= x0 < x1 <= 1128 and 0 <= y0 < y1 <= 1400
    win = crop_px_to_crs_window(LASSEN, x0, y0, x1, y1)
    assert win[2] - win[0] >= 10.0 * round(18 * 300) - 1e-6         # still clears floor
