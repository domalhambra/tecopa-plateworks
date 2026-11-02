# app/orderemail.py
"""The preview email: the words Dom pastes into HEY, with the preview PDF attached.

One line for each size the preview offers and a last line for the digital poster, each
with its price, its shipping and its Payment Link. Each link ends with
?client_reference_id=<order number>: Stripe returns that value with the sale, and that
is how a payment names its order. No email address is ever in a link. A returning
client (order.toml `returning = true`) gets the next-year prices and links. A member
(`member = true`) gets the member links of each print size: the same price with no
shipping, so there is no code to enter. The digital poster ships nothing and has one
link for everyone.

Spec: docs/superpowers/specs/2026-10-12-tecopa-client-intake-and-payment-design.md,
sections 5.2 and 5.3, and decisions 3 and 7. Nothing here sends an email: the file is a
draft, and Dom reads it before it goes out."""
from __future__ import annotations

import os

from app.order import ORDER_NUMBER
from app.sizes import DIGITAL, PAYMENT_LINK

FILE = "email.txt"
SUBJECT = "Your Tecopa Plateworks poster, order {number}"
# Said only when the preview drew a second map of each size (the order's `viewshed` key,
# viewshed wash spec, decision 20). A customer sentence: it goes through the profile, so it
# says "line of sight over bare ground", and no word of what the client saw or knows.
WASH_PARAGRAPH = (
    "The page for each size shows your map twice, side by side: as it is, and with your "
    "pins and the ground they can see. Ground out of their sight is toned down. It's line "
    "of sight over bare ground, so it ignores trees and buildings. Reply and tell me which "
    "one you'd like.")
# Photos get their places in Prepare, so the preview's second map holds the waypoints and
# no photo (wash spec, final review, finding 4). These two sentences say what the proof adds.
# Customer sentences: "line of sight over bare ground", and what is on the paper first.
WASH_PHOTOS_TOO = (
    "Your photos count as pins too. They only get their places when the proof is made, so "
    "it can show more ground in sight than these pages do.")
WASH_PHOTOS_PROOF = (
    "Your photos mark places on the map, and the proof will tone down the ground that "
    "can't be seen from them. It's line of sight over bare ground, so it ignores trees and "
    "buildings. If you'd rather have the plain map, just say so.")


def _fields(order, key) -> tuple:
    """(price field, link field) of one row for this order."""
    price = "next_price" if order.returning else "price"
    if order.member and key != DIGITAL:
        return price, "member_next_link" if order.returning else "member_link"
    return price, "next_link" if order.returning else "link"


def _needed(entries) -> list:
    """The rows the email has a line for: the offered sizes in menu order, then digital."""
    return [e["key"] for e in entries if e["offered"]] + [DIGITAL]


def missing(order, entries, rows) -> list:
    """What config/sizes.toml lacks for this order's email, as "<name> (<field>)"."""
    out = []
    for key in _needed(entries):
        row = rows.get(key)
        if row is None:
            out.append("the digital poster (no row)" if key == DIGITAL else f"{key} (no row)")
            continue
        price_field, link_field = _fields(order, key)
        shipping = [] if key == DIGITAL or order.member else ["shipping"]
        fields = [price_field] + shipping + [link_field]
        out += [f"{row['name']} ({f})" for f in fields if not row[f]]
    return out


def link(row_link: str, number: str) -> str:
    """A Payment Link that names its order. Both parts are checked again here: a link
    carries the order number and nothing else of the client's."""
    if not PAYMENT_LINK.fullmatch(row_link) or not ORDER_NUMBER.fullmatch(number):
        raise ValueError(f"not a Payment Link and an order number: {row_link!r}, {number!r}")
    return f"{row_link}?client_reference_id={number}"


def email_text(order, entries, rows) -> str:
    """The email. The caller checks `missing` first: every row it needs is there."""
    number = order.order_number
    first_name = order.client.split()[0] if order.client.split() else ""
    lines = [f"To: {order.email}".rstrip(), "Subject: " + SUBJECT.format(number=number), "",
             f"Hi {first_name}," if first_name else "Hi,", ""]
    # One paragraph to a line: HEY wraps the lines itself, and a hard break would show.
    lines += ["Here's your map at each size it suits. The PDF attached shows them all on one "
              "wall first, so you can see how big each one is, then a page for each size."]
    photos = bool(order.viewshed > 0 and order.photo_files())     # they are marks in the wash
    if any(e["offered"] and e.get("wash_image") for e in entries):
        lines += ["", WASH_PARAGRAPH] + (["", WASH_PHOTOS_TOO] if photos else [])
    elif photos:                           # a wash with no second map: the proof shows it first
        lines += ["", WASH_PHOTOS_PROOF]
    if order.returning:
        lines += ["", "Good to see your tracks again. Since this isn't your first poster, these "
                      "are the next-year prices."]
    if order.member:
        lines += ["", "As a member at plateworks.org, your shipping is on me: the print links "
                      "below have none."]
    lines += ["", "When you've picked one, pay with its link:", ""]
    for key in _needed(entries):
        row = rows[key]
        price_field, link_field = _fields(order, key)
        paid = link(row[link_field], number)
        if key == DIGITAL:
            lines.append(f"- {row['name']}, {row[price_field]}, nothing to ship: {paid}")
        elif order.member:
            lines.append(f"- {row['name']}, {row[price_field]}, shipping included: {paid}")
        else:
            lines.append(f"- {row['name']}, {row[price_field]} plus {row['shipping']} shipping: {paid}")
    if any(e["offered"] and e.get("panels", 1) > 1 for e in entries):
        lines += ["", "A set is shown with a 2 in gap between the panels. It can also hang with "
                      "no gap, or with a 4 in gap. Reply and tell me which you'd like."]
    lines += ["",
              "Once you've paid, I make the full proof of your poster and send it to you. You "
              "can ask for a full refund any time until you approve the proof. Nothing prints "
              "before you approve it, and one round of changes is free.",
              "",
              "The links ship to US addresses. If you're outside the US, reply and I'll send "
              "you an invoice instead.",
              "",
              "Thanks,",
              "Dom",
              "Tecopa Plateworks"]
    text = "\n".join(lines) + "\n"
    if any("@" in w for w in text.split() if w.startswith("https://")):
        raise ValueError("an email address must never be in a link")
    return text


def write(order, entries, rows, out_dir) -> dict:
    """Write out_dir/email.txt, or remove an old one when this order can have none.
    {"path": the file or None, "missing": what sizes.toml lacks, "why": another reason}."""
    path = os.path.join(out_dir, FILE)
    result = {"path": None, "missing": [], "why": ""}
    if not order.order_number:
        result["why"] = ("order.toml has no order_number: an order made before the intake. "
                         "A link must name its order.")
    else:
        result["missing"] = missing(order, entries, rows)
    if result["why"] or result["missing"]:
        if os.path.lexists(path):
            os.remove(path)                # an old email would carry old sizes or links
        return result
    text = email_text(order, entries, rows)
    os.makedirs(out_dir, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    result["path"] = path
    return result


def report_line(result, member=False) -> str:
    if result["path"]:
        if member:
            return (f"Email: {result['path']}, with the member links (no shipping). Check "
                    f"Stripe for an active Plateworks Member subscription on the client's "
                    f"email before it goes out.")
        return f"Email: {result['path']}"
    if result["why"]:
        return f"Email: not written. {result['why']}"
    return ("Email: not written. config/sizes.toml has no "
            + ", ".join(result["missing"]) + " for this order.")
