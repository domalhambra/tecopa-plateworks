# TrailPrint — "Reprint Forever" Continuity (design + implementation plan)

_2026-07-12 · Status: **proposed** (not yet built). The load-bearing plan of this batch:
it makes the app's headline promise true rather than aspirational. Companion:
`2026-07-12-data-licensing-and-attribution.md` (the LICENSE file this plan needs) and
`2026-07-12-product-strategy-fork.md` (which distribution model this promise lives in)._

---

## Context — the promise the artifact can't currently keep

The product's sharpest differentiator is stated three times, each as an absolute:

- `docs/scope.md`: living editions are "the sharpest differentiator TrailPrint has — no
  other track-print tool can promise 'your artifact can never be orphaned.'"
- `docs/marketing.md`: **"Reprint Forever."** / *"Lose everything but the file? Reprint it
  in 2035. We promise."* / FAQ *"What if you disappear?"* → *"your file reprints itself."*
- `README.md`: the PNG is "stateless-reprintable … from the file alone (no session, no DB)."

As built, the file reprints on exactly one class of machine: **one that already has the
region present and the engine installed and licensed.** Outside that machine the promise
fails, and it fails *silently* in development because every machine that has ever run a
reprint already had the regions. Three concrete gaps:

1. **The engine is not runnable by anyone but the operator.** There is **no `LICENSE`
   file** in the repo (verified: `ls LICENSE*` → none). Even with the code in hand, a user
   has no legal right to run it. "Your file reprints itself" today means "Dom's laptop
   reprints it."
