# tests/test_orderemail.py
"""The preview email: one Payment Link for each offered size and the digital poster
(client intake spec, 2026-10-12, section 5.2)."""
import os
import re

import pytest

from app import order as od
from app import orderemail as oe
from app import orderpreview as opv
from app import sizes
from tests.test_orderpreview import _preview
from tests.test_orderprep import WIDE, _make_order, tools  # noqa: F401

NUMBER = "TP-26-001"
URL = re.compile(r"https://\S+")


def _rows(**drop):
    """The repo's prices with a first-poster and a next-year link on every row."""
    rows = sizes.table()
    for key, row in rows.items():
        row["link"] = f"https://buy.stripe.com/first_{key}"
        row["next_link"] = f"https://buy.stripe.com/next_{key}"
    for key, field in drop.items():
        rows[key][field] = ""
    return rows


def _entries(*offered):
    return [{"key": k, "offered": k in offered, "panels": {"two": 2, "three": 3}.get(k, 1)}
            for k in od.SIZE_KEYS]


def _order(tmp_path, **kw):
    base = dict(dir=str(tmp_path), title="Smith home ground", subtitle="", size=(11.0, 17.0),
                orientation="portrait", notes="", order_number=NUMBER, client="Sam Smith",
                email="sam@example.com")
    base.update(kw)
    return od.Order(**base)


def test_a_link_for_each_offered_size_and_the_digital_poster_and_no_other(tmp_path):
    text = oe.email_text(_order(tmp_path), _entries("11x17", "two"), _rows())
    links = URL.findall(text)
    assert links == [f"https://buy.stripe.com/first_{k}?client_reference_id={NUMBER}"
                     for k in ("11x17", "two", "digital")]
    lines = text.splitlines()
    # one line for each: the name, the price, the shipping and the link
    assert f"- 11 × 17 in, $69 plus $8 shipping: {links[0]}" in lines
    assert f"- Two panels, $149 plus $16 shipping: {links[1]}" in lines
    assert lines.index(f"- Two panels, $149 plus $16 shipping: {links[1]}") + 1 == \
        lines.index(f"- Digital poster, $39, nothing to ship: {links[2]}")     # digital is last
    assert "17 × 22" not in text and "Three panels" not in text


def test_the_order_number_is_in_each_link_and_no_email_address_is(tmp_path):
    text = oe.email_text(_order(tmp_path), _entries(*od.SIZE_KEYS), _rows())
    links = URL.findall(text)
    assert len(links) == 5
    for link in links:
        assert link.endswith(f"?client_reference_id={NUMBER}")
        assert "@" not in link and "sam" not in link and "email" not in link
    assert text.count("sam@example.com") == 1
    assert text.splitlines()[0] == "To: sam@example.com"


def test_the_subject_is_the_one_thread_of_the_order(tmp_path):
    text = oe.email_text(_order(tmp_path), _entries("11x17"), _rows())
    assert text.splitlines()[1] == "Subject: Your Tecopa Plateworks poster, order TP-26-001"
    assert text.splitlines()[3] == "Hi Sam,"


def test_a_returning_client_gets_the_next_year_links_and_prices(tmp_path):
    text = oe.email_text(_order(tmp_path, returning=True), _entries("17x22", "three"), _rows())
    assert URL.findall(text) == [f"https://buy.stripe.com/next_{k}?client_reference_id={NUMBER}"
                                 for k in ("17x22", "three", "digital")]
    assert "- 17 × 22 in, $69 plus $12 shipping: " in text
    assert "- Three panels, $159 plus $16 shipping: " in text
    assert "- Digital poster, $25, nothing to ship: " in text
    assert "first_" not in text and "$99" not in text and "$189" not in text


def test_the_refund_and_the_changes_are_said(tmp_path):
    text = oe.email_text(_order(tmp_path), _entries("11x17"), _rows())
    assert ("You can ask for a full refund any time until you approve the proof. Nothing "
            "prints before you approve it, and one round of changes is free.") in " ".join(text.split())


def test_the_gap_of_a_set_is_said_only_when_a_set_is_offered(tmp_path):
    with_set = " ".join(oe.email_text(_order(tmp_path), _entries("11x17", "three"), _rows()).split())
    assert ("A set is shown with a 2 in gap between the panels. It can also hang with no gap, "
            "or with a 4 in gap") in with_set
    single = oe.email_text(_order(tmp_path), _entries("11x17", "17x22"), _rows())
    assert "gap" not in single


def test_no_client_name_or_address_still_makes_an_email(tmp_path):
    text = oe.email_text(_order(tmp_path, client="", email=""), _entries("11x17"), _rows())
    assert text.splitlines()[0] == "To:" and text.splitlines()[3] == "Hi,"


@pytest.mark.parametrize("drop,returning,said", [
    ({"two": "link"}, False, ["Two panels (link)"]),
    ({"digital": "next_link"}, True, ["Digital poster (next_link)"]),
    ({"11x17": "next_price", "two": "next_link"}, True, ["11 × 17 in (next_price)", "Two panels (next_link)"]),
    ({"two": "shipping"}, False, ["Two panels (shipping)"]),
])
def test_a_missing_link_or_price_writes_no_email_and_names_what_is_missing(tmp_path, drop, returning,
                                                                           said):
    out = tmp_path / "out" / "preview"
    out.mkdir(parents=True)
    (out / "email.txt").write_text("an old email with old links")
    result = oe.write(_order(tmp_path, returning=returning), _entries("11x17", "two"),
                      _rows(**drop), str(out))
    assert result == {"path": None, "missing": said, "why": ""}
    assert not (out / "email.txt").exists()        # the email of an earlier run is gone too
    assert oe.report_line(result) == ("Email: not written. config/sizes.toml has no "
                                      + ", ".join(said) + " for this order.")


