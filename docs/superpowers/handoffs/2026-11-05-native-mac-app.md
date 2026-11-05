# Handoff: Tecopa Plateworks as a native Mac app

**Date:** 2026-11-05
**From:** a Claude project thread ("Package Tecopa as a native Mac app"), assessment only, no code.
**For:** a Claude Code session on Dom's Mac that designs and builds the app.
**Decision:** Dom chose the SwiftUI shell, a native studio, and native tooling (2026-11-05). The
other options and why they lost are under "Options Dom weighed" below.

## The goal in Dom's words

"How do we package Tecopa as a Mac-assed native app that I can start using myself without
relying on Claude to do everything? What's left to make it its own app?" Then: build "this
native studio, shell and the native tooling."

Success means Dom runs a whole Tecopa order alone, from the intake number to the print TIFFs,
in one Mac app he installs from a signed disk image. No terminal, no repo checkout, no venv,
no browser tab. Claude can still help through the `tecopa` tool and its MCP tools, but nothing
needs it.

## Start here

1. Read `CLAUDE.md` (the router and the 15 invariants), then `README.md`,
   `docs/architecture.md`, and this file.
2. Read the two specs this work extends:
   `docs/superpowers/specs/2026-07-18-macos-launcher-app-design.md` (the launcher, port 8848,
   engine ownership, the Documents prompt) and
   `docs/superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md` (the `tecopa` tool and
   TecopaKit).
3. Read Desqueeze, Dom's shipped SwiftUI app, for patterns: `plateworks-desqueeze`
   `CLAUDE.md`, `project.yml` (XcodeGen, not sandboxed, no entitlements file),
   `App/PlateworksDesqueeze/` (AppModel, BundledTools), and `scripts/make_release.sh` (sign
   inside out, notarize, staple, DMG). Copy the release script's shape.
4. Read `docs/changing-things.md` › Run an order, all of it. That is the workflow the Orders
   window replaces, step by step, with every refusal message the user must see.
5. Use the brainstorming skill and write a design spec in `docs/superpowers/specs/` before any
   code (CLAUDE.md, and the documentation standard). Add its row to `docs/README.md`.

## What exists today

| Piece | Where | Size | Role in the app |
| --- | --- | --- | --- |
| Engine | `app/` | ~18,700 lines Python | Kept as is. Bundled inside the app. Every render and order rule stays here. |
| Web studio | `app/static/` | ~6,800 lines JS | Replaced by the native studio, piece by piece. Keep it working until the native one reaches parity. |
| Plate builder | `region_prep.py`, `.venv-prep` | ~1,100 lines | Bundled as a second, separate Python environment (invariant 13). |
| Order pipeline | `scripts/order.py`, `app/order*.py` | in the engine | `new`, `preview`, `prepare`, `finish`. Driven by native buttons. |
| Launcher | `scripts/macos/` | ~240 lines Swift | Its engine-ownership logic moves into the app, then it retires. |
| `tecopa` tool | `tools/tecopa/` | ~4,200 lines in TecopaKit | TecopaKit is Foundation only: the app links it for orders, runs, plates, renders, doctor. The CLI and MCP server keep working against the app's engine. |

The studio is already a pure HTTP client of the engine. Its whole contract is the routes in
`app/main.py` (`/api/upload`, `/api/proof`, `/api/final/submit`, `/api/orders`,
`/api/order/open|save|approve|photo`, `/api/continue`, `/api/reprint`, `/api/jobs/{id}`,
`/api/regions/plan|build`, `/api/wallpapers/*`, `/api/timelapse/submit`, `/api/mockups/submit`,
`/readyz`) plus the debug router in `app/debug.py`. A native studio is a SwiftUI client of the
same routes. `app/static/api.js` lists every call and its form fields: read it first.

## Options Dom weighed

| Option | Verdict |
| --- | --- |
| Bundle only (launcher plus bundled engine, browser studio) | Too little: orders stay commands. |
| SwiftUI shell, studio in a WKWebView | Recommended first by the thread; Dom wants the studio native too. |
| **Shell plus native studio plus native tooling** | **Chosen.** |
| Full Swift port of the engine | Not realistic. GDAL, rasterio, scipy and pyproj do the terrain math, and determinism (invariant 3) depends on the pinned wheels in `requirements-lock.txt`. |

What the native studio costs, as Dom was told: about 15 more sessions than the web-view shell;
studio changes can no longer be checked from a Linux cloud session (`node --check`, headless
browser), only on the Mac; the `studio_state` and `studio_errors` reporting in
`app/static/debug.js` must be rebuilt natively (its keys must match `STATE_KEYS` in
`app/debug.py`); and the Order panel's approval rules must be carried over exactly.

## What the app must do

1. **Carry its own engine.** A relocatable Python 3.14 (python-build-standalone or similar)
   with `requirements-lock.txt` plus the two extras the README names, and a separate
   environment for `requirements-regionprep.txt`. Never mix the two (invariant 13). The app
   finds them inside its bundle, never through a repo path.
2. **Keep data outside the bundle.** Plates, caches, logs and settings in
   `~/Library/Application Support/Tecopa Plateworks/`. Orders stay in `~/Tecopa Orders/`
   (`TECOPA_ORDERS_DIR`), never inside the app or the repo: the repo is public. The Dropbox
   intake folder stays read-only (`order new` never writes there).
3. **Own the engine on port 8848.** Start it as a child process, wait on `/readyz`, stop it on
   Quit, adopt one that is already running only when `/readyz` has the engine's shape. Same
   rules as the launcher spec. The `tecopa` tool's decision 7 (one owner of the engine) now
   names the app: amend that spec in one line.
