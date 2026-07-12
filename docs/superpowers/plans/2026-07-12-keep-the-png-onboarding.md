# TrailPrint — "Keep the PNG" Onboarding (design + implementation plan)

_2026-07-12 · Status: **proposed** (not yet built). Small, and it protects the entire
Living Editions ritual from its one silent failure mode. Sibling to
`2026-07-12-honest-coverage-plate-boundary.md`._

---

## Context — the save file is the PNG, and the marketing points users at the wrong artifact

The tagline is *"the poster on your wall is the save file."* Taken literally it is
**backwards**: the provenance manifest lives in a `zTXt` chunk (`app/provenance.py`), and
that chunk **does not survive printing**. The framed print on the wall is the one artifact
in the whole system that *cannot* be continued — it has no manifest, no spec, no lineage.
**The PNG is the save file.** The poster is the photograph of the save file.

As poetry the tagline is fine. As onboarding it is dangerous, because the entire Living
Editions thesis — the yearly ritual, the repeat purchase, "Edition 2 a year out" (the
marketing plan's single success metric) — depends on the user **still having the PNG next
January.** And nothing in the product currently teaches that or protects against losing it.
The most valuable user action (returning next year with last year's file) is guarded by
nothing more than "hopefully it's still in their Downloads folder." For a product whose
differentiator is *"your artifact can never be orphaned,"* orphaning-by-lost-download is the
one failure mode that quietly kills the flywheel.

## The one design idea: make the PNG's role explicit at the moment it's created, and easy to recover

Not a cloud backup (that would violate the no-cloud identity the scope doc defends). The fix
is to make the local file's importance **legible and its loss recoverable-by-habit**:

1. **Name the moment.** At download, one honest line: *"This PNG is your save file — it
   holds your whole poster and reprints forever. Keep it; next year it becomes Edition 2."*
   Turn the tagline from a wall metaphor into a **file instruction**. This is the highest-
   leverage sentence in the app and it currently isn't said.
2. **A filename that self-documents.** `trailprint_lassen_edition-1_2026.png`, not
   `a.png` / `final.png` — the file should announce what it is in any Downloads folder two
   years later.
3. **Keep "Download again" prominent** (it already exists — v1.1 added re-serve of the last
   final without an ~80 s re-render; `2026-07-02-v1.1-redteam.md`). Surface it as "save
   another copy," so making a backup is one click, not a re-render.
4. **The `tEXt` resurrection note** (shared with `2026-07-12-reprint-forever-continuity.md`
   step 6): a human-readable chunk inside the PNG telling a future finder what the file is
   and how to reopen it. Belt-and-suspenders for the day the user forgets everything the UI
   told them.
5. **On "Continue a poster," verify and reassure.** When a user drops last year's PNG,
   confirm the manifest read cleanly and echo the edition/lineage back (*"Edition 1, Lassen,
   2026 — ready to add this year"*) so the ritual visibly *works* and the habit reinforces.

## Concrete work

- **Copy:** the download-step sentence + the "Continue a poster" confirmation echo (wizard +
  landing copy). No engine change.
- **Filename:** compose the download name from region + edition + year (data already on the
  spec/manifest). Small change at the download-serving path.
- **Re-download affordance:** relabel/surface the existing "Download again" as "Save another
  copy."
- **`tEXt` note:** shared with the continuity plan — build once, both plans benefit.

## Invariants / risks

- **No cloud, no account.** Every mitigation is local — copy, filename, a PNG chunk, a
  re-download button. The scope doc's identity is preserved; the point is precisely to make
  the *local file* trustworthy enough that no cloud is needed.
- **The tagline stays** as brand poetry; the *onboarding* stops relying on it being literally
  true. Wall poster = the beautiful object; PNG = the save file. Say both.

## Out of scope

Any server-side archive of user files (violates the identity and competes with the
file-is-the-archive thesis — the scope doc names this explicitly). This plan makes losing
the file *harder and recoverable-by-habit*, not *impossible via our servers*.
