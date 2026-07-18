# macOS Launcher App (TrailPrint.app) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a double-clickable `TrailPrint.app` that starts the existing FastAPI engine from this repo's `.venv`, opens the browser UI, and stops the engine when you quit the app.

**Architecture:** A minimal single-file Swift AppKit launcher (compiled by a repo build script with `swiftc` — no Xcode project) owns `uvicorn` as a true child process. On launch it validates the repo/venv, spawns the engine on port 8848 with the repo as its working directory, polls `/readyz`, and opens `http://127.0.0.1:8848/`. Cmd-Q sends SIGTERM (then SIGKILL) to the child. The app runs the engine *from the repo*, so `git pull` updates behavior with no rebuild.

**Tech Stack:** Swift/AppKit (launcher), Bash (build + smoke test), Python/Pillow (icon generation, already a core dependency), macOS `swiftc`/`sips`/`iconutil`/`codesign` (all confirmed present).

**Spec:** `docs/superpowers/specs/2026-07-18-macos-launcher-app-design.md`

**Verification note (read before starting):** This is a GUI launcher plus shell tooling, not a library — classic unit-TDD doesn't fit. The executable acceptance test is `scripts/macos/smoke_test.sh`, which launches the built app, asserts `/readyz` responds, quits via AppleScript, and asserts the engine process and port are gone. That script is the "test" this plan is written against; Task 6 runs it as the gate. Two facts already de-risked in the scratchpad during planning: (a) `swiftc -O` compiles a single-file top-level AppKit program to an arm64 binary with no extra flags, and (b) the Pillow→`sips`→`iconutil` icon pipeline produces a valid `.icns`.

**Ground truth confirmed during planning:**
- Engine entry point: `app.main:app` (`app/main.py:60`), started with `python -m uvicorn app.main:app`.
- `/readyz` returns HTTP 200 when all regions are ready, 503 otherwise, both with JSON `{"ready": ..., "regions": [...]}` (`app/main.py:322`). "Engine is up" = *any* HTTP response; adopting an existing engine additionally requires the `ready`/`regions` keys.
- Engine mounts `app/static` and `regions/` **relative to the working directory**, so the child's cwd must be the repo root.
- Port 8848 is unused anywhere in the repo (deliberate: not 8000, so a hand-started dev server never collides).
- venv interpreter: `<repo>/.venv/bin/python`; `uvicorn` (0.49) and `Pillow` (12.2) both import from it.
- The repo path contains spaces (`…/Badwater OS/Badwater Trails`) — every shell reference must be quoted; Swift's `Process` argument array handles spaces natively.

---

## File Structure

All new files under `scripts/macos/` except the `.gitignore` and `README.md` edits:

| File | Responsibility |
|---|---|
| `scripts/macos/TrailPrintLauncher.swift` | The launcher: preflight, spawn engine, poll ready, open browser, own quit lifecycle |
| `scripts/macos/Info.plist.template` | Bundle metadata; `__REPO_PATH__` / `__VERSION__` placeholders filled at build time |
| `scripts/macos/make_icon.py` | Pillow: crop a region overview to a native rounded-rect 1024px icon |
| `scripts/macos/icon.png` | Committed 1024px icon master (output of `make_icon.py`) |
| `scripts/macos/build_app.sh` | Compile → assemble `dist/TrailPrint.app` → `.icns` → bake plist → ad-hoc sign → optional `--install` |
| `scripts/macos/smoke_test.sh` | End-to-end launch / ready / quit-to-stop acceptance test |
| `.gitignore` | Add `/dist/` |
| `README.md` | Add a "macOS app" subsection under Setup |

`dist/TrailPrint.app` is a build artifact (gitignored).

---

## Task 1: Scaffold — directory, gitignore, README

**Files:**
- Create: `scripts/macos/` (directory)
- Modify: `.gitignore` (append `/dist/`)
- Modify: `README.md` (add subsection after the Setup block, before Layout)

- [ ] **Step 1: Create the directory**

Run: `mkdir -p "scripts/macos"`

- [ ] **Step 2: Ignore the build artifact**

