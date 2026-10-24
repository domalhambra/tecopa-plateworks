# tests/test_papers.py
import pytest

from app import papers

ROW = """
[[paper]]
key = "{key}"
name = "Test Paper"
roll_in = {roll}
profile = "Test.icc"
intent = "{intent}"
preset = "Test preset"
enabled = {enabled}
{extra}
"""


def _table(tmp_path, *rows):
    path = tmp_path / "papers.toml"
    path.write_text("".join(rows), encoding="utf-8")
    return path


def _row(key="a", roll=17, intent="perceptual", enabled="true", extra=""):
    return ROW.format(key=key, roll=roll, intent=intent, enabled=enabled, extra=extra)


def test_the_shipped_table_has_one_enabled_paper():
    p = papers.enabled_paper()
    assert p.name == "Red River Premium Matte 230"
    assert p.roll_in == 17 and p.intent in papers.INTENTS


def test_feed_puts_the_17_in_side_across_the_roll():
    assert papers.feed_rotation(17, 22, 17) == 0
    assert papers.feed_rotation(22, 17, 17) == 90
    assert papers.feed_rotation(11, 17, 17) == 90
    assert papers.feed_rotation(17, 11, 17) == 0


def test_a_piece_no_side_of_which_fits_the_roll_is_refused():
    with pytest.raises(papers.PaperError, match="17 in roll"):
        papers.feed_rotation(18, 24, 17)


def test_a_good_table_is_read_in_file_order(tmp_path):
    path = _table(tmp_path, _row("a"), _row("b", enabled="false"))
    rows = papers.load_papers(path)
    assert [p.key for p in rows] == ["a", "b"]
    assert [p.enabled for p in rows] == [True, False]
    assert papers.enabled_paper(path).key == "a"


def test_an_unknown_field_is_refused(tmp_path):
    path = _table(tmp_path, _row(extra='gloss = "matte"'))
    with pytest.raises(papers.PaperError, match="gloss"):
        papers.load_papers(path)


def test_an_intent_outside_the_list_is_refused(tmp_path):
    path = _table(tmp_path, _row(intent="saturation"))
    with pytest.raises(papers.PaperError, match="intent"):
        papers.load_papers(path)


def test_no_enabled_paper_is_refused(tmp_path):
    path = _table(tmp_path, _row(enabled="false"))
    with pytest.raises(papers.PaperError, match="enabled"):
        papers.enabled_paper(path)


def test_two_enabled_papers_are_refused(tmp_path):
    path = _table(tmp_path, _row("a"), _row("b"))
    with pytest.raises(papers.PaperError, match="enabled"):
        papers.enabled_paper(path)


def test_a_missing_field_a_bad_roll_and_a_repeated_key_are_refused(tmp_path):
    no_preset = _row().replace('preset = "Test preset"\n', "")
    with pytest.raises(papers.PaperError, match="preset"):
        papers.load_papers(_table(tmp_path, no_preset))
    with pytest.raises(papers.PaperError, match="roll_in"):
        papers.load_papers(_table(tmp_path, _row(roll=0)))
    with pytest.raises(papers.PaperError, match="twice"):
        papers.load_papers(_table(tmp_path, _row("a"), _row("a", enabled="false")))
    with pytest.raises(papers.PaperError, match="enabled"):
        papers.load_papers(_table(tmp_path, _row(enabled='"yes"')))
