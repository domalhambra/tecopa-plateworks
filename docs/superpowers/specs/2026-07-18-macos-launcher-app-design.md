# macOS Launcher App (TrailPrint.app) — Design

**Date:** 2026-07-18
**Status:** Approved by Dom (brainstorming session)

## Goal

Make TrailPrint launchable like a Mac app: double-click `TrailPrint.app`, the engine
starts, the existing browser UI opens. Quit the app, the engine stops. Personal-use
build for this machine — not a distributable.

## Requirements (from brainstorming)

1. **Launcher + browser** — the app starts the engine and opens the existing UI in the
   default browser. No embedded web view, no native UI rewrite.
2. **Points at the repo** — the app runs the engine from this repo's `.venv`. No
   frozen/bundled Python. `git pull` changes app behavior with no rebuild.
3. **Quit app = stop engine** — the app stays in the Dock while the engine runs; Cmd-Q
   shuts the engine down cleanly. Launching (or clicking the Dock icon) while already
   running reopens the browser tab.

## Non-goals

- Distribution to other machines (no Developer ID signing, no notarization, no DMG).
- Embedded window/WebView, menu bar utility, login item, auto-update.
- Bundling Python or dependencies inside the .app.

## Approach

A minimal single-file Swift AppKit launcher, compiled by a repo build script with
`swiftc` (Xcode toolchain already installed — no Xcode project, no third-party tools).
Chosen over an AppleScript stay-open applet (PID-file process management, weak error
handling, force-quit orphans the engine) and a Platypus wrapper (external tool
dependency, shell-trap shutdown).

The launcher owns uvicorn as a **true child process**, which is what makes
quit-to-stop solid: no PID files, no orphan detection heuristics.

## Components

All new files live under `scripts/macos/`:

| File | Purpose |
|---|---|
| `TrailPrintLauncher.swift` | The launcher (~100 lines): spawn engine, wait ready, open browser, own lifecycle |
| `Info.plist.template` | Bundle metadata; placeholders for repo path + version, filled by the build script |
| `icon.png` | 1024×1024 icon source (derived from a poster render terrain crop), committed |
| `build_app.sh` | Compile Swift → assemble `dist/TrailPrint.app` → icns via `sips`/`iconutil` → bake repo path → ad-hoc `codesign` → optional `--install` copy to /Applications |
| `smoke_test.sh` | End-to-end launch/ready/quit verification (see Verification) |

`dist/` is gitignored. README gains a short "macOS app" subsection under Setup.

## Launch flow

1. Launcher reads the repo path from its own Info.plist (key `TrailPrintRepoPath`,
   baked at build time by `build_app.sh`).
2. Preflight: repo path exists and `<repo>/.venv/bin/python` exists — else a native
   alert (see Error handling) and quit.
3. Probe `http://127.0.0.1:8848/readyz` with a short timeout. If it responds **and the
   JSON body carries the engine's `ready`/`regions` keys**, an engine is already
   serving — skip spawning, open the browser, stay running in adopt mode (quit then
   closes nothing it doesn't own). A response without that shape is a foreign process
   squatting the port: alert and quit rather than opening a browser on the wrong
   service.
4. Otherwise spawn: `<repo>/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1
   --port 8848`, **cwd = repo root** (the engine mounts `app/static` and `regions/`
   relative to cwd). stdout/stderr append to `~/Library/Logs/TrailPrint.log`.
5. Poll `/readyz` up to 60 s (geo imports take a few seconds). The engine counts as
   *up* on **any HTTP response — 200 or 503**: 503 means "serving, but a region can't
   render," and the UI is where region health is communicated. Then open
   `http://127.0.0.1:8848/` in the default browser via NSWorkspace.
6. No window. Dock icon + minimal app menu (About / Quit). Activation policy
   `.regular` so Cmd-Q and Dock presence behave like a normal app.

**Port 8848** is TrailPrint's dedicated port (Everest in meters) — deliberately not
8000, so a hand-started dev server never collides with the app.

## Quit / reopen / failure behavior

- **Cmd-Q / Quit:** SIGTERM to the child (uvicorn shuts down gracefully), wait up to
  5 s, SIGKILL if still alive, then exit.
- **Dock icon click while running** (`applicationShouldHandleReopen`): reopen the
  browser tab at the engine URL. macOS single-instancing means a second double-click
  lands here too.
- **Engine exits unexpectedly** (terminationHandler while not quitting): native alert
  pointing at `~/Library/Logs/TrailPrint.log`, then the app quits.
- **Launcher force-killed (SIGKILL):** the child can orphan. Accepted for a
  personal tool — the next launch finds 8848 responding and adopts (step 3), so the
  UI keeps working; the orphan dies at logout/reboot or by hand.

## Error handling (all native alerts, never silence)

| Condition | Alert says |
|---|---|
| Repo path missing (folder moved/renamed) | Path it looked for + "rebuild with `scripts/macos/build_app.sh --install`" |
| `.venv` or its python missing | The README setup command to create it |
| `/readyz` never responds within 60 s | Points at the log file; app quits |
| Engine dies mid-session | Points at the log file; app quits |
| Port 8848 held by a non-TrailPrint process | HTTP-responding squatter → "port in use by another app" alert + quit (adopt-probe shape check); non-HTTP holder → uvicorn bind failure → engine-died alert + log |

## Icon

1024×1024 PNG derived from an existing poster render (terrain crop). Committed at
`scripts/macos/icon.png`; `build_app.sh` generates the `.icns` iconset from it. Swap
the PNG and rebuild to change the icon.

## Verification

`scripts/macos/smoke_test.sh` (run locally, not CI — it needs this machine's venv and
a GUI session):

0. Pre-check: port 8848 is free — else fail fast with a clear message (an occupied
   port would put the launch into adopt mode and make the quit-to-stop asserts fail
   confusingly).
1. `build_app.sh` produces `dist/TrailPrint.app`.
2. `open dist/TrailPrint.app` → poll `http://127.0.0.1:8848/readyz` until it responds
   (bounded wait) — asserts launch + ready.
3. `osascript -e 'quit app "TrailPrint"'` → assert the uvicorn process is gone and
   port 8848 no longer accepts connections — asserts quit-to-stop.

Manual checks (once): Dock icon appears, clicking it reopens the tab, renaming `.venv`
produces the setup alert.

## Decision record

- Port **8848**, localhost-only bind.
- Log at `~/Library/Logs/TrailPrint.log` (Console.app-readable).
- Ad-hoc codesign only; the app never leaves this machine, so no notarization.
- Repo path baked at build time rather than discovered at runtime — an alert on a
  moved repo beats a heuristic search that guesses wrong.
- Bundle version = `git describe --always --dirty` at build time (purely cosmetic;
  shown in About and Info.plist).
