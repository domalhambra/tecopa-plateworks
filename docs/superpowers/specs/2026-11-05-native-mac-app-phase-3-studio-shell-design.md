# Native Mac app, phase 3: the studio's native shell: design

**Date:** 2026-11-05
**Status:** Decided by Claude under Dom's standing instruction of 2026-11-05 ("Make all decisions for yourself to get to this end goal"). Phase 3a is built. Phase 3b, the area-by-area SwiftUI port, is not built: on 2026-11-05 Claude decided the web studio in the native shell is the app's studio (`docs/decisions.md`). Section 3 stays as the plan if Dom asks for a native area later.
**Extends:** the phase 1 and phase 2 specs, and the handoff `superpowers/handoffs/2026-11-05-native-mac-app.md` (phase 3).

## 1. The decision

The handoff plans a SwiftUI studio, area by area, 12 to 18 sessions. Each area must send exactly the request bodies the web studio sends, and the Order panel's approval rules must carry over unchanged.

This session splits phase 3 in two:

- **3a, the native shell (built):** the web studio runs inside the app's window, and the app gives it a Mac's menus, keys and files. Every byte the engine sees is still the web studio's.
- **3b, the native areas (planned):** each area is ported only with a person who can watch the window. The building session had no screen access to the app: Dom declined it on 2026-11-05. So no native UI is shipped that nobody has looked at.

**Why:** a ported area that renders wrong, or sends a different body, breaks a working order flow. The proof that one does not is a person looking at it beside the web studio, plus a request-body comparison. The second can be automated; the first cannot be done blind.

## 2. Phase 3a (built)

- **The studio in the window,** a `WKWebView` (phase 2, decision 2). Uploads go through the native open panel. A download lands in Downloads under its own name, never over a file, and Finder shows it. A link outside the engine opens in the browser. The page's alerts and confirms are native sheets.
- **File > Open Tracks… (⌘O)** and **Open Poster… (⇧⌘O)** click the studio's own hidden inputs (`#fileInput`, `#posterInput`). The upload is therefore the web studio's own. A command that arrives while the page loads runs once the load finishes.
- **Drag and drop:** GPX, KML, KMZ and poster PNG files dropped on the window reach the studio's drag-anywhere router (`app/static/app.js`), unchanged.
- **Go > Studio, Orders, Plates, Engine (⌘1 to ⌘4),** and Reload Studio (⌘R).
- **Open in Studio** from an order (phase 2, decision 10).

## 3. Phase 3b (planned, not built)

Order of areas, each its own change:

1. map and crop (`canvas.js`)
2. the inspector (`controls.js`, `STYLE_BOUNDS`)
3. markers and photos
4. proof and final
5. the Order panel
6. the exports (wallpapers, films, mockups)
7. the library

Each area must:

- read the studio's request bodies through the debug routes (`/api/debug/forms`). A test drives the same edits in the web studio and the native area and compares the bodies byte for byte;
- carry the studio's state keys (`STATE_KEYS` in `app/debug.py`) into the native `studio_state` report;
- be looked at by Dom, or by a session with screen access to the app, before it replaces the web area. Until then the web area stays.

## 4. What does not change

Every rule in the phase 1 and 2 specs. The engine and the web studio are untouched by 3a.