Append to `.gitignore` (after the `assets/` block at the end):

```
# built macOS launcher app (scripts/macos/build_app.sh)
/dist/
```

- [ ] **Step 3: Document it in the README**

Insert this subsection in `README.md` immediately after the Setup fenced block (the `import rasterio…` check) and its two bullet points, before `## Layout`:

```markdown
## macOS app (TrailPrint.app)

Build a double-clickable launcher that starts the engine and opens the UI:

```
scripts/macos/build_app.sh --install     # builds dist/ and copies to /Applications
```

Double-click **TrailPrint** in `/Applications`: the engine starts from this repo's
`.venv` on port 8848 and the UI opens in your default browser. Quit the app (Cmd-Q)
to stop the engine; relaunching while it's already running just reopens the tab. The
app runs the engine *from this repo*, so `git pull` updates it with no rebuild —
rebuild only if you move the repo folder or change the launcher itself. Engine output
logs to `~/Library/Logs/TrailPrint.log`. Verify end-to-end with
`scripts/macos/smoke_test.sh` (needs port 8848 free).
```

- [ ] **Step 4: Commit**

```bash
git add .gitignore README.md
git commit -m "macos-app: scaffold scripts/macos, ignore dist/, document launcher"
```

---

## Task 2: Icon generator + committed master

**Files:**
- Create: `scripts/macos/make_icon.py`
- Create: `scripts/macos/icon.png` (generated, committed)

- [ ] **Step 1: Write the icon generator**

Create `scripts/macos/make_icon.py` (proven working in planning):

```python
#!/usr/bin/env python3
"""Generate a macOS app icon (1024px, native rounded-rect) from a region overview.

Usage: python scripts/macos/make_icon.py <source.png> <out.png>
Default source is the Tushar Mountains relief overview. Swap the source (any
regions/<id>/overview.png) and rerun to rebrand the icon, then rebuild the app.
"""
import sys
from PIL import Image, ImageDraw

DEFAULT_SRC = "regions/tushar_beaver_ut/overview.png"
CANVAS = 1024
INSET = 100                        # transparent padding around the tile
TILE = CANVAS - 2 * INSET          # 824
RADIUS = round(TILE * 0.2237)      # Apple-ish continuous corner radius


def main() -> None:
    src_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    out_path = sys.argv[2] if len(sys.argv) > 2 else "scripts/macos/icon.png"

    src = Image.open(src_path).convert("RGB")
    w, h = src.size
    s = min(w, h)
    left, top = (w - s) // 2, (h - s) // 2
    src = src.crop((left, top, left + s, top + s)).resize((TILE, TILE), Image.LANCZOS)

    mask = Image.new("L", (TILE, TILE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, TILE - 1, TILE - 1], radius=RADIUS, fill=255)

    canvas = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    canvas.paste(src, (INSET, INSET), mask)
    canvas.save(out_path)
    print("wrote", out_path, canvas.size)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate the icon master**

Run: `.venv/bin/python scripts/macos/make_icon.py`
Expected: `wrote scripts/macos/icon.png (1024, 1024)` and a `scripts/macos/icon.png` on disk.

- [ ] **Step 3: Eyeball it**

Run: `open scripts/macos/icon.png`
Expected: a rounded-rect terrain-relief tile centered on transparent padding. (If you'd rather use a different region, rerun Step 2 with `… make_icon.py regions/<id>/overview.png scripts/macos/icon.png`.)

- [ ] **Step 4: Commit**

```bash
git add scripts/macos/make_icon.py scripts/macos/icon.png
git commit -m "macos-app: icon generator + committed 1024px master"
```

---

## Task 3: Info.plist template

**Files:**
- Create: `scripts/macos/Info.plist.template`

- [ ] **Step 1: Write the template**

Create `scripts/macos/Info.plist.template`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>TrailPrint</string>
  <key>CFBundleDisplayName</key><string>TrailPrint</string>
  <key>CFBundleIdentifier</key><string>guide.badwater.trailprint</string>
  <key>CFBundleExecutable</key><string>TrailPrint</string>
  <key>CFBundleIconFile</key><string>TrailPrint</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>__VERSION__</string>
  <key>CFBundleVersion</key><string>__VERSION__</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSUIElement</key><false/>
  <key>TrailPrintRepoPath</key><string>__REPO_PATH__</string>
</dict>
</plist>
```

