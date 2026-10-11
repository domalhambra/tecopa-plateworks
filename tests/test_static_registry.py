# tests/test_static_registry.py
"""The studio has no JS test runner, so the control registry and the studio shell are
checked from here as text. Each rule below is a bug that actually shipped: a duplicate
key inside one control literal is legal JS that silently keeps the LAST value -- which
is how five help sentences (oblique, contours, compass, tlHoldMs, tlLeaderMs) vanished
while pasted into a neighbour's literal; a control without help is an unexplained
slider, the exact failure the ?-affordance exists to prevent; and a duplicated DOM id
makes getElementById resolve the first match and silently orphan the rest (the
provenance card lived that bug). Pure text checks -- no node, no browser."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def _control_literals():
    """Split the CONTROLS array into one source slice per control literal."""
    src = (STATIC / "controls.js").read_text(encoding="utf-8")
    m = re.search(r"export const CONTROLS = \[(.*?)\n\];", src, re.S)
    assert m, "CONTROLS array not found in controls.js"
    body = m.group(1)
    starts = [mm.start() for mm in re.finditer(r"\{ id: '", body)]
    assert len(starts) > 20, "suspiciously few controls parsed -- splitter broken?"
    slices = []
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(body)
        chunk = body[s:end]
        cid = re.match(r"\{ id: '([^']+)'", chunk).group(1)
        slices.append((cid, chunk))
    return slices


def test_every_control_has_exactly_one_help():
    """One help sentence per control: zero is an unexplained knob, two or more means a
    duplicate key and JS is silently discarding all but the last."""
    bad = []
    for cid, chunk in _control_literals():
        n = len(re.findall(r"\bhelp:", chunk))
        if n != 1:
            bad.append(f"{cid}: {n} help keys")
    assert not bad, f"controls with missing/duplicated help: {bad}"


def test_no_duplicate_keys_within_a_control():
    """The registry's own top-level keys must appear at most once per literal (options
    sub-literals legitimately repeat value/label, so only registry keys are checked)."""
    registry_keys = ("id", "path", "section", "panel", "label", "type", "default",
                     "affectsProof", "help", "hint", "keywords", "visibleWhen",
                     "advanced", "geometry", "min", "max", "step", "fmt")
    bad = []
    for cid, chunk in _control_literals():
        # options sub-literals legitimately repeat value/label per entry — count only
        # the control's own keys, not its option list's
        chunk = re.sub(r"options: \[.*?\]", "", chunk, flags=re.S)
        for key in registry_keys:
            n = len(re.findall(rf"[\{{,\s]{key}:", chunk))
            if n > 1:
                bad.append(f"{cid}.{key} x{n}")
    assert not bad, f"duplicate keys inside control literals (last one wins!): {bad}"


def test_every_panel_has_a_group_description():
    """The sidebar explains each group under its heading; a panel value without a
    GROUPS entry renders a heading with no explanation."""
    src = (STATIC / "controls.js").read_text(encoding="utf-8")
    panels = set(re.findall(r"panel: '([^']+)'", src))
    groups_m = re.search(r"export const GROUPS = \{(.*?)\n\};", src, re.S)
    assert groups_m, "GROUPS map not found"
    groups = set(re.findall(r"'([^']+)':", groups_m.group(1)))
    groups.discard("Fine-tuning")  # not a panel value; the advanced disclosure's title
    missing = panels - groups
    assert not missing, f"panels without a GROUPS description: {sorted(missing)}"
    assert "Fine-tuning" in re.findall(r"'([^']+)':", groups_m.group(1)), \
        "the advanced disclosure needs its GROUPS sentence too"


def test_index_html_ids_are_unique():
    """getElementById returns the FIRST match; a repeated id silently orphans the rest
    of them (the home surface once carried a #provenanceCard nothing could reach)."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    ids = re.findall(r'\bid="([^"]+)"', html)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"duplicate ids in index.html: {dupes}"


# ---- the debug hook (app/static/debug.js) ----
# The hook posts the studio's small state and its errors to the engine. The studio's
# promise is that it goes online only to build a plate, and that a report never holds
# journey data. With no JS runner, each of those promises is held here as text.

DEBUG_JS = STATIC / "debug.js"
# store.js field -> the key the engine keeps
HOOK_FIELDS = {"session": "session", "target": "target", "view": "view",
               "region": "region", "output": "output", "edition": "edition",
               "hasSpec": "has_spec", "proofStale": "proof_stale"}


def test_app_starts_the_debug_hook():
    """A module nobody imports is dead code that still passes every other check here."""
    src = (STATIC / "app.js").read_text(encoding="utf-8")
    assert re.search(r"^import \* as debug from '\./debug\.js';$", src, re.M), \
        "app.js does not import ./debug.js"
    assert len(re.findall(r"\bdebug\.init\(", src)) == 1, \
        "app.js calls debug.init( exactly one time"


def test_debug_hook_posts_to_one_local_route():
    """One fetch, to the hook's own engine route by a same-origin path. A second fetch,
    or a second import, is a second door for data to leave by."""
    src = DEBUG_JS.read_text(encoding="utf-8")
    assert len(re.findall(r"\bfetch\(", src)) == 1, "debug.js holds exactly one fetch("
    target = re.search(r"\bfetch\(\s*(['\"`])(.*?)\1", src)
    assert target, "the fetch target is not a string literal"
    assert target.group(2) == "/api/debug/studio"
    assert re.findall(r"^\s*import\b[^;]*;", src, re.M) == \
        ["import { state } from './store.js';"], "debug.js imports only ./store.js"
    assert not re.search(r"\bimport\s*\(", src), "debug.js holds no dynamic import"
    assert len(re.findall(r"\bfrom\s+['\"]", src)) == 1, "debug.js re-exports nothing"


def test_debug_hook_names_no_journey_data():
    """The privacy rule, held on the whole source text, comments included: the hook
    cannot send a field it never names."""
    src = DEBUG_JS.read_text(encoding="utf-8")
    named = sorted({w.lower() for w in re.findall(
        r"\b(tracks|hotspots|files|crop|title)\b", src, re.I)})
    assert not named, f"debug.js names journey data: {named}"


def test_debug_hook_reads_the_store_only_as_its_eight_fields():
    """The word list above cannot name every store field, and a field has more than
    one spelling: state['tracks'], a destructure, a spread, JSON.stringify(state). So
    the store may appear only as state.<one of the eight>. The one other use is the
    import itself."""
    src = DEBUG_JS.read_text(encoding="utf-8")
    code = re.sub(r"//.*$", "", src, flags=re.M)
    loose = re.findall(
        r"(?<![\w$])(?<![^.]\.)state\b"
        r"(?!\.(?:session|target|view|region|output|edition|hasSpec|proofStale)\b)", code)
    assert loose == ["state"], f"debug.js uses the store outside its eight fields: {loose}"


def test_debug_hook_leaves_no_other_trace():
    """The hook writes nothing to the browser log, stores nothing, and has no second
    way to send."""
    src = DEBUG_JS.read_text(encoding="utf-8")
    held = [w for w in ("console.", "localStorage", "sessionStorage", "sendBeacon",
                        "XMLHttpRequest") if w in src]
    assert not held, f"debug.js holds: {held}"


def test_no_studio_module_names_an_outside_host():
    """The studio goes online only to build a plate, and the engine does that. No
    module in the browser names a host: each request is a same-origin path."""
    modules = sorted(STATIC.glob("*.js"))
    assert len(modules) > 20, "suspiciously few studio modules found -- glob broken?"
    bad = [m.name for m in modules
           if re.search(r"https?://", m.read_text(encoding="utf-8"))]
    assert not bad, f"studio modules that name a host: {bad}"


def test_debug_hook_sends_the_state_keys_the_engine_keeps():
    """The engine drops each key it does not know without a word, so a renamed key is a
    field that silently stops arriving. The eight keys sent are the eight kept, and the
    eight store fields read are the only ones the hook reads."""
    from app.debug import STATE_KEYS
    src = DEBUG_JS.read_text(encoding="utf-8")
    body = re.search(r"function snapshot\(\) \{(.*?)\n\}", src, re.S)
    assert body, "snapshot() not found in debug.js"
    pairs = re.findall(r"^\s*(\w+): scalar\(state\.(\w+)\),$", body.group(1), re.M)
    assert len(pairs) == len(STATE_KEYS), f"snapshot() sends {len(pairs)} keys"
    assert {key for key, _ in pairs} == set(STATE_KEYS)
    assert {field: key for key, field in pairs} == HOOK_FIELDS
    # no read of the store anywhere else in the module
    assert set(re.findall(r"\bstate\.(\w+)", src)) == set(HOOK_FIELDS)
    # each field read is a field the store has: a misspelled one is sent as null
    store = (STATIC / "store.js").read_text(encoding="utf-8")
    missing = [f for f in HOOK_FIELDS if not re.search(rf"^  {f}:", store, re.M)]
    assert not missing, f"fields debug.js reads that store.js does not have: {missing}"


def test_the_studio_sends_a_set_with_the_engines_own_field_names():
    """The two set fields have one name each on the wire. A typo here would send a
    set as a single sheet with no error, because FastAPI ignores an unknown field."""
    import inspect
    from app import main
    params = inspect.signature(main.proof).parameters
    assert "panels" in params and "panel_gap" in params
    api = (STATIC / "api.js").read_text(encoding="utf-8")
    assert re.search(r"\bpanels: panels > 1 \? panels : undefined", api)
    assert re.search(r"\bpanel_gap: panels > 1 \? panelGap : undefined", api)
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<option value="panels:2">Two panels</option>' in html
    assert '<option value="panels:3">Three panels</option>' in html
    assert 'id="gapField"' in html and 'id="gap"' in html
    store = (STATIC / "store.js").read_text(encoding="utf-8")
    assert re.search(r"^  panels: 1,", store, re.M) and re.search(r"^  panelGap: 2,", store, re.M)


def test_a_set_is_sent_with_no_bleed():
    """The engine refuses a set with bleed (422). The bleed control is hidden for a set,
    so a remembered bleed must stay out of the request, or every proof of a set fails."""
    api = (STATIC / "api.js").read_text(encoding="utf-8")
    assert re.search(
        r"\bbleed: output === 'print' && panels === 1 && style\.bleedIn \? style\.bleedIn : undefined",
        api)


def test_the_provenance_card_escapes_every_value_it_is_given():
    """The card is written with innerHTML from a file anyone can craft. Each value from
    the inspect reply is made a number or escaped before the template, and the template
    takes only those locals. An info.x inside the markup is the hole: the edition was
    one."""
    src = (STATIC / "library.js").read_text(encoding="utf-8")
    body = re.search(r"function renderProvenance\(info\) \{(.*?)\n\}", src, re.S)
    assert body, "renderProvenance not found in library.js"
    template = re.search(r"card\.innerHTML = `(.*?)`;", body.group(1), re.S)
    assert template, "the card template not found"
    assert "provenance-actions" in template.group(1), "the template was cut short"
    raw = re.findall(r"\binfo\b[.\[]\w*", template.group(1))
    assert not raw, f"values written into the card straight from the reply: {raw}"
    # the text values are escaped where they are read
    for field in ("title", "region_id"):
        assert re.search(rf"escapeHtml\(info\.{field}\b", body.group(1)), field
