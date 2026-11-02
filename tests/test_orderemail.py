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
        if key != "digital":
            row["member_link"] = f"https://buy.stripe.com/member_{key}"
            row["member_next_link"] = f"https://buy.stripe.com/member_next_{key}"
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
    assert "- 17 × 22 in, $69 plus $14 shipping: " in text
    assert "- Three panels, $159 plus $16 shipping: " in text
    assert "- Digital poster, $25, nothing to ship: " in text
    assert "first_" not in text and "$99" not in text and "$189" not in text


def test_a_member_gets_the_member_links_with_no_shipping_and_no_code(tmp_path):
    text = oe.email_text(_order(tmp_path, member=True), _entries("11x17", "two"), _rows())
    assert URL.findall(text) == [f"https://buy.stripe.com/member_11x17?client_reference_id={NUMBER}",
                                 f"https://buy.stripe.com/member_two?client_reference_id={NUMBER}",
                                 f"https://buy.stripe.com/first_digital?client_reference_id={NUMBER}"]
    assert "- 11 × 17 in, $69, shipping included: " in text
    assert "- Two panels, $149, shipping included: " in text
    assert "- Digital poster, $39, nothing to ship: " in text
    assert ("As a member at plateworks.org, your shipping is on me: the print links below have "
            "none.") in text
    assert "$8" not in text and "$16" not in text and "code" not in text
    # a returning member: next year's prices, with no shipping
    text = oe.email_text(_order(tmp_path, member=True, returning=True), _entries("17x22"), _rows())
    assert URL.findall(text)[:1] == [f"https://buy.stripe.com/member_next_17x22?client_reference_id={NUMBER}"]
    assert "- 17 × 22 in, $69, shipping included: " in text
    assert "next_digital?" in text


def test_a_member_order_needs_the_member_links_and_says_to_check_stripe(tmp_path):
    out = tmp_path / "out"
    order = _order(tmp_path, member=True)
    result = oe.write(order, _entries("11x17", "two"), _rows(two="member_link", **{"11x17": "shipping"}),
                      str(out))
    assert result["missing"] == ["Two panels (member_link)"]    # a member's link has no shipping
    result = oe.write(order, _entries("11x17"), _rows(), str(out))
    assert oe.report_line(result, member=True) == (
        f"Email: {out / 'email.txt'}, with the member links (no shipping). Check Stripe for an "
        f"active Plateworks Member subscription on the client's email before it goes out.")


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

def _sizes_file(tmp_path, monkeypatch, links=None):
    """The repo's sizes.toml with its own links swapped for made-up ones, on the rows
    named in `links` (every row when None)."""
    body = open(sizes.default_path(), encoding="utf-8").read()
    body = re.sub(r'(?m)^(member_)?(next_)?link = .*\n', "", body)
    body = re.sub(r'(?m)^(key = "([a-z0-9]+)")$',
                  lambda m: m[0] if links is not None and m[2] not in links else
                  f'{m[0]}\nlink = "https://buy.stripe.com/first_{m[2]}"\n'
                  f'next_link = "https://buy.stripe.com/next_{m[2]}"',
                  body)
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


def test_the_preview_with_a_link_missing_says_which_and_writes_no_email(tmp_path, tools, monkeypatch):
    # the repo's file before the links were made: only the digital poster had one
    _sizes_file(tmp_path, monkeypatch, links=["digital"])
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


# ---- the wash: the email tells the client the PDF shows two maps (viewshed wash, 20) ----

def _washed(*offered):
    return [{**e, "wash_image": f"/x/{e['key']}-wash.png"} if e["offered"] else e
            for e in _entries(*offered)]


def test_the_email_says_each_page_shows_two_maps_when_the_preview_drew_both(tmp_path):
    text = oe.email_text(_order(tmp_path), _washed("11x17", "two"), _rows())
    assert oe.WASH_PARAGRAPH in text.splitlines()
    assert oe.WASH_PARAGRAPH == (
        "The page for each size shows your map twice, side by side: as it is, and with your "
        "pins and the ground they can see. Ground out of their sight is toned down. It's line "
        "of sight over bare ground, so it ignores trees and buildings. Reply and tell me "
        "which one you'd like.")
    lines = text.splitlines()
    first = next(i for i, l in enumerate(lines) if l.startswith("Here's your map"))
    assert lines[first + 2] == oe.WASH_PARAGRAPH and lines[first + 1] == ""
    # nothing else of the email moved, and the links are the same
    plain = oe.email_text(_order(tmp_path), _entries("11x17", "two"), _rows())
    assert "\n".join(l for l in lines if l != oe.WASH_PARAGRAPH).replace("\n\n\n", "\n\n") == \
        plain.rstrip("\n").replace("\n\n\n", "\n\n")


def test_the_email_has_no_such_paragraph_without_a_second_map(tmp_path):
    for entries in (_entries("11x17", "two"),
                    [{**e, "wash_image": "/x.png"} if not e["offered"] else e
                     for e in _entries("11x17")]):                 # only a size not offered has one
        assert oe.WASH_PARAGRAPH not in oe.email_text(_order(tmp_path), entries, _rows())


def test_the_wash_paragraph_keeps_to_the_profile():
    words = oe.WASH_PARAGRAPH
    assert "line of sight over bare ground" in words
    assert "what you saw" not in words.lower() and "—" not in words
    assert "plate" not in words.lower() and "viewshed" not in words.lower()
    assert not words.startswith(("I ", "We "))                       # not the maker's verb first