Notes: `CFBundleIconFile` `TrailPrint` matches the `.icns` the build writes to `Resources/TrailPrint.icns`. `LSUIElement` false keeps the Dock icon. `TrailPrintRepoPath` is the seam the launcher reads at runtime.

- [ ] **Step 2: Commit**

```bash
git add scripts/macos/Info.plist.template
git commit -m "macos-app: Info.plist template with repo-path/version seams"
```

---

## Task 4: The launcher (TrailPrintLauncher.swift)

**Files:**
- Create: `scripts/macos/TrailPrintLauncher.swift`

- [ ] **Step 1: Write the launcher**

Create `scripts/macos/TrailPrintLauncher.swift`:

```swift
import AppKit
import Foundation

// ---- Constants ----
let kPort = 8848
let kBaseURL = "http://127.0.0.1:8848/"
let kReadyURL = "http://127.0.0.1:8848/readyz"
let kLogPath = NSHomeDirectory() + "/Library/Logs/TrailPrint.log"

// ---- Small helpers ----

func onMain(_ block: @escaping () -> Void) { DispatchQueue.main.async(execute: block) }

func logLine(_ msg: String) {
    let line = "[\(Date())] \(msg)\n"
    guard let fh = FileHandle(forWritingAtPath: kLogPath) else { return }
    fh.seekToEndOfFile()
    fh.write(line.data(using: .utf8)!)
    try? fh.close()
}

func openBrowser() { NSWorkspace.shared.open(URL(string: kBaseURL)!) }

func showAlert(_ title: String, _ text: String) {
    let a = NSAlert()
    a.messageText = title
    a.informativeText = text
    a.alertStyle = .critical
    a.addButton(withTitle: "OK")
    NSApp.activate(ignoringOtherApps: true)
    a.runModal()
}

/// Synchronous HTTP GET. Returns (data, hadResponse). `hadResponse` is true for ANY
/// HTTP reply (200 or 503); false only when the connection is refused/timed out.
/// MUST be called off the main thread.
func httpGet(_ urlString: String, timeout: TimeInterval) -> (Data?, Bool) {
    var data: Data?
    var hadResponse = false
    let sem = DispatchSemaphore(value: 0)
    let cfg = URLSessionConfiguration.ephemeral
    cfg.timeoutIntervalForRequest = timeout
    cfg.timeoutIntervalForResource = timeout
    let session = URLSession(configuration: cfg)
    let task = session.dataTask(with: URL(string: urlString)!) { d, r, _ in
        if r != nil { hadResponse = true; data = d }
        sem.signal()
    }
    task.resume()
    _ = sem.wait(timeout: .now() + timeout + 1)
    session.finishTasksAndInvalidate()
    return (data, hadResponse)
}

enum ServingState { case trailprint, foreign, none }

/// Is something already serving on the port, and is it TrailPrint?
func probeExisting(timeout: TimeInterval) -> ServingState {
    let (data, hadResponse) = httpGet(kReadyURL, timeout: timeout)
    if !hadResponse { return .none }
    if let d = data,
       let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
       obj["ready"] != nil, obj["regions"] != nil {
        return .trailprint
    }
    return .foreign
}

// ---- App delegate ----

final class AppDelegate: NSObject, NSApplicationDelegate {
    var engine: Process?
    var ownsEngine = false
    var isQuitting = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        ensureLogFile()
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in self?.boot() }
    }

    func ensureLogFile() {
        let fm = FileManager.default
        let dir = NSHomeDirectory() + "/Library/Logs"
        if !fm.fileExists(atPath: dir) {
            try? fm.createDirectory(atPath: dir, withIntermediateDirectories: true)
        }
        if !fm.fileExists(atPath: kLogPath) {
            fm.createFile(atPath: kLogPath, contents: nil)
        }
    }

    func die(_ title: String, _ text: String) {
        onMain { showAlert(title, text); NSApp.terminate(nil) }
    }

    func boot() {
        // 1. Repo path baked at build time
        guard let repo = Bundle.main.object(forInfoDictionaryKey: "TrailPrintRepoPath") as? String,
              !repo.isEmpty else {
            die("TrailPrint can’t find its files",
                "No repository path is baked into this app. Rebuild it with:\n\nscripts/macos/build_app.sh --install")
            return
        }
        let py = repo + "/.venv/bin/python"
        let fm = FileManager.default

        // 2. Preflight
        if !fm.fileExists(atPath: repo) {
            die("TrailPrint can’t find its files",
                "The project folder isn’t where it was when this app was built:\n\n\(repo)\n\nRebuild with scripts/macos/build_app.sh --install after moving it back or rebuilding in place.")
            return
        }
        if !fm.fileExists(atPath: py) {
            die("TrailPrint isn’t set up yet",
                "No Python environment was found at:\n\n\(py)\n\nCreate it first:\n  python3 -m venv .venv && source .venv/bin/activate\n  pip install -r requirements-lock.txt")
            return
        }

        // 3. Already serving?
        switch probeExisting(timeout: 0.7) {
        case .trailprint:
            logLine("adopting engine already serving on \(kPort)")
            onMain { openBrowser() }
            return
        case .foreign:
            die("Port \(kPort) is in use",
                "Another program is already using port \(kPort). Quit it, then relaunch TrailPrint.")
            return
        case .none:
            break
        }

        // 4. Spawn the engine
        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "\(kPort)"]
        p.currentDirectoryURL = URL(fileURLWithPath: repo)
        if let fh = FileHandle(forWritingAtPath: kLogPath) {
            fh.seekToEndOfFile()
            p.standardOutput = fh
            p.standardError = fh
        }
        p.terminationHandler = { [weak self] proc in
            guard let self = self, !self.isQuitting else { return }
            self.die("TrailPrint’s engine stopped",
                     "The rendering engine exited unexpectedly (status \(proc.terminationStatus)).\n\nSee the log:\n\(kLogPath)")
        }
        logLine("starting engine: \(py) -m uvicorn app.main:app --port \(kPort) (cwd=\(repo))")
        do {
            try p.run()
        } catch {
            die("TrailPrint couldn’t start its engine",
                "\(error.localizedDescription)\n\nSee the log:\n\(kLogPath)")
            return
        }
        engine = p
        ownsEngine = true

        // 5. Poll readiness up to 60s (any HTTP response counts as up)
        let deadline = Date().addingTimeInterval(60)
        while Date() < deadline {
            if isQuitting { return }
            if !p.isRunning { return } // terminationHandler shows the alert
            let (_, hadResponse) = httpGet(kReadyURL, timeout: 1.0)
            if hadResponse {
                logLine("engine ready")
                onMain { openBrowser() }
                return
            }
            Thread.sleep(forTimeInterval: 0.5)
        }
        die("TrailPrint took too long to start",
            "The engine didn’t become ready within 60 seconds.\n\nSee the log:\n\(kLogPath)")
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openBrowser()
        return true
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        isQuitting = true
        if ownsEngine, let p = engine, p.isRunning {
            logLine("quitting: SIGTERM to engine")
            p.terminate() // SIGTERM
            let deadline = Date().addingTimeInterval(5)
            while p.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.1) }
            if p.isRunning {
                logLine("engine still alive after 5s; SIGKILL")
                kill(p.processIdentifier, SIGKILL)
            }
        }
        return .terminateNow
    }
}

// ---- Bootstrap ----

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)

// Minimal main menu so Cmd-Q and About work.
let mainMenu = NSMenu()
let appItem = NSMenuItem()
mainMenu.addItem(appItem)
let appMenu = NSMenu()
appItem.submenu = appMenu
appMenu.addItem(withTitle: "About TrailPrint",
                action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
appMenu.addItem(NSMenuItem.separator())
appMenu.addItem(withTitle: "Quit TrailPrint",
                action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
app.mainMenu = mainMenu

app.activate(ignoringOtherApps: true)
app.run()
```

