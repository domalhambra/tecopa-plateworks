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


def _function_body(module, name):
    """The source of one top-level function of a studio module (its `}` is in column 0)."""
    src = (STATIC / module).read_text(encoding="utf-8")
    m = re.search(rf"^(?:export )?(?:async )?function {name}\([^\n]*\) \{{\n(.*?)\n\}}", src,
                  re.S | re.M)
    assert m, f"{name} not found in {module}"
    return m.group(1)


SET_GUARD = "if (state.output !== 'wallpaper' && state.panels > 1) {"


def test_a_change_of_the_set_shape_frames_the_journey_afresh():
    """refitForSize keeps the old frame's width. The wide frame of a set became a single
    sheet of that width, taller than the plate. So a change of the panel count or of the
    gap takes the Reset frame path, and orientation and the single sizes do not."""
    shape = _function_body("compose.js", "setShape")
    assert "state.panels > 1 ? `${state.panels}:${state.panelGap}` : '1'" in shape
    src = (STATIC / "compose.js").read_text(encoding="utf-8")
    assert "function reframe(was = setShape()) {" in src, \
        "reframe reads the set shape on entry, before applyPrintSize changes it"
    body = _function_body("compose.js", "reframe")
    assert re.search(r"if \(setShape\(\) !== was && state\.starterCrop\) canvas\.resetFrame\(\);"
                     r"\s+else canvas\.refitForSize\(\);", body)
    assert body.index("applyPrintSize()") < body.index("setShape() !== was")
    # the gap control writes the gap itself, so it reads the shape first and passes it
    gap = re.search(r"segGap = wireSegmented\(.*?\n  \}\);", src, re.S)
    assert gap, "the gap control's handler not found"
    assert re.search(r"const was = setShape\(\);.*?state\.panelGap = Number\(v\);.*?reframe\(was\);",
                     gap.group(0), re.S)
    # every other caller lets reframe read the shape itself
    assert len(re.findall(r"\breframe\(was\)", src)) == 1
    assert not re.findall(r"\breframe\((?!was\)|\)|was = )", src)


def test_a_restored_set_keeps_the_crop_the_engine_returns():
    """"Add this year" on a panel file restores the set through ensurePrintSize, which
    sets the size without reframe. The frame is then the starter /api/continue returns,
    the poster's own crop. A reframe there would frame the journey afresh instead."""
    for name in ("ensurePrintSize", "applyPrefill"):
        body = _function_body("compose.js", name)
        assert "reframe(" not in body and "resetFrame" not in body, name
    cont = _function_body("compose.js", "continueFromPoster")
    assert "state.starterCrop = j.starter_crop; state.crop = null;" in cont
    assert "reframe(" not in cont
    # Reset frame gives a starter of another shape the sheet's shape. Used as it was, it
    # was a wide frame on a tall sheet and the proof was refused for its aspect.
    reset = _function_body("canvas.js", "resetFrame")
    assert "if (!near(shape, sheet) && !near(shape, 17 / 22)) {" in reset
    assert "Math.sqrt((x1 - x0) * (y1 - y0) * sheet)" in reset


def test_a_set_stops_each_job_it_cannot_have_before_anything_is_submitted():
    """The engine has no wallpaper bundle, no film and no mockup of a set. The share kit
    queued the 71 megapixel poster final first and was refused after it. Each of these
    stops for a set before its first request and before it disables its control."""
    for module, name, first in (("social.js", "buildKit", "proof.hasFreshProof()"),
                                ("social.js", "stageMockups", ".disabled = true"),
                                ("films.js", "renderTimelapse", "tlInFlight = true")):
        body = _function_body(module, name)
        assert SET_GUARD in body, f"{name} has no stop for a set"
        guard = body.index(SET_GUARD)
        assert guard < body.index(first), f"{name}: the stop for a set comes too late"
        assert guard < body.index("api.submit"), f"{name} submits before the stop"
        stop = body[guard:body.index("}", guard)]
        assert "toast(" in stop and "'info'" in stop and "return;" in stop, name
    assert ("toast('A set of panels has no share kit yet. Choose one sheet for a kit.', 'info');"
            in _function_body("social.js", "buildKit"))
    # A new place that submits a job from the stamped session must decide what a set does
    # there. These are all of them: the proof refine and the final work for a set.
    found = {}
    for path in sorted(STATIC.glob("*.js")):
        n = len(re.findall(r"\bapi\.submit\w+\(state\.session\b", path.read_text(encoding="utf-8")))
        if n:
            found[path.name] = n
    assert found == {"films.js": 1, "proof.js": 2, "social.js": 4}, found


