# The Pick-a-plate page's sentences live in one copy document, and the farm's
# story config repeats its headings (spec 2026-11-01, sections 8 and 10). These
# tests keep the two in step and keep the copy in the customer's register.
import importlib.util
import pathlib
import re
import tomllib

REPO = pathlib.Path(__file__).resolve().parent.parent
COPY = REPO / "docs/superpowers/specs/2026-11-01-pick-a-plate-landing-copy.md"
STORIES = REPO / "marketing/stories.toml"
PLATES = ["canyonlands_ut", "tahoe_ca", "eastern_sierra_ca", "ruby_mountains_nv", "zion_ut"]


def banned_phrases():
    # Read from the live test file so a phrase retired there is retired here. Its
    # requests run inside tests, so importing it fetches nothing.
    spec = importlib.util.spec_from_file_location(
        "marketing_page", REPO / "tests/test_marketing_page.py")
    page = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(page)
    return (page.RETIRED + page.RETIRED_2026_09 + page.RETIRED_2026_10_12
            + page.BUILDER_REGISTER)


def test_copy_has_five_stories_of_three_sections():
    text = COPY.read_text()
    assert re.findall(r"^Anchor: (\w+)$", text, re.M) == [
        "canyonlands", "tahoe", "sierra", "rubies", "zion"]
    assert len(re.findall(r"^### Section [123]: ", text, re.M)) == 15


def test_copy_says_real_trails_and_stays_in_register():
    text = COPY.read_text()
    assert ("Every one is real country and real trails, "
            "lit so the mountains stand up off the paper.") in text
    assert "real trips" not in text
    assert "—" not in text
    assert not re.search(r"\bI [a-z]+[^.\n]*\bby\b", text)
    for phrase in banned_phrases():
        assert phrase not in text, phrase


def test_config_lists_the_five_plates_in_page_order():
    cfg = tomllib.loads(STORIES.read_text())
    assert cfg["status"] == "plan"
    plates = [k for k in cfg if k != "status"]
    assert plates == PLATES
    assert [cfg[p]["anchor"] for p in plates] == [
        "canyonlands", "tahoe", "sierra", "rubies", "zion"]


def test_every_section_heading_is_in_the_copy_document():
    cfg, text = tomllib.loads(STORIES.read_text()), COPY.read_text()
    for plate in PLATES:
        assert len(cfg[plate]["sections"]) == 3
        for n, section in enumerate(cfg[plate]["sections"], 1):
            assert f"### Section {n}: {section['heading']}\n" in text, section["heading"]
            assert section["crop_place"]


def test_drive_trips_name_their_road():
    cfg = tomllib.loads(STORIES.read_text())
    assert {"shape": "drive", "road": "White Rim Road"} in cfg["canyonlands_ut"]["trips"]
    assert {"shape": "drive", "road": "Lamoille Canyon Road"} in cfg["ruby_mountains_nv"]["trips"]