- [ ] **Step 2: Sanity-compile it standalone (fast feedback before the build script exists)**

Run: `swiftc -O -o /tmp/trailprint-launcher-check "scripts/macos/TrailPrintLauncher.swift" && echo COMPILE_OK && rm -f /tmp/trailprint-launcher-check`
Expected: `COMPILE_OK` with no warnings/errors. (Proven in planning that single-file top-level AppKit compiles with no extra flags.)

- [ ] **Step 3: Commit**

```bash
git add scripts/macos/TrailPrintLauncher.swift
git commit -m "macos-app: Swift launcher (spawn engine, poll ready, quit-to-stop)"
```

---

## Task 5: Build script

**Files:**
- Create: `scripts/macos/build_app.sh`

- [ ] **Step 1: Write the build script**

Create `scripts/macos/build_app.sh`:

```bash
#!/usr/bin/env bash
# Build (and optionally install) TrailPrint.app — a launcher for the local engine.
# Usage: scripts/macos/build_app.sh [--install]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
INSTALL=0
[[ "${1:-}" == "--install" ]] && INSTALL=1

VERSION="$(git -C "$REPO" describe --always --dirty 2>/dev/null || echo dev)"
APP="$REPO/dist/TrailPrint.app"
MACOS_DIR="$APP/Contents/MacOS"
RES_DIR="$APP/Contents/Resources"

echo "Building TrailPrint.app  (version $VERSION)"
echo "  repo: $REPO"

rm -rf "$APP"
mkdir -p "$MACOS_DIR" "$RES_DIR"

# 1. Compile the launcher
swiftc -O -o "$MACOS_DIR/TrailPrint" "$SCRIPT_DIR/TrailPrintLauncher.swift"

# 2. icon.png -> Resources/TrailPrint.icns
ICONSET="$(mktemp -d)/TrailPrint.iconset"
mkdir -p "$ICONSET"
for sz in 16 32 64 128 256 512; do
  sips -z "$sz" "$sz" "$SCRIPT_DIR/icon.png" --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null
  d=$(( sz * 2 ))
  sips -z "$d" "$d" "$SCRIPT_DIR/icon.png" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$RES_DIR/TrailPrint.icns"

# 3. Info.plist — bake the absolute repo path + version (delimiter '|' is safe:
#    the repo path contains no '|', only spaces, which sed passes through verbatim)
sed -e "s|__REPO_PATH__|$REPO|g" -e "s|__VERSION__|$VERSION|g" \
  "$SCRIPT_DIR/Info.plist.template" > "$APP/Contents/Info.plist"

# 4. Ad-hoc code-sign (local machine only; no Developer ID / notarization)
codesign --force --deep --sign - "$APP"

echo "Built: $APP"

if [[ "$INSTALL" == 1 ]]; then
  rm -rf "/Applications/TrailPrint.app"
  cp -R "$APP" "/Applications/TrailPrint.app"
  echo "Installed: /Applications/TrailPrint.app"
fi
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x scripts/macos/build_app.sh`