def test_the_save_file_note_has_its_own_sentence_for_a_set_as_pdf():
    """The PDF branch came before the set branch, so a set with PDF chosen was told about
    one sheet. The set-and-PDF branch comes first, and the other sentences are as they
    were."""
    body = _function_body("ui.js", "updateSaveFileNote")
    set_pdf = "state.output !== 'wallpaper' && state.panels > 1 && state.finalFormat === 'pdf'"
    pdf = "} else if (state.output !== 'wallpaper' && state.finalFormat === 'pdf') {"
    a_set = "} else if (state.output !== 'wallpaper' && state.panels > 1) {"
    assert body.index("if (!state.embedSpec) {") < body.index(set_pdf) < body.index(pdf) \
        < body.index(a_set)
    for sentence in (
        "'The PDF panels are for the print shop: they can’t carry the reprint recipe. "
        "Download the set as PNG as well, and keep those files — each PNG panel is a save "
        "file for the whole set.'",
        "'A PDF is for the print shop: it can’t carry the reprint recipe. Download a PNG "
        "as well — that file is your save file and reprints from itself alone.'",
        "`Each panel PNG in the zip is a save file for the whole set: the set reprints "
        "from any one of them, for as long as its terrain plate survives. Keep them — next "
        "year the set becomes Edition ${state.edition + 1}.`",
        "`This PNG is your save file: the whole poster rides inside it and reprints from "
        "the file alone, for as long as its terrain plate survives. Keep it — next year it "
        "becomes Edition ${state.edition + 1}.`",
        "'Reprintable file is off: this download is a share copy — your exact route "
        "coordinates stay out of the file, and it can never reprint or continue. Keep a "
        "reprintable copy as your save file.'",
    ):
        assert sentence in body, sentence


def test_the_proof_call_passes_the_set_to_the_api_module():
    """api.proof defaults to one panel. If the call in proof.js stopped passing the
    two values, a set would go to the engine as an odd single sheet, with a
    remembered bleed, and the engine would accept it: no error anywhere."""
    src = (STATIC / "proof.js").read_text(encoding="utf-8")
    call = re.search(r"api\.proof\((.*?)\);", src, re.S)
    assert call, "proof.js no longer calls api.proof"
    assert re.search(r"\bpanels: state\.panels\b", call.group(1))
    assert re.search(r"\bpanelGap: state\.panelGap\b", call.group(1))


def test_auto_orientation_of_a_set_takes_the_nearer_sheet():
    """Both sheets of a set are wider than tall, so the single-sheet rule ("are the
    tracks wider than tall?") cannot choose. The studio takes the sheet whose shape
    is nearer the journey's, as app/orderpreview.choose does. Run the function itself
    under node, and compare with the order preview's choice."""
    import json
    import shutil
    import subprocess
    import pytest
    from app import orderpreview as opv
    from app.orderplate import nestled_frame, track_shares
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    store = (STATIC / "store.js").read_text(encoding="utf-8")
    fn = re.search(r"export function setAutoIsLandscape\(.*?\n\}\n", store, re.S)
    assert fn, "store.js has no setAutoIsLandscape"
    cases = [(n, g, a) for n in (2, 3) for g in (0, 2, 4)
             for a in (0.2, 0.9, 1.2, 1.7, 2.0, 2.4, 3.0, 5.0, 12.0)]
    script = (fn.group(0).replace("export function", "function").replace(
        "aspect = trackAspect()", "aspect") +
        f"console.log(JSON.stringify({json.dumps(cases)}.map(([n, g, a]) => setAutoIsLandscape(n, g, a))));")
    got = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True,
                                    check=True).stdout)
    for (n, g, a), landscape in zip(cases, got):
        bounds = (0.0, 0.0, 1000.0 * a, 1000.0)            # a box of that shape
        best = {}
        for c in opv.candidates("two" if n == 2 else "three"):
            w = n * (22 if c.orientation == "landscape" else 17) + (n - 1) * g
            h = 17 if c.orientation == "landscape" else 22
            best[c.orientation] = min(track_shares(bounds, nestled_frame(bounds, w / h)))
        want = best["landscape"] > best["portrait"]
        assert landscape == want, (n, g, a, best)
    assert json.loads(subprocess.run(
        ["node", "-e", fn.group(0).replace("export function", "function").replace(
            "aspect = trackAspect()", "aspect") + "console.log(setAutoIsLandscape(2, 2, 0))"],
        capture_output=True, text=True, check=True).stdout) is False     # no box yet

