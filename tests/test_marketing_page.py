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


# the profile spec (docs/superpowers/specs/2026-08-16-target-customer-profile-design.md)
# struck the builder's register from customer surfaces: measurements as selling
# points, file-format talk, licence names, and privacy reassurance that answers
# a question nobody asked. The page speaks to the Home-Ground Collector.
BUILDER_REGISTER = [
    "2.6",                      # the pt-width lines, both variants
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


def test_the_page_speaks_to_the_collector_not_the_builder():
    for phrase in BUILDER_REGISTER:
        assert phrase not in PAGE, f"builder register on a customer surface: {phrase!r}"


def test_the_customers_doubts_are_answered():
    # the four doubts from the profile spec, pinned by their load-bearing phrases
    assert "until you say yes" in PAGE          # doubt 4: you see it before it prints
    assert "export GPX in bulk" in PAGE         # doubt 2: getting tracks out is easy
    assert "the person who makes your poster" in PAGE   # the one plain order-door line
    assert "Tell me where you've been" in PAGE  # the request door, maker-present


# The privacy page (marketing/privacy.html, published at /privacy/) makes claims
# about the landing page -- what it loads, what it stores, where the form goes.
# Those claims are only true while the landing page stays as described, so each
# one is pinned here against the HTML it describes. Change the landing page and
# the privacy page goes red until its copy is brought back into step.
PRIVACY = (REPO / "marketing" / "privacy.html").read_text(encoding="utf-8")
FOOTER = PAGE[PAGE.index("<footer"):PAGE.index("</footer>")]


def test_the_footer_links_to_the_privacy_page():
    assert 'href="/privacy/"' in FOOTER


def test_privacy_page_carries_its_furniture():
    assert re.search(r"Last updated \d{4}-\d{2}-\d{2}\.", PRIVACY)
    assert 'href="mailto:badwaterguidance@gmail.com"' in PRIVACY
    # the comment markers keep Cloudflare's email obfuscation off the address
    assert "<!--email_off-->" in PRIVACY and "<!--/email_off-->" in PRIVACY
    assert 'href="/"' in PRIVACY               # a way back to the landing page


def test_privacy_page_describes_what_the_landing_page_actually_does():
    # analytics: the page loads Plausible, and the privacy page says so
    assert "plausible.io" in PAGE and "Plausible" in PRIVACY
    # "stores nothing in your browser": the landing page must not touch storage
    for api in ("localStorage", "sessionStorage", "document.cookie", "indexedDB"):
        assert api not in PAGE, f"landing page uses {api}; the privacy page says it stores nothing"
    # the region-request form is Netlify Forms, and the privacy page names it
    assert 'name="region-request"' in PAGE and "Netlify" in PRIVACY
    # orders happen over mailto, and the privacy page says where that lands
    assert "mailto:" in PAGE and "email" in PRIVACY
    # "Plausible's script is the only one loaded from another site": every
    # src/href that leaves this origin must be Plausible's, or a plain link
    loaded = set(re.findall(r'<(?:script|link|img|iframe|source)[^>]+?(?:src|href)="https?://([^/"]+)', PAGE))
    assert loaded == {"plausible.io"}, f"landing page loads from {loaded}; update privacy.html"
