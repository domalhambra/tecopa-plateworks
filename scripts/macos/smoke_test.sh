#!/usr/bin/env bash
# End-to-end acceptance: build, launch, assert ready, quit, assert engine stopped.
# Requires port 8848 to be free (the test must own the engine it kills).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
PORT=8848
APP="$REPO/dist/Tecopa Plateworks.app"
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
[[ "$up" == 1 ]] || fail "engine did not become ready within 60s (see ~/Library/Logs/TecopaPlateworks.log)"
echo "  launch + ready: OK"

# 4. The engine process exists and we own it
pgrep -f "uvicorn app.main:app" >/dev/null || fail "no uvicorn process found after launch"
echo "  engine process present: OK"

# 5. Quit the app. The FIRST run raises a one-time macOS Automation (TCC) prompt —
#    "<terminal> wants to control Tecopa Plateworks.app". Click Allow. If denied (or run
#    unattended so the dialog times out), the quit event never arrives; catch that
#    specific case so the failure isn't misread as a launcher bug.
if ! osascript -e 'quit app "Tecopa Plateworks"' 2>/tmp/tecopa-quit.err; then
  if grep -qiE "1743|not authoriz|not permitted" /tmp/tecopa-quit.err; then
    fail "macOS Automation permission was denied — allow your terminal to control Tecopa Plateworks under System Settings > Privacy & Security > Automation, then rerun (the launcher's own quit path is fine)"
  fi
fi

# 6. Engine gone AND port closed within 10s
gone=0
for _ in $(seq 1 20); do
  if ! pgrep -f "uvicorn app.main:app" >/dev/null && ! serving; then gone=1; break; fi
  sleep 0.5
done
[[ "$gone" == 1 ]] || fail "engine still running after quit — quit-to-stop is broken"

echo "PASS: launch, ready, and quit-to-stop all verified"
