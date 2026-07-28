# Retiring the forever-contract — design

**Status:** approved in conversation 2026-07-27. Not yet implemented.

**Decision:** Stop promising that a poster reprints byte-identically across future engine
versions. Keep every feature that lets *the press* reopen, reprint and continue a poster.
Stamp the engine version into the manifest instead of proving against it.

---

## Why

The contract was written for an imagined person: a stranger in 2035 holding the PNG, with
no app and no author. Everything expensive serves only them — `profile_rev`, `relief_rev`,
seven frozen `manifest_*_v1.json` fixtures, the additive-defaults rule, the orphan drill,
the resurrection note, a CC0 format spec inviting third-party readers.

The person who actually reprints is Dom, on his own machine, when a customer wants a
reorder or a new edition. That costs almost nothing to support.

The cost is not hypothetical. Within one hour on 2026-07-27 the contract forced a revision
question onto an ordinary bug fix (upside-down curved range labels, `0b6b217`) whose old
behaviour was a defect nobody would ever want preserved.

## The line

**Byte-identity within one build is free and worth keeping.** It falls out of determinism
(invariant 3 — seeded grain and jitter), which the engine needs anyway or the proof stops
predicting the print. A reorder rendered today matches one rendered this morning.

**Byte-identity across builds is the entire expense.** `app/spec.py:104` states the
mechanism plainly: *"no engine version rides the file, so the rev is the gate."* Give the
file a version and the gate becomes unnecessary.

---

## What changes

### 1. Stamp the version, drop the revs

Add `engine_version` to the manifest. Delete `profile_rev` and `relief_rev` from
`CompositionSpec`, their `PROFILE_REVS` / `RELIEF_REVS` validation, their two branches in
`app/relief.py:276,317`, and their plumbing through `app/main.py` and `app/static/`.
Collapse each to its rev-2 behaviour — the float32 + pyramid-blur relief chain and the
rev-2 elevation strip are the ones worth keeping.

When a reprint no longer matches, the file says which build made it. Drift is **recorded,
not prevented**.

### 2. Keep read-tolerance, drop write-identity

These were conflated and only one is expensive.

- **Keep** `serialize.spec_from_json`'s two-way drift tolerance — unknown fields dropped,
  missing ones defaulted. This is what lets a two-year-old poster open at all.
- **Drop** the eight omit-at-default branches in `serialize.spec_to_json`. They exist only
  so a pre-feature manifest re-stamps byte-for-byte. Always emit every field: simpler code,
  and a more self-describing file.

### 3. The untrusted door is untouched

`provenance.manifest_to_spec` — parse, drop non-embedded photos, bound geometry, validate —
is about crafted PNGs, not about reprint identity. A hostile file is still hostile. No
change.

### 4. `region_pack` mismatch becomes a warning, not a refusal

Today a rebuilt plate makes `/api/reprint` refuse with 422. That was right when the promise
was byte-identity; it is wrong when the goal is "reprint it for them easily." USGS re-flying
3DEP should not block a customer's reorder.

Keep the check and keep surfacing it — the operator needs to know the terrain moved — but
let the reprint proceed on an explicit override.

### 5. Cut the stranger infrastructure

- **The resurrection note** (`provenance.py:206`, `NOTE_KEY`). It bakes a promise into every
  file sold. Stop writing it to new files.
- **The CC0 manifest spec.** `docs/MANIFEST.md` stops being a public contract and becomes an
  internal format doc, free to change. **The CC0 dedication on what is already published
  cannot be revoked** — that grant stands for that version. This is a decision to stop
  maintaining and advertising it, not a withdrawal, and the docs should say so rather than
  imply otherwise.
- **The orphan drill** (`tests/test_orphan_drill.py`, 139 lines, and the whole `pytest -m
  serial` tier). It proves a stranger can resurrect a poster from a packed plate. That is
  precisely the scenario being retired.
- **The seven frozen fixtures** (226 lines) and the rev test suites
  (`test_relief_rev.py` 218, `test_profile_rev.py` 204).

### 6. What survives

`/api/reprint`, `/api/continue`, the embedded manifest, editions and lineage, determinism,
proof→final fidelity, the plate-hash record, and the manifest key `trailprint` — a stable
key still matters for opening one's own old files, it just is not a public contract.

---

## Downstream: the marketing claim

"Reprint Forever" is load-bearing in `docs/marketing.md` — the trust block (:128), the
reprint promise (:165), the claim row *"Lose everything but the file? Reprint it in 2035.
We promise."* (:44), and the rationale for free plates (:73). `CLAUDE.md` requires every
marketing claim to have a test behind it. Removing the tests **requires** removing the
claim; leaving the copy up while deleting the fixtures would be exactly the dishonesty that
rule exists to prevent.

Rewrite toward what stays true: the file carries its own recipe, and the press can reprint
or extend it. `docs/scope.md`'s second pillar ("the file is the whole record") survives in
weakened form; the third ("the record is alive") is untouched.

---

## Consequences for work already planned

`docs/superpowers/plans/2026-07-27-per-role-font-seam.md` was built around this contract and
gets materially smaller: no `type_rev`, no cache-key masking for it, no endpoint or client
plumbing. The role table simply changes. Revised alongside this decision.

## Not decided here

Whether to record the bound faces in the manifest for the record. Cheap and informative, and
with the promise gone it is a note rather than a guarantee. Deferred until the font seam
lands.