def test_the_preview_of_an_order_with_the_key_writes_the_paragraph(tmp_path, tools, monkeypatch):
    from tests.test_orderpreview import _asking_for_the_wash, _washing_render
    _sizes_file(tmp_path, monkeypatch)
    d = _intake_order(tmp_path)
    intake = (f'order_number = "{NUMBER}"\nreturning = false\n'
              'client = "Sam Smith"\nemail = "sam@example.com"\n')
    _asking_for_the_wash(d, [(-116.2, 35.9, "Camp")])
    with open(d / "order.toml", "a") as f:
        f.write(intake)

    def run():
        opv.preview(str(d), tools, log=lambda s: None, render=_washing_render([]),
                    write_pdf=lambda path, entries, names, title: None)
        return (d / "out" / "preview" / "email.txt").read_text()
    assert oe.WASH_PARAGRAPH in run().splitlines()
    # take the key away and it is the email it was
    (d / "order.toml").write_text('title = "Smith home ground"\nsize = "12x18"\n' + intake)
    assert oe.WASH_PARAGRAPH not in run()


# ---- a photos-only order with the key: the proof is the first picture of its wash ----

def _with_photos(tmp_path, n=2, **kw):
    from tests.test_photos import _make
    (tmp_path / "in").mkdir(exist_ok=True)
    for k in range(n):
        _make(tmp_path / "in" / f"p{k}.jpg")
    return _order(tmp_path, **kw)


def _paragraphs(text):
    return [l for l in text.splitlines() if l]


def test_the_email_for_photos_and_no_second_map_says_the_proof_shows_the_wash(tmp_path):
    order = _with_photos(tmp_path, viewshed=0.6)
    text = oe.email_text(order, _entries("11x17", "two"), _rows())
    lines = text.splitlines()
    first = next(i for i, l in enumerate(lines) if l.startswith("Here's your map"))
    assert lines[first + 2] == oe.WASH_PHOTOS_PROOF and lines[first + 1] == ""
    assert oe.WASH_PHOTOS_PROOF == (
        "Your photos mark places on the map, and the proof will tone down the ground that "
        "can't be seen from them. It's line of sight over bare ground, so it ignores trees "
        "and buildings. If you'd rather have the plain map, just say so.")
    assert oe.WASH_PARAGRAPH not in lines and oe.WASH_PHOTOS_TOO not in lines
    assert len(URL.findall(text)) == 3                    # the links did not move


def test_the_email_for_waypoints_and_photos_says_the_proof_can_show_more(tmp_path):
    order = _with_photos(tmp_path, viewshed=0.6)
    text = oe.email_text(order, _washed("11x17", "two"), _rows())
    lines = text.splitlines()
    first = lines.index(oe.WASH_PARAGRAPH)
    assert lines[first + 1] == "" and lines[first + 2] == oe.WASH_PHOTOS_TOO
    assert oe.WASH_PHOTOS_TOO == (
        "Your photos count as pins too. They only get their places when the proof is made, "
        "so it can show more ground in sight than these pages do.")
    assert oe.WASH_PHOTOS_PROOF not in lines


def test_photos_say_nothing_about_a_wash_without_the_key_or_when_the_wash_has_no_photo(tmp_path):
    photos = _with_photos(tmp_path)                                    # no key
    for entries in (_entries("11x17"), _washed("11x17")):
        text = oe.email_text(photos, entries, _rows())
        assert not {oe.WASH_PHOTOS_PROOF, oe.WASH_PHOTOS_TOO} & set(text.splitlines())
    keyed = _order(tmp_path / "none", viewshed=0.6)                    # the key, no photo
    text = oe.email_text(keyed, _washed("11x17"), _rows())
    assert oe.WASH_PARAGRAPH in text.splitlines()
    assert oe.WASH_PHOTOS_TOO not in text.splitlines()
    assert oe.WASH_PHOTOS_PROOF not in oe.email_text(keyed, _entries("11x17"), _rows())


@pytest.mark.parametrize("words", ["WASH_PHOTOS_PROOF", "WASH_PHOTOS_TOO"])
def test_the_photo_sentences_keep_to_the_profile(words):
    text = getattr(oe, words)
    assert "what you saw" not in text.lower() and "—" not in text
    assert "plate" not in text.lower() and "viewshed" not in text.lower()
    assert not text.startswith(("I ", "We ")) and " by " not in text   # no maker's verb "by"
    assert ("line of sight over bare ground" in text) == (words == "WASH_PHOTOS_PROOF")


def test_the_preview_of_a_photos_only_order_with_the_key_writes_the_proof_paragraph(
        tmp_path, tools, monkeypatch):
    from tests.test_orderpreview import _asking_for_the_wash, _washing_render
    from tests.test_photos import _make
    _sizes_file(tmp_path, monkeypatch)
    d = _intake_order(tmp_path)
    _asking_for_the_wash(d, [])                          # the key, and no waypoint in the files
    with open(d / "order.toml", "a") as f:
        f.write(f'order_number = "{NUMBER}"\nreturning = false\n'
                'client = "Sam Smith"\nemail = "sam@example.com"\n')
    _make(d / "in" / "a.jpg")
    opv.preview(str(d), tools, log=lambda s: None, render=_washing_render([]),
                write_pdf=lambda path, entries, names, title: None)
    lines = (d / "out" / "preview" / "email.txt").read_text().splitlines()
    assert oe.WASH_PHOTOS_PROOF in lines and oe.WASH_PARAGRAPH not in lines