- [ ] **Step 3: Build once**

Run: `scripts/macos/build_app.sh`
Expected: ends with `Built: …/dist/TrailPrint.app` and no errors.

- [ ] **Step 4: Verify the bundle is well-formed**

Run:
```bash
plutil -p "dist/TrailPrint.app/Contents/Info.plist" | grep -E "TrailPrintRepoPath|CFBundleShortVersionString"
codesign -dv "dist/TrailPrint.app" 2>&1 | grep -E "Identifier|Signature"
file "dist/TrailPrint.app/Contents/MacOS/TrailPrint"
ls "dist/TrailPrint.app/Contents/Resources/TrailPrint.icns"
```
Expected: the plist shows the correct absolute repo path and version; codesign shows the ad-hoc signature; the binary is a Mach-O arm64 executable; the `.icns` exists.

- [ ] **Step 5: Commit**

```bash
git add scripts/macos/build_app.sh
git commit -m "macos-app: build script (compile, icns, bake plist, ad-hoc sign, install)"
```

---

## Task 6: Smoke test + acceptance run

**Files:**
- Create: `scripts/macos/smoke_test.sh`

- [ ] **Step 1: Write the smoke test**

Create `scripts/macos/smoke_test.sh`:

```bash
#!/usr/bin/env bash
# End-to-end acceptance: build, launch, assert ready, quit, assert engine stopped.
# Requires port 8848 to be free (the test must own the engine it kills).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
PORT=8848
APP="$REPO/dist/TrailPrint.app"
READY="http://127.0.0.1:$PORT/readyz"

fail() { echo "FAIL: $*" >&2; exit 1; }
serving() { curl -s -o /dev/null --max-time 1 "$READY"; }  # exit 0 on any HTTP reply

# 0. Port must be free (otherwise launch adopts and quit-to-stop can't be asserted)
if serving; then fail "port $PORT is already serving — quit that instance first"; fi

# 1. Build
"$SCRIPT_DIR/build_app.sh"
[[ -d "$APP" ]] || fail "build did not produce $APP"

# 2. Launch
open "$APP"

# 3. Wait for ready (any HTTP response), up to 60s
up=0
for _ in $(seq 1 120); do
  if serving; then up=1; break; fi
  sleep 0.5
done
[[ "$up" == 1 ]] || fail "engine did not become ready within 60s (see ~/Library/Logs/TrailPrint.log)"
echo "  launch + ready: OK"

# 4. The engine process exists and we own it
pgrep -f "uvicorn app.main:app" >/dev/null || fail "no uvicorn process found after launch"
echo "  engine process present: OK"

# 5. Quit the app
osascript -e 'quit app "TrailPrint"' || true

# 6. Engine gone AND port closed within 10s
gone=0
for _ in $(seq 1 20); do
  if ! pgrep -f "uvicorn app.main:app" >/dev/null && ! serving; then gone=1; break; fi
  sleep 0.5
done
[[ "$gone" == 1 ]] || fail "engine still running after quit — quit-to-stop is broken"

echo "PASS: launch, ready, and quit-to-stop all verified"
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x scripts/macos/smoke_test.sh`

