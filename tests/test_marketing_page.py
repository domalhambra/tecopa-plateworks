# The marketing-honesty gate for the landing page (CLAUDE.md: every claim must have
# a test behind it). The page went stale once -- it kept selling the forever-contract
# for weeks after 2026-07-27 retired it, and showed four plates when five were built.
# These tests make that class of drift a red build instead of a live lie.
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = (REPO / "marketing" / "landing.html").read_text(encoding="utf-8")

# claims retired with the forever-contract (docs/superpowers/specs/2026-07-27-*):
# none may reappear in customer copy without reinstating the tests behind them
RETIRED = ["orphan drill", "Reprint forever", "reprint forever",
           "tested against every release", "byte-for-byte"]


def test_no_retired_claims():
    for phrase in RETIRED:
        assert phrase not in PAGE, f"retired claim back on the landing page: {phrase!r}"


def test_every_built_plate_is_on_the_page():
    built = sorted(p.parent.name for p in REPO.glob("regions/*/region.json"))
    assert built, "no regions found -- the test is looking in the wrong place"
    on_page = set(re.findall(r'data-plate="([^"]+)"', PAGE))
    missing = [r for r in built if r not in on_page]
    assert not missing, f"built plates absent from the landing page gallery: {missing}"


def test_no_ghost_plates_on_the_page():
    built = {p.parent.name for p in REPO.glob("regions/*/region.json")}
    ghosts = [r for r in re.findall(r'data-plate="([^"]+)"', PAGE) if r not in built]
    assert not ghosts, f"landing page advertises plates that are not built: {ghosts}"


def test_demand_signals_have_a_channel():
    # the region-request form (Netlify) and the commission CTA must exist and be wired
    assert 'name="region-request"' in PAGE and "data-netlify" in PAGE
    assert 'name="form-name"' in PAGE            # required for JS-less Netlify capture
    assert "plate%20commission" in PAGE          # the commission mailto

def test_the_studio_door_exists():
    assert "https://github.com/domalhambra/tecopa-plateworks" in PAGE


def test_osm_attribution_is_present():
    # the demo journeys are routed over OpenStreetMap geometry, which is ODbL:
    # the rendered posters are a produced work, so attribution ships or the
    # licence is not satisfied. A claim on the page needs a test behind it, and
    # so does an obligation.
    assert "OpenStreetMap contributors" in PAGE
