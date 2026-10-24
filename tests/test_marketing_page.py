# The marketing-honesty gate for the Tecopa pages (CLAUDE.md invariant 11: every
# claim has a test behind it). The page went stale once -- it kept selling the
# forever-contract for weeks after 2026-07-27 retired it, and showed four plates
# when five were built. These tests make that class of drift a red build instead
# of a live lie.
#
# The pages lived on Ghost from 2026-09-26 (spec
# docs/superpowers/specs/2026-09-24-ghost-landing-page-design.md §8) and on the
# Netlify site (domalhambra/plateworks-site) since 2026-10-13, so the tests
# fetch what is published. They carry the `live` marker and stay out of the default
# run (tests/conftest.py). Run them after every publish of any of the three pages:
#
#   .venv/bin/python -m pytest -m live tests/test_marketing_page.py
import pathlib
import re
from functools import lru_cache

import httpx
import pytest

pytestmark = pytest.mark.live

REPO = pathlib.Path(__file__).resolve().parent.parent
SITE = "https://www.plateworks.org"
ORDER_EMAIL = "lab@plateworks.org"


@lru_cache(maxsize=None)
def fetch(path):
    # httpx (a dev dependency) carries certifi's roots; the python.org build's
    # urllib has none on a fresh Mac.
    res = httpx.get(SITE + path, headers={"User-Agent": "tecopa-honesty-tests"}, timeout=30)
    assert res.status_code == 200, f"{path} returned {res.status_code}"
    return res.text


def article(path):
    # The page's own words: the theme's header, footer and scripts are not claims.
    html = fetch(path)
    return html[html.index("<article"):html.index("</article>")]


def landing():
    return article("/tecopa/")


def order():
    return article("/tecopa-build/")


def privacy():
    return article("/tecopa-privacy-policy/")


# claims retired with the forever-contract (docs/superpowers/specs/2026-07-27-*):
# none may reappear in customer copy without reinstating the tests behind them
RETIRED = ["orphan drill", "Reprint forever", "reprint forever",
           "tested against every release", "byte-for-byte"]

# claims retired with the Ghost move (decisions 2026-09-24): the plate
# commission, the region-request form, and a payment by Stripe or PayPal
# (the marketing pages say "pay by card"; only the privacy page names Stripe)
RETIRED_2026_09 = ["$299", "commission", "Tell me where you've been", "region-request",
                   "Stripe", "PayPal"]

# claims retired with the client intake (spec 2026-10-12, section 7): the order by
# email with attachments, and the invoice after the proof
RETIRED_2026_10_12 = ["Email me your tracks", "Start the email", "invoice", "LZ Books"]


def test_no_retired_claims():
    for path, page in (("/tecopa/", landing()), ("/tecopa-build/", order())):
        for phrase in RETIRED + RETIRED_2026_09 + RETIRED_2026_10_12:
            assert phrase not in page, f"retired claim back on {path}: {phrase!r}"


def built_plates():
    built = sorted(p.parent.name for p in REPO.glob("regions/*/region.json"))
    assert built, "no regions found -- the test is looking in the wrong place"
    return built


def test_every_built_plate_is_on_the_page():
    page = landing()
    missing = [r for r in built_plates() if f"{r}-coin" not in page]
    assert not missing, f"built plates absent from the landing page's coins: {missing}"


def test_no_ghost_plates_on_the_page():
    built = set(built_plates())
    shown = set(re.findall(r"/([a-z0-9_]+)-coin(?:-h)?\.(?:webp|png)", landing()))
    ghosts = sorted(shown - built)
    assert not ghosts, f"landing page shows plates that are not built: {ghosts}"


# spec §2.1: the first poster and next year's, at both sizes and digital
# (the two-size menu, Dom 2026-10-10: 11x17 and 17x22 from 17 in rolls)
# and, since the client intake (spec 2026-10-12, decisions 6 and 7), the two sets
# and the shipping of each print
LANDING_PRICES = ["$69", "$99", "$149", "$189", "$39", "$59", "$119", "$159", "$25",
                  "$8", "$12", "$16"]
ORDER_PRICES = ["$69", "$99", "$149", "$189", "$39", "$8", "$12", "$16"]
SIZES = ["11×17", "17×22", "two panels", "three panels"]
# the Tecopa order form, on plateworks.org since the intake's D43 (Netlify Forms,
# which posts to the intake's /forms); Tally's q4xp89 before
ORDER_FORM = "/tecopa/request/"
# retired 2026-10-10: the PRO-1100 feeds at most 17 in, so 18x24 cannot print
RETIRED_2026_10 = ["13×19", "18×24", "$79", "$89"]


def test_every_price_is_on_the_landing_page():
    page = landing()
    for price in LANDING_PRICES:
        assert price in page, f"landing page lost the price {price}"


def test_the_order_page_carries_the_first_poster_prices_and_the_address():
    page = order()
    for price in ORDER_PRICES:
        assert price in page, f"order page lost the price {price}"
    # the address stays for questions; the order itself starts on the form
    assert f'href="mailto:{ORDER_EMAIL}' in page
    # the comment markers keep Cloudflare's email obfuscation off the address
    assert "<!--email_off-->" in page and "<!--/email_off-->" in page


def test_the_order_page_opens_the_form():
    page = order()
    assert f'href="{ORDER_FORM}' in page
    assert "Start your order" in page


