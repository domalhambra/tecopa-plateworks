# The marketing-honesty gate for the Tecopa pages (CLAUDE.md invariant 11: every
# claim has a test behind it). The page went stale once -- it kept selling the
# forever-contract for weeks after 2026-07-27 retired it, and showed four plates
# when five were built. These tests make that class of drift a red build instead
# of a live lie.
#
# Since 2026-09-26 the pages live on Ghost (spec
# docs/superpowers/specs/2026-09-24-ghost-landing-page-design.md §8), so the tests
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
ORDER_EMAIL = "badwaterguidance@gmail.com"


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
# (Tecopa orders are paid by an LZ Books invoice, 2026-09-26)
RETIRED_2026_09 = ["$299", "commission", "Tell me where you've been", "region-request",
                   "Stripe", "PayPal"]


def test_no_retired_claims():
    for path, page in (("/tecopa/", landing()), ("/tecopa-build/", order())):
        for phrase in RETIRED + RETIRED_2026_09:
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
LANDING_PRICES = ["$79", "$89", "$39", "$59", "$69", "$25"]
ORDER_PRICES = ["$79", "$89", "$39"]


def test_every_price_is_on_the_landing_page():
    page = landing()
    for price in LANDING_PRICES:
        assert price in page, f"landing page lost the price {price}"


def test_the_order_page_carries_the_first_poster_prices_and_the_address():
    page = order()
    for price in ORDER_PRICES:
        assert price in page, f"order page lost the price {price}"
    assert f'href="mailto:{ORDER_EMAIL}' in page
    # the comment markers keep Cloudflare's email obfuscation off the address
    assert "<!--email_off-->" in page and "<!--/email_off-->" in page


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


# The privacy page (spec §6) says what the Ghost pages load. Those claims are only
# true while the pages stay as described, so each is pinned against the published
# HTML. Change what a page loads and the privacy page goes red until its copy and
# its "Last updated" date follow.
NAMED_HOSTS = {"fonts.bunny.net", "cdn.jsdelivr.net", "storage.ghost.io"}


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
    # The site-wide Plausible script came off on 2026-09-26: Ghost's own
    # analytics counts the visits, and the page must not claim otherwise.
    assert "Ghost's built-in analytics" in page
    assert "Plausible" not in page
    for host in NAMED_HOSTS:
        assert host in page, f"privacy page no longer names {host}"
    allowed = NAMED_HOSTS | {"www.plateworks.org"}
    for path in ("/tecopa/", "/tecopa-build/", "/tecopa-privacy-policy/"):
        loaded = set(re.findall(
            r'<(?:script|link|img|iframe|source|video)[^>]+?(?:src|href)="https?://([^/"]+)', fetch(path)))
        extra = sorted(loaded - allowed)
        assert not extra, f"{path} loads from {extra}; name them on the privacy page"


def test_privacy_page_says_how_orders_are_paid():
    page = privacy()
    assert "LZ Books" in page
    assert "Stripe" not in page and "PayPal" not in page
