# Native Mac app, phase 2: the window, Orders, tooling and Settings: design

**Date:** 2026-11-05
**Status:** Decided by Claude under Dom's standing instruction of 2026-11-05: "Make all decisions for yourself to get to this end goal", the end goal being a fully working Tecopa Plateworks app, optimized for macOS and ready to use. Not built.
**Extends:** `2026-11-05-native-mac-app-phase-1-bundled-engine-design.md` (the bundle, the engine, the proofs) and the handoff `superpowers/handoffs/2026-11-05-native-mac-app.md` (phase 2: "Orders list and step buttons, engine status, logs, plate builder, Settings, on TecopaKit").

## 1. Goal

Dom runs a whole Tecopa order from the app alone, from the intake number to the print TIFFs. That means no terminal, no browser tab and no Claude. The studio stays the web studio for now, but it lives in the app's own window. Phase 3 replaces it area by area.

**Done means:** one real past order, copied, runs end to end in the app (the handoff's proof). The steps are New, Preview, choose the size, Prepare, open in the studio, save, approve and Finish. Every refusal shows the engine's own words.

## 2. Decisions

| # | Decision | Why |
| --- | --- | --- |
| 1 | The app becomes a SwiftUI `App` with one main window, a `NavigationSplitView`. The sidebar has Studio, Orders, Plates and Engine; Settings is a Settings scene (⌘,). | One window is the Mac shape for a single-user tool. The sidebar holds what the handoff lists. |
| 2 | **Studio** is a `WKWebView` on `http://127.0.0.1:8848/`, inside the window. The browser tab goes. | The handoff allows the web studio in a window "for any area not yet native". The window gives the studio ⌘W, full screen, the Dock, and one app to quit. |
| 3 | Every tool action goes through `Catalog.call(name, runtime, args)` in TecopaKit, the same entry points the `tecopa` CLI and MCP server use. | Swift holds no order, plate or render rule (phase 1 spec section 3). One code path for Claude and Dom. |
| 4 | `ScriptRunner` runs scripts with the **layout's** interpreters. In the bundle that is `python-engine` or `python-prep`, with cwd = the data root and the phase 1 engine environment. The allowlist table and its app/prep column stay, so invariant 13 is enforced in one place. | The app has no repo. Phase 1 left the CLI on the repo venvs (phase 1 spec 9). |
| 5 | `Runtime` resolves an `EngineLayout`: `--repo`, then `TECOPA_REPO`, then the baked repo (development builds), then the app bundle that holds the running binary, then `TECOPA_APP` / `/Applications/Tecopa Plateworks.app`. | The app and the CLI inside it find the bundle from their own path. A development CLI keeps working against the repo. |
| 6 | The `tecopa` binary ships in `Contents/Helpers/tecopa`. Settings offers "Install the tecopa command", which makes `~/.local/bin/tecopa` a symlink to it, and re-registers the MCP server. | Claude keeps its tools with no repo checkout (handoff goal). |
| 7 | Choosing a size is a script command, `scripts/order.py choose <folder> <size>`. It writes the preview's lines for that size into `order.toml`; the app never edits `order.toml`. | Changing-things step 5 says "paste the lines of the chosen size into `order.toml`". The lines and the rules live in Python. |
| 8 | The paid size comes from the order desk: `GET https://lab.plateworks.org/desk/data` with `Authorization: Bearer <DESK_API_TOKEN>`. The app reads the `records.tecopa` row whose `order_id` is the order number, and its `size` and `paid` columns. It only **reads**, and never taps. | Dom's answer to the handoff's question (2026-11-05). |
| 9 | The desk token lives in the login Keychain, service `plateworks-lab-desk-api-token`, account `dom`. Settings writes it there with `SecItemAdd`; nothing writes it to a file. Without it, Orders says "Paid size: not connected (add the desk token in Settings)" and Dom chooses the size by hand. | The workspace rule: secrets in the Keychain, never in a file or chat. |
| 10 | "Open in studio" switches to Studio and loads `http://127.0.0.1:8848/?order=<folder name>`. A small studio change reads that parameter, selects the order in the Order panel and presses Open. | One click from an order to its proof. The Order panel's approval rules stay exactly as they are (the handoff's rule). |
| 11 | Copy email puts `out/preview/email.txt` on the pasteboard; Reveal opens Finder. Nothing sends an email. | The handoff's rule. |
| 12 | Plates shows each plate: ready, DEM cached or not, DRIFT, size. It offers verify, **Restore from Dropbox** and **Free space** (evict) per plate, plus Build a new plate (`plate_plan`, then `plate_build`). Restore and evict follow phase 1 spec section 6 exactly: restore by `index.json` `current`; never evict under an order run. | The phase 1 cache design, made usable. |
| 13 | Engine shows doctor's rows, engine status, a live log tail with a filter, the caches, and the runs with Cancel. | The handoff's "native tooling". |
| 14 | Settings edits `settings.json` (orders folder, intake folder, a font file per type role) and the desk token. It shows whether the Red River profiles are installed, and offers "Restart the engine" when a setting the engine reads at start has changed. | Phase 1 left `settings.json` hand-edited. |
| 15 | Long runs (Prepare, Preview, Finish, plate builds) show a progress row from the run record (`runs_show`), polled every 2 s while visible. | TecopaKit already tracks runs. |

## 3. Non-goals

The native studio (phase 3). The signed release (phase 4). Sending email. Track deletion: it still waits for Dom's decision on the privacy rule.

## 4. What must not break

Every phase 1 rule. The Order panel's approval semantics, unchanged: Approve works only on a proof saved in this session and unchanged since. The intake folder stays read-only. Invariant 13. No font in the bundle.

## 5. Proof

A copy of a real past order from `~/Library/Application Support/Tecopa Plateworks/Orders/` runs end to end in the app, from New to Finish, with the PRINT.txt shown. Each step's refusal is checked once by making it happen: Finish before Approve says "Approve the proof in the studio first."