def test_both_pages_say_when_you_pay_and_how_to_get_it_back():
    # spec 2026-10-12, decisions 1 and 3: pay after the size preview, and a full
    # refund until the proof is approved
    assert "after you've seen your map at each size" in landing()
    for path, page in (("/tecopa/", landing()), ("/tecopa-build/", order())):
        assert "you can ask for a full refund" in page, f"{path} lost the refund sentence"
        # decision 9: a member says so on the form and gets the shipping back
        assert "A member at plateworks.org?" in page, f"{path} lost the member line"


def test_the_landing_page_opens_the_order_page():
    assert "/tecopa-build/" in landing()


def test_the_studio_door_exists():
    assert "https://github.com/domalhambra/tecopa-plateworks" in landing()


def test_osm_attribution_is_present():
    # the demo journeys are routed over OpenStreetMap geometry, which is ODbL:
    # the rendered posters are a produced work, so attribution ships or the
    # licence is not satisfied. A claim on the page needs a test behind it, and
    # so does an obligation.
    assert "OpenStreetMap contributors" in landing()


# the profile spec (docs/superpowers/specs/2026-08-16-target-customer-profile-design.md)
# struck the builder's register from customer surfaces: measurements as selling
# points, file-format talk, licence names, and privacy reassurance that answers
# a question nobody asked. The page speaks to the Home-Ground Collector.
BUILDER_REGISTER = [
    "2.6 pt",                   # the pt-width lines, both variants
    "pixel-for-pixel",
    "hash-addressed",
    "a known ppi",
    "physical units",
    "deterministic",
    "byte-identical",
    "CC0",
    "AGPL",
    "Private by default",
    "keep my tracks",
    "disappears",               # the "What if Tecopa Plateworks disappears?" FAQ
]


def test_the_pages_speak_to_the_collector_not_the_builder():
    for path, page in (("/tecopa/", landing()), ("/tecopa-build/", order())):
        for phrase in BUILDER_REGISTER:
            assert phrase not in page, f"builder register on {path}: {phrase!r}"


def test_the_customers_doubts_are_answered():
    # the doubts from the profile spec, pinned by their load-bearing phrases
    page = landing()
    assert "until you say yes" in page          # doubt 4: you see it before it prints
    assert "export GPX in bulk" in page         # doubt 2: getting tracks out is easy
    assert "the person who makes your poster" in page   # the one plain order-door line


# The privacy page (spec §6) says what the pages load. Those claims are only
# true while the pages stay as described, so each is pinned against the published
# HTML. Change what a page loads and the privacy page goes red until its copy and
# its "Last updated" date follow.
# Since 2026-10-24 the outside hosts are Umami's script from stats.plateworks.org
# on every page (Plausible before it, from the move to Netlify on 2026-10-13)
# and the video poster's placeholder on /tecopa/; fonts, scripts and images
# otherwise come from the site.
NAMED_HOSTS = {"img.spacergif.org", "stats.plateworks.org"}


def test_the_pages_link_to_the_privacy_page():
    for path in ("/tecopa/", "/tecopa-build/"):
        assert "/tecopa-privacy-policy/" in fetch(path), f"{path} has no privacy link"


def test_privacy_page_carries_its_furniture():
    page = privacy()
    assert re.search(r"Last updated \d{4}-\d{2}-\d{2}\.", page)
    assert f'href="mailto:{ORDER_EMAIL}"' in page
    assert "<!--email_off-->" in page and "<!--/email_off-->" in page
    assert 'id="support"' in page               # the #support anchor, its last section


def test_privacy_page_names_every_host_the_pages_load():
    page = privacy()
    # Netlify hosts the pages and Umami counts the page views, without
    # cookies, and the page must say so. The Ghost-era and Plausible-era
    # claims are gone.
    assert "Netlify hosts these pages" in page
    assert "Umami" in page and "cookies" in page
    assert "Plausible" not in page
    assert "Ghost's built-in analytics" not in page
    assert "storage.ghost.io" not in page
    for host in NAMED_HOSTS:
        assert host in page, f"privacy page no longer names {host}"
    allowed = NAMED_HOSTS | {"www.plateworks.org", "plateworks.org"}
    for path in ("/tecopa/", "/tecopa-build/", "/tecopa-privacy-policy/"):
        loaded = set(re.findall(
            r'<(?:script|link|img|iframe|source|video)[^>]+?(?:src|href)="https?://([^/"]+)', fetch(path)))
        extra = sorted(loaded - allowed)
        assert not extra, f"{path} loads from {extra}; name them on the privacy page"


def test_privacy_page_says_how_orders_are_paid():
    page = privacy()
    assert "Stripe takes the payment on its own page" in page
    assert "LZ Books" not in page and "PayPal" not in page


def test_privacy_page_says_who_holds_what_and_for_how_long():
    # spec 2026-10-12, section 7 and decision 8. The form and the order record
    # are on Netlify since the intake's D37 (ORDER_LOG=blobs) and D43 (the form
    # on plateworks.org through Netlify Forms).
    page = privacy()
    for service in ("Netlify", "Dropbox", "Stripe"):
        assert service in page, f"privacy page no longer names {service}"
    assert "Netlify, which hosts these pages, holds the form's answers" in page
    assert "emails me a copy of the form" in page
    for gone in ("Tally", "Notion"):
        assert gone not in page, f"privacy page still names {gone}"
    assert "90 days after your poster is delivered" in page
    assert "hold them for next year" in page


def test_both_pages_sell_the_two_sizes_and_no_retired_one():
    for path, page in (("/tecopa/", landing()), ("/tecopa-build/", order())):
        for size in SIZES:
            assert size in page, f"{path} lost the size {size}"
        for gone in RETIRED_2026_10:
            assert gone not in page, f"{path} still shows the retired {gone}"