4. **Native studio.** Open tracks (GPX, KML, KMZ) and a poster PNG (reprint, continue) from
   File > Open and by drag and drop. The map view with the crop box and marker drag
   (`canvas.js`), the inspector and its controls (`controls.js`, `STYLE_BOUNDS` in
   `app/spec.py`), markers and photos, proof and final, wallpapers, films, mockups, the
   library, and the Order panel. Undo, keyboard shortcuts, VoiceOver.
5. **Orders window.** A list of orders by state (read `work/state.json`), and one button per
   step: New from a TP number, Preview (show the PDF, pick a size from the offered list,
   which writes `order.toml`; Copy email for HEY; Reveal PDF), Prepare (report, warnings
   first, soft proof), Open in studio, Save to order, Approve, Finish (show `PRINT.txt`, open
   each TIFF). Every refusal the CLI prints is shown as the engine words it. TecopaKit already
   runs these as tracked runs: reuse `Orders.swift`, `Runs.swift`, `ScriptRunner.swift`.
6. **Native tooling.** What `tecopa doctor`, `regions`, `regions verify`, `plate plan|build`,
   `logs`, `caches` and `runs` give Claude today becomes a window or a menu for Dom: an engine
   status view, a plate builder, a log viewer.
7. **Settings.** Orders folder, Dropbox intake folder, a font file per type role
   (`TECOPA_FONT_TITLE`, `_POINT`, `_AREA`, `_WATER`, `TECOPA_FONT`), and a check that the Red
   River ICC profiles are installed in `/Library/ColorSync/Profiles/`.
8. **Ship as a signed disk image.** Developer ID, hardened runtime, every `.so` and `.dylib` of
   both Python environments signed inside out, notarized and stapled, as Desqueeze does.
   Not sandboxed.

## Rules that must not break

- Every invariant in `CLAUDE.md`. The ones this work touches most: 3 (determinism: a render
  from the bundled engine must equal the venv's byte for byte), 9 (the zTXt keyword
  `trailprint` and `ENGINE` names), 10 (never commit a font, and never put one in the DMG:
  MB Type is licensed), 13 (two Python environments), 14 (the product is "Tecopa Plateworks"
  in full; Plateworks alone names the business).
- The engine keeps every rule. Swift holds no render logic, no coordinate math and no spec
  rules (the `tecopa` spec, decision 6). The native studio sends what the web studio sends.
- Proof approval: Approve works only on a proof saved in this session and unchanged since.
  The hash, "Edited since the last proof", and each Finish refusal are defined in the engine
  and `docs/changing-things.md`. Port the client side exactly; never relax one.
- Nothing sends an email or charges anyone. Copy email puts text on the clipboard; Dom sends
  from HEY.
- Customer tracks are private. The Tecopa privacy promise deletes tracks 90 days after
  delivery; no code does that yet, and the business owner of that rule is the "Tecopa
  Changes" thread in Dom's Claude project. Do not build deletion without Dom's decision.
- GitHub Actions is off for this repo (Dom, 2026-11-02). Never re-enable it.
- Commits on `claude/*` branches, squash-merged; the Mac commits to `main` only when green.
  Every pull request passes `python3 scripts/docs_check.py --impact origin/main` and ends with
  a `Docs:` line. Releases, pushes of a release, and anything signed wait for Dom's typed yes.

## Suggested order of work

Phase 1 carries the most risk: if the bundled engine cannot match the venv's render, the
plan changes before any UI is built.

| Phase | Delivers | Proof it works | Rough effort |
| --- | --- | --- | --- |
| 0. Machine | Xcode, XcodeGen, Python 3.14, both venvs, real DEMs, fonts, ICC profiles, Developer ID and notary profile in the Keychain | `pytest -n auto -q` full suite on the Mac; `scripts/verify_regions.py` | 1 session |
| 1. Bundled engine | An app bundle (XcodeGen, like Desqueeze) that starts the bundled engine and serves the existing web studio in the browser | A test poster from the bundle is byte-equal to the venv's; ad hoc signed bundle runs with the repo moved away | 2 to 3 |
| 2. Orders window and tooling | Orders list and step buttons, engine status, logs, plate builder, Settings, on TecopaKit | One real past order run end to end on a copy | 3 to 4 |
| 3. Native studio | SwiftUI studio, one area at a time: map and crop, inspector, markers and photos, proof and final, Order panel, then exports (wallpapers, films, mockups), library | Each area: the same request bodies as the web studio for the same edits; the order approval flow passes on a copy | 12 to 18 |
| 4. Signed release | `scripts/macos/make_release.sh` adapted from Desqueeze | `spctl` accepts the app and the DMG | 1 to 2 |
| 5. Retire | The browser studio and the old launcher, once Dom has run real orders in the native app | Dom's go | 1 |

During phase 3 the app can show the web studio in a window for any area not yet native, so Dom
can use the app from the end of phase 2.

## Open questions for Dom

- Curated plates: inside the app (large), or copied from Dropbox or Drive on first launch?
- Just for Dom, or a public download later? Public adds an About box, the AGPL notice and
  source offer, and an update path.
- Bundle id: keep `guide.badwater.tecopa` (no new Documents prompt) or a new `org.plateworks`
  one like Desqueeze?
- Paid size: read it from the order desk (`DESK_API_TOKEN`, in plateworks-lab-intake) or keep
  reading Stripe's email?

## Machine notes (2026-11-05)

Dom wiped his Mac on 2026-11-05. Nothing Tecopa-related is installed: no venvs, no real DEMs,
no launcher, no `tecopa` binary, no fonts. Phase 0 rebuilds that from `docs/changing-things.md`
› Set up a machine and Build a new plate. The intake's Dropbox job folders sync to
`~/Dropbox/Apps/Plateworks Lab/Tecopa/` once the Dropbox app is back.
