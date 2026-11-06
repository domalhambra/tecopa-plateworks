"""The Mac app bundle's two locks (native Mac app phase 1 plan, task 9)."""
import re
from pathlib import Path

from scripts.macos import bundle_checks as bc

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "requirements-bundle-engine.txt"
PREP = REPO / "requirements-bundle-prep.txt"
LINE = re.compile(r"^[A-Za-z0-9._-]+==\S+ --hash=sha256:[0-9a-f]{64}$")


def _lines(p):
    return [l for l in p.read_text().splitlines() if l.strip() and not l.startswith("#")]


def _names(p):
    return {bc._norm(l.split("==")[0]) for l in _lines(p)}


def test_the_engine_lock_holds_every_runtime_pin():
    assert bc.lock_pin_mismatches(REPO / "requirements-lock.txt", ENGINE, bc.TEST_STACK) == []


def test_every_bundle_pin_is_hashed():
    for p in (ENGINE, PREP):
        bad = [l for l in _lines(p) if not LINE.match(l)]
        assert bad == [], (p.name, bad)


def test_the_engine_lock_has_no_test_stack_and_has_the_extras():
    names = _names(ENGINE)
    assert not names & {bc._norm(n) for n in bc.TEST_STACK}
    assert {"pandas", "geopandas", "pyogrio", "imageio-ffmpeg"} <= names


def test_the_prep_lock_is_not_the_engine_lock():
    # Invariant 13: two environments, never one.
    assert ENGINE.read_text() != PREP.read_text()
    assert "py3dep" in _names(PREP)