2. **The terrain is neither in the file nor distributed.** `/api/reprint` raises a 422 —
   *"Region isn't built on this server"* (`app/main.py:927`, `_manifest_region_or_422`) —
   whenever `spec.region_id ∉ REGIONS`. The DEMs are gitignored (190–704 MB), have **no
   distribution channel**, and are rebuildable only from live USGS services. The first
   red-team already flagged the archival gap as V1-12 (*"Archive the shipped regions' raw
   source DEM/water"*) — **still not done**.
3. **The manifest doesn't record which terrain it was painted on.** `build_manifest`
   (`app/provenance.py:89`) embeds the spec, the source-GPX hashes, and the engine version
   — but **no hash of `dem.tif` / `hydro.json` / `labels.json`**. USGS re-flies 3DEP and
   revises NHD; a plate rebuilt in 2030 will not be byte-identical to the 2026 build. An
   old poster would then reprint **differently**, with no signal. The determinism tests
   can't catch this — they only ever assert same-bytes-in → same-bytes-out. The frozen
   `manifest_*_v1.json` fixtures freeze the *schema*; nothing freezes the *capability*.

The rigor already in the repo (invariants, frozen fixtures, red-team discipline) makes
this a *strategic* blind spot, not a technical one: all that rigor currently defends a
promise that stops being true one step outside the author's machine.

## The one design idea: the poster names its own resurrection recipe, and the recipe is publishable

A poster is truly un-orphanable only if, from the file alone, someone can obtain **(a) the
engine, legally, and (b) the exact plate it was painted on, verifiably** — and know when
they've got the wrong version. So:

1. **Publish the engine under a real license** (see the companion licensing plan). This is
   the precondition; "reprints itself" is meaningless if running the reprinter is illegal.
2. **Publish versioned region packs ("plates").** `sources.json` already records every
   asset's `sha256` and byte length and a one-line `rebuild` recipe. A *plate* is that
   directory plus `dem.tif`, content-addressed and downloadable — a `lassen_ca@<hash>`
   artifact. The manifest already speaks "plates" in marketing; make it a real noun.
3. **Stamp the plate identity into the manifest.** Add a `region_pack` block to
   `build_manifest`: `{ "region_id", "pack_version", "assets": {name: sha256} }` — the same
   hashes `sources.json` already computes. Purely additive (MANIFEST_VERSION stays 1; every
   frozen fixture unchanged — the exact discipline `edition`/`animation` already follow).
4. **On reprint, verify the plate.** `_manifest_region_or_422` grows one branch: region
   present **and** its asset hashes match the manifest's `region_pack` → faithful reprint.
   Region present but hashes differ → an **honest 422** naming the pack the file wants
   (*"this poster was painted on the Lassen plate v2026-07-03; this server has v2030-01-10 —
   fetch the original plate to reprint exactly"*), never a silent redraw. Region absent →
   the 422 already exists, now with a URL to the pack.
5. **Archive the raw sources (finally close V1-12).** The `dem.tif` and pre-bake NHD/NLCD
   pulls go into an object store you control, keyed by pack hash, so a plate can be rebuilt
   even if USGS changes or rate-limits. This is the difference between "reproducible in
   theory" and "reproducible in 2035."
6. **Optional, and the best Show HN copy you'll ever get:** a human-readable `tEXt` chunk
   alongside the machine `zTXt` — a few sentences telling a 2035 finder how to resurrect the
   file (where the engine lives, which plate, that it's public-domain terrain). A PNG that
   **carries the instructions for its own resurrection** is the demo of the whole thesis.

## Why this falls out of what already ships

- `sources.json` **already computes and stores** every asset's sha256 — step 3 is
  re-surfacing data the build already produces, not new machinery.
- The additive-manifest discipline is proven three times over (`edition`, `lineage`,
  `animation` are all omitted-when-absent, fixtures byte-stable). `region_pack` is the
  fourth instance of the same pattern.
- `_manifest_region_or_422` is already the single gate for reprint/continue region checks;
  the plate-hash comparison lands in exactly one function.
- The "honest 422, never a silent wrong poster" posture is the **same principle as the
  off-DEM guard** (invariant 5, registration-is-correctness): the app already refuses to
  paint invented terrain; refusing to *reprint against the wrong terrain* is the temporal
  version of the same rule.

## Concrete work, ordered

1. **`LICENSE` file** (companion plan) — unblocks everything; one commit.
2. **`region_pack` manifest block** + `spec`-adjacent plumbing in `build_manifest` /
   `spec_from_manifest`; freeze `manifest_region_pack_v1.json`. Old manifests (no block)
   still reprint — treated as "unverifiable plate," a soft warning, never a hard fail
   (forward-compat, exactly like `.get(..., [])` drift tolerance today).
3. **Plate publication**: a `scripts/pack_region.py` that zips a region dir + `dem.tif`
   into a content-addressed artifact and writes a small `plates.json` index; a documented
   place they're hosted (ties to the distribution decision in the strategy plan).
4. **Reprint plate-verification branch** in `_manifest_region_or_422` + the three humanized
   messages (match, mismatch, absent) + tests for each.
5. **Raw-source archival (V1-12)** — the object-store home for `dem.tif` + pre-bake pulls,
   keyed by pack hash.
6. **`tEXt` resurrection note** (optional, cheap, high marketing leverage).

## Invariants / risks

- **New invariant candidate:** *a faithful reprint requires a matching plate; a mismatch is
  a humanized refusal, never a silent redraw.* This extends invariant 5 across time.
- **Determinism now spans the plate, not just the spec.** The determinism test should assert
  reprint-identity *given the same pack*, and a new test should assert reprint *refuses*
  (422) when the pack hash differs.
- **Privacy unchanged:** `region_pack` carries only hashes of public-domain terrain, never
  user data; the existing `embed_spec=false` share-copy path is untouched.

## Out of scope (here)

- Which host serves the plates, and whether users self-serve them or the operator does —
  that's the `product-strategy-fork` decision.
- Global coverage / on-demand AOIs — the geo rock in the red-team roadmap; this plan makes
  the *existing four plates* permanent, which is the honest scope of "forever" today.
- Re-deriving old renders when a plate legitimately improves — the manifest *detecting* the
  difference is in scope; an automatic "re-master to the new plate" verb is a later feature.
