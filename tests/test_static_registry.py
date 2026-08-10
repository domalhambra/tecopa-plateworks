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
