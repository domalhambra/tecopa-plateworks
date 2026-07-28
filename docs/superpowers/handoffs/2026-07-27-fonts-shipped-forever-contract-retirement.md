# Handoff — 2026-07-27: type roles shipped, forever-contract retirement pending

> **Superseded same day:** the retirement spec was implemented in the same Mac session
> that wrote this handoff (see the commits following `8acd37c` on `main`). "The next
> job" below is done; the verification caveat was also resolved by the post-retirement
> full-suite run. Kept as written per the handoff convention — historical record.

**From:** Mac session (fonts + curved-label fix + retirement decision)
**State of `main`:** `78e705b`, pushed. Workspace repo at `b69f3ea` (typography doc updated).

## What shipped today

1. **Curved-label reading-direction fix** (`0b6b217`). Direction is decided on the glyphs'
   own tangents, not the whole spine; a spine bending >60° through the name declines the
   curve and falls back straight. Both `lassen_ca` range labels verified on real terrain.
2. **The per-role type seam** (`fca299a`…`78e705b`). `_font(size, role)` with five roles
   (`body`, `point`, `area`, `water`, `title`); operator binds faces via
   `TECOPA_FONT_<ROLE>`; `TECOPA_FONT_<ROLE>_CASE=mixed` for small-caps faces (Advocate);
   bound faces auto-normalise on register metrics (cap-height caps / x-height text)
   against the default chain. README has the binding table; repo CLAUDE.md has the Type
   roles paragraph. Mockup captions follow `TECOPA_FONT_TITLE`.
3. **The retirement decision** (`9afd4b5`) —
   `docs/superpowers/specs/2026-07-27-retire-the-forever-contract-design.md`. Approved,
   **not implemented**. Cross-build byte-identity is dropped; the press's own reprint/
   continue workflow stays.

## Verification state — read before trusting

- Tasks 1–3 of the font plan were committed fully green (label suites show only the
  known Georgia MAD failures).
- **The final two commits (`f1678af`, `78e705b`) rode partial verification**: the 10 seam
  tests green, label suites green, visual gate passed on real `lassen_ca` — but the
  operator stopped the full-suite run before it finished. **First action for any session:
  run the full suite** (`pytest -q`, ~15 min) and confirm only the six known failures
  named in CLAUDE.md. CI on the `78e705b` push is the other completing evidence.

## Constraints for a CLOUD session specifically

- **MB Type faces are Mac-local** (licensed; `.gitignore` blocks all font binaries —
  never weaken it). Cloud renders use DejaVu. Seam *behaviour* is fully testable in
  cloud; type *appearance* is not. Don't judge or tune the slate visually from cloud.
- **The `lassen_ca` DEM is gitignored** — cloud gets a synthetic plate from
  `tests/conftest.py`. `ready: True` does not mean real terrain. Do not rebuild plates
  in cloud (that orphans the Mac's DEM — see MEMORY and CLAUDE.md).
- Cloud lands on `claude/*` branches → squash-merged PR to `main`. Never `main` directly.

## The next job: implement the retirement spec

The spec is the authority; summary of the work:

- Add `engine_version` to the manifest; delete `profile_rev`/`relief_rev` (spec,
  validation, `relief.py:276,317` branches, `main.py` Form + continue-restore, the four
  JS modules), collapsing each to rev-2 behaviour.
- Delete the 8 omit-at-default branches in `serialize.spec_to_json`; **keep**
  `spec_from_json`'s read-tolerance.
- `region_pack` mismatch: 422 → warning with explicit override.
- Stop writing the resurrection note (`provenance.py:206`); demote `docs/MANIFEST.md`
  to internal (CC0 on the published version stands — say so, don't imply withdrawal).
- Delete `tests/test_orphan_drill.py`, `test_relief_rev.py`, `test_profile_rev.py`,
  the 7 frozen `manifest_*_v1.json` fixtures, and the `serial` pytest tier.
- Rewrite the reprint claims in `docs/marketing.md` (rows :44, :73, :128, :165) and the
  forever-contract section of `CLAUDE.md` — the claims register rule means deleted tests
  require deleted claims, same commit.

Suggested shape: plan with superpowers:writing-plans against the spec, then execute.
Expect the suite count to drop substantially; that is the point.

## Small open ends

- `docs/superpowers/plans/2026-07-27-per-role-font-seam.md` is fully executed — mark or
  archive it as done when convenient.
- Recording bound faces in the manifest as an informational note: deferred by the spec's
  "Not decided here". Don't build it without a fresh decision.
- Untracked on the Mac only: `comparison.png`, `tune.png`, `docs/trails for claude
  design/` — pre-existing, not part of this work.
