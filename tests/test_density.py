# tests/test_density.py
import numpy as np
from app.ingest import Track
from app.density import hotspots, _rasterize_visits

def line(a, b, n=50):
    return np.linspace(a, b, n)

def test_returned_place_outranks_one_off():
    base = (430000.0, 4350000.0)
    # Five overlapping tracks through 'base' (a returned-to place):
    repeated = [Track(f"r{i}", line(base, (base[0]+500, base[1]+500)), day=f"2024-01-0{i+1}")
                for i in range(5)]
    # One long one-off elsewhere:
    oneoff = [Track("o0", line((445000.0, 4365000.0), (446000.0, 4366000.0)), day="2024-02-01")]
    hs = hotspots(repeated + oneoff, region_bounds=(400000, 4318000, 470000, 4385000),
                  cell_m=1000, max_spots=3)
    assert len(hs) >= 1
    top = hs[0]
    assert abs(top["x"] - base[0]) < 2000 and abs(top["y"] - base[1]) < 2000
    assert top["weight"] >= 5

def test_short_segment_marks_destination_cell():
    # A 200 m segment (shorter than half a 1000 m cell) that crosses a cell
    # boundary must mark BOTH the start and the destination cell, not just the start.
    bounds = (400000.0, 4318000.0, 470000.0, 4385000.0)
    cell_m = 1000.0
    t = Track("t", np.array([[430900.0, 4350000.0], [431100.0, 4350000.0]]), day="2024-01-01")
    grid, nx, ny = _rasterize_visits([t], bounds, cell_m)
    gy = int((bounds[3] - 4350000.0) / cell_m)
    gx_start = int((430900.0 - bounds[0]) / cell_m)   # cell 30
    gx_end = int((431100.0 - bounds[0]) / cell_m)     # cell 31
    assert gx_start != gx_end
    assert grid[gy, gx_start] >= 1
    assert grid[gy, gx_end] >= 1                       # the dropped one before the fix

def test_dayless_tracks_from_different_files_count_separately():
    # red-team: track_ids restart at "<name>-0" per FILE, so two day-less files'
    # tracks used to collide on the visit key and undercount to weight 1.
    base = (430000.0, 4350000.0)
    a = Track("track-0", line(base, (base[0] + 500, base[1] + 500)), day=None)
    b = Track("track-0", line(base, (base[0] + 500, base[1] + 500)), day=None)  # same id!
    hs = hotspots([a, b], region_bounds=(400000, 4318000, 470000, 4385000),
                  cell_m=1000, max_spots=1)
    assert hs and hs[0]["weight"] == 2