- [ ] **Step 3: Run the acceptance test**

Run: `scripts/macos/smoke_test.sh`
Expected: prints `launch + ready: OK`, `engine process present: OK`, and finally `PASS: launch, ready, and quit-to-stop all verified`.

If it fails: check `~/Library/Logs/TrailPrint.log` for the engine's own output; the most common causes are port 8848 already in use (quit the other instance) or a stale `dist/` (the script rebuilds, so this shouldn't happen).

- [ ] **Step 4: Manual checks (once, by hand — GUI behaviors the script can't assert)**

- [ ] Launch `dist/TrailPrint.app`; confirm the TrailPrint icon appears in the Dock and the browser opens to the UI.
- [ ] With it running, click the Dock icon → the browser tab reopens (no second engine spawned; `pgrep -f "uvicorn app.main:app"` still shows exactly one).
- [ ] Cmd-Q → the Dock icon disappears and `pgrep -f "uvicorn app.main:app"` returns nothing.
- [ ] Temporarily rename `.venv` (`mv .venv .venv.off`), launch → the "isn't set up yet" alert appears with the setup command; then restore (`mv .venv.off .venv`).

- [ ] **Step 5: Commit**

```bash
git add scripts/macos/smoke_test.sh
git commit -m "macos-app: end-to-end smoke test (launch/ready/quit-to-stop)"
```

---

## Task 7: Finish the branch

- [ ] **Step 1: Confirm the tree is clean and the app is installed for daily use**

Run:
```bash
git status
scripts/macos/build_app.sh --install
```
Expected: `git status` shows only the (gitignored) `dist/` untracked or nothing; the install copies to `/Applications/TrailPrint.app`.

- [ ] **Step 2: Integrate**

Use the superpowers:finishing-a-development-branch skill to choose merge / PR / cleanup for the `macos-launcher-app` branch.

---

## Out of scope (do not build)

Distribution to other machines, Developer ID signing / notarization / DMG, an embedded WebView or native UI, a menu-bar-only mode, a login item, and auto-update. These are explicit non-goals in the spec; adding them here is scope creep.
