"""The documentation standard's check, run with the suite.

`docs/README.md` must list every document under `docs/`, every path the guide
and the docs quote must exist, and `CLAUDE.md` must stay under its token
budget. The check itself is `scripts/docs_check.py`, vendored byte for byte
from Plateworks OS; this test only runs it. The standard is
00_Resources/documentation-standard.md.

The test is fast and pure: it reads Markdown and walks the tree. It renders
nothing, so `tests/conftest.py` does not classify it as slow and the fast tier
(`-m "not slow"`) collects it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import docs_check  # noqa: E402


def test_docs_are_indexed_and_every_quoted_path_exists():
    findings = docs_check.check_repo(
        ROOT,
        require=[
            "docs/architecture.md",
            "docs/changing-things.md",
            "docs/decisions.md",
        ],
        known_absent=(
            # docs_check's own default excuses SESSION_LOG.md, the Notion-offline
            # fallback. This repo has one and it is tracked, so it is left out here:
            # excusing it would hide a real deletion later.
            # Gitignored runtime folders. They exist on Dom's Mac after a run
            # and never in a fresh clone. The docs name all four, and quote
            # assets/index.json under one of them.
            "cache/",
            "blobs/",
            "assets/",
            ".venv/",
            # Written 2026-09-02 and deliberately left uncommitted pending
            # Dom's review. It is indexed in docs/README.md, so a clone
            # without the file stays green.
            "docs/superpowers/assessments/2026-09-02-metal-render-viability.md",
            # An order folder's own contents (order pipeline spec, section 1).
            # They live under ~/Tecopa Orders/ (or $TECOPA_ORDERS_DIR),
            # entirely outside this repo, so no checkout ever has them.
            "order.toml",
            "in/",
            "state.json",
            "build.log",
        ),
    )
    assert findings == [], "\n" + "\n".join(str(f) for f in findings)