def test_a_size_that_is_not_offered_needs_no_link(tmp_path):
    out = tmp_path / "out"
    result = oe.write(_order(tmp_path), _entries("11x17"), _rows(three="link"), str(out))
    assert result["path"] == str(out / "email.txt") and os.path.isfile(result["path"])
    assert oe.report_line(result) == f"Email: {out / 'email.txt'}"


def test_the_digital_row_is_needed(tmp_path):
    rows = _rows()
    del rows["digital"]
    result = oe.write(_order(tmp_path), _entries("11x17"), rows, str(tmp_path))
    assert result["missing"] == ["the digital poster (no row)"]


def test_an_order_with_no_order_number_gets_no_email(tmp_path):
    (tmp_path / "email.txt").write_text("old")
    result = oe.write(_order(tmp_path, order_number=""), _entries("11x17"), _rows(), str(tmp_path))
    assert result["path"] is None and not (tmp_path / "email.txt").exists()
    assert oe.report_line(result) == ("Email: not written. order.toml has no order_number: an "
                                      "order made before the intake. A link must name its order.")


# ---- in the preview ----

def _sizes_file(tmp_path, monkeypatch, links=True):
    body = open(sizes.default_path(), encoding="utf-8").read()
    if links:
        body = re.sub(r'(?m)^(key = "([a-z0-9]+)")$',
                      r'\1\nlink = "https://buy.stripe.com/first_\2"\nnext_link = "https://buy.stripe.com/next_\2"',
                      body)
        body = re.sub(r'(?m)^link = "https://buy\.stripe\.com/fZu5.*$', "", body)
    path = tmp_path / "sizes.toml"
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(sizes, "default_path", lambda: str(path))


def _intake_order(tmp_path, returning=False):
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    with open(d / "order.toml", "a") as f:
        f.write(f'order_number = "{NUMBER}"\nreturning = {str(returning).lower()}\n'
                'client = "Sam Smith"\nemail = "sam@example.com"\n')
    return d


def test_the_preview_writes_the_email_beside_the_pdf(tmp_path, tools, monkeypatch):
    _sizes_file(tmp_path, monkeypatch)
    d = _intake_order(tmp_path)
    state = _preview(d, tools)
    email = d / "out" / "preview" / "email.txt"
    text = email.read_text()
    offered = [e["key"] for e in state["sizes"] if e["offered"]]
    assert URL.findall(text) == [f"https://buy.stripe.com/first_{k}?client_reference_id={NUMBER}"
                                 for k in offered + ["digital"]]
    assert state["email"]["path"] == str(email)
    report = (d / "work" / "preview" / "report.txt").read_text()
    assert f"Email: {email}\n" in report
    assert report.rstrip().splitlines()[-1].startswith("Time: ")


def test_a_returning_clients_pdf_and_email_have_the_next_year_prices(tmp_path, tools, monkeypatch):
    _sizes_file(tmp_path, monkeypatch)
    d = _intake_order(tmp_path, returning=True)
    seen = []
    state = opv.preview(str(d), tools, log=lambda s: None, render=lambda *a: _render(*a),
                        write_pdf=lambda path, entries, names, title: seen.append(names))
    assert seen[0]["11x17"]["price"] == "$59" and seen[0]["17x22"]["price"] == "$69"
    assert state["names"] == seen[0]
    assert "next_digital?client_reference_id=TP-26-001" in (d / "out" / "preview" / "email.txt").read_text()
    assert 'offered, price "$59"' in (d / "work" / "preview" / "report.txt").read_text()


def _render(entries, tracks, plate_dir, title, out_dir):
    for e in entries:
        if e["offered"]:
            e["image"], e["dpi"] = os.path.join(out_dir, e["key"] + ".png"), opv.preview_dpi(e)


def test_the_preview_with_the_links_not_made_yet_says_which_are_missing(tmp_path, tools):
    # the repo's file on 2026-10-12: only the digital poster's first-poster link exists
    d = _intake_order(tmp_path)
    state = _preview(d, tools)
    assert not (d / "out" / "preview" / "email.txt").exists()
    report = (d / "work" / "preview" / "report.txt").read_text()
    names = [sizes.table()[e["key"]]["name"] for e in state["sizes"] if e["offered"]]
    assert ("Email: not written. config/sizes.toml has no "
            + ", ".join(f"{n} (link)" for n in names) + " for this order.\n") in report


def test_an_order_from_before_the_intake_has_a_report_line_and_no_email(tmp_path, tools, monkeypatch):
    _sizes_file(tmp_path, monkeypatch)
    d = _make_order(tmp_path, bbox=WIDE, size="11x17")
    _preview(d, tools)
    assert not (d / "out" / "preview" / "email.txt").exists()
    assert "Email: not written. order.toml has no order_number" in \
        (d / "work" / "preview" / "report.txt").read_text()
