#!/usr/bin/env bash
# The end-to-end check: build, install, then drive the real launcher.
# Phase 1: with the engine stopped, doctor names the state. With it running, the jobs
# tool answers through MCP.
# Phase 2: a final from `tecopa render final` is byte-identical to the same requests
# sent by hand.
# Phase 3: the run list and the order status answer. No plate is built here: a build
# reads the network and takes minutes.
# Phase 4: a studio report that is posted to the engine shows in `tecopa studio errors`.
# Requires port 8848 to be free, the real lassen_ca DEM, and a human for the one-time
# macOS Automation prompt on the first quit.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TECOPA="$HOME/.local/bin/tecopa"
READY="http://127.0.0.1:8848/readyz"
LAUNCHER='^/Applications/Tecopa Plateworks\.app/Contents/MacOS/TecopaPlateworks( |$)'

fail() { echo "FAIL: $*" >&2; exit 1; }
serving() { curl -s -o /dev/null --max-time 1 "$READY"; }  # exit 0 on any HTTP reply

# If the script fails after it started the engine, it still tries to stop it, so a
# failed run does not leave the launcher and the engine behind. Best effort: the
# original failure stays the exit code, and a failed stop is only reported.
STARTED=0
WORK=""
cleanup() {
  local rc=$?
  [[ -n "$WORK" ]] && rm -rf "$WORK"
  if [[ "$rc" -ne 0 && "$STARTED" == 1 ]]; then
    echo "  cleanup: stopping the engine this run started" >&2
    # --force: the test owns this engine, and a failure can leave a render job in it
    "$TECOPA" engine stop --force >/dev/null 2>&1 || echo "  cleanup: engine stop failed. Quit the launcher by hand." >&2
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# 0. The port must be free: the test must own the engine that it stops.
if serving; then fail "port 8848 already answers. Quit that engine first."; fi
if pgrep -f "$LAUNCHER" >/dev/null; then fail "the launcher is already running. Quit it first."; fi

# 1. Build and install
"$SCRIPT_DIR/build.sh" --install
[[ -x "$TECOPA" ]] || fail "build did not install $TECOPA"
echo "  build + install: OK ($("$TECOPA" --version))"

# 2. Stopped engine: doctor names the state, and the check is a warning
DOCTOR="$("$TECOPA" doctor --json)" || fail "doctor exited non-zero. Run: tecopa doctor"
grep -q "No engine answers on port 8848" <<<"$DOCTOR" \
  || fail "doctor did not report the stopped engine"
grep -q '"fail_count" : 0' <<<"$DOCTOR" \
  || fail "doctor reports a failed check. Run: tecopa doctor"
echo "  doctor with the engine stopped: OK"

# 3. Start through the launcher
STARTED=1
START="$("$TECOPA" engine start --json)" || fail "engine start failed: $START"
grep -q '"started" : true' <<<"$START" || fail "engine start did not start the engine"
STATUS="$("$TECOPA" engine status --json)" || fail "engine status failed"
grep -q '"debug" : true' <<<"$STATUS" \
  || fail "the debug gate is off. Rebuild the launcher: scripts/macos/build_app.sh --install"
echo "  engine start + debug gate: OK"

# 4. The CLI reads the debug routes
for cmd in jobs sessions caches regions; do
  OUT="$("$TECOPA" "$cmd" --json)" || fail "tecopa $cmd failed"
  grep -q '"ok" : true' <<<"$OUT" || fail "tecopa $cmd did not answer ok"
done
echo "  jobs, sessions, caches, regions: OK"

# 5. The same jobs call through MCP, as a client sends it. The server exits when
#    stdin closes and drops replies in flight, so stdin stays open for 3 seconds.
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
NOTE='{"jsonrpc":"2.0","method":"notifications/initialized"}'
CALL='{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"jobs","arguments":{}}}'
LIST='{"jsonrpc":"2.0","id":3,"method":"tools/list"}'
REPLY="$( ( printf '%s\n' "$INIT" "$NOTE" "$CALL"; sleep 3 ) | "$TECOPA" mcp )"
JOBS="$(grep '"id":2' <<<"$REPLY")" || fail "the MCP jobs tool sent no reply"
grep -q '"isError":false' <<<"$JOBS" || fail "the MCP jobs tool reported an error: $JOBS"
grep -qF '\"ok\":true' <<<"$JOBS" || fail "the MCP jobs tool did not answer ok: $JOBS"
echo "  MCP jobs tool: OK"

# 6. The tool list names the tools a client needs
REPLY="$( ( printf '%s\n' "$INIT" "$NOTE" "$LIST"; sleep 3 ) | "$TECOPA" mcp )"
TOOLS="$(grep '"id":3' <<<"$REPLY")" || fail "the MCP tools/list sent no reply"
grep -qF '"name":"doctor"' <<<"$TOOLS" || fail "tools/list does not name doctor"
grep -qF '"name":"engine_restart"' <<<"$TOOLS" || fail "tools/list does not name engine_restart"
for tool in render_final reprint continue runs_show plate_build order_status studio_errors; do
  grep -qF "\"name\":\"$tool\"" <<<"$TOOLS" || fail "tools/list does not name $tool"
done
echo "  MCP tools/list: OK"

# 7. Phase 2: the tool's final and a final made by hand are the same bytes
REPO="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
GPX="$REPO/tests/fixtures/sample.gpx"
WORK="$(mktemp -d)"
ENGINE="http://127.0.0.1:8848"
UP="$(curl -s -F "files=@$GPX" "$ENGINE/api/upload")" || fail "the upload by hand got no answer"
grep -q '"session"' <<<"$UP" || fail "the upload by hand was refused: $UP"
read -r SID X0 Y0 X1 Y1 <<<"$(/usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["session"], *d["starter_crop"])' <<<"$UP")"
CODE="$(curl -s -o /dev/null -w '%{http_code}' -F "session_id=$SID" -F "x0=$X0" -F "y0=$Y0" \
  -F "x1=$X1" -F "y1=$Y1" -F "title=Smoke test" "$ENGINE/api/proof")"
[[ "$CODE" == 200 ]] || fail "the proof by hand answered $CODE"
SUBMIT="$(curl -s -F "session_id=$SID" "$ENGINE/api/final/submit")"
grep -q '"job"' <<<"$SUBMIT" || fail "the final by hand was refused: $SUBMIT"
JID="$(/usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["job"])' <<<"$SUBMIT")"
STATE=""
for _ in $(seq 1 150); do
  STATE="$(curl -s "$ENGINE/api/jobs/$JID")"
  case "$STATE" in *'"done"'*) break ;; *'"state":"error"'*) fail "the final by hand failed: $STATE" ;; esac
  sleep 2
done
case "$STATE" in *'"done"'*) ;; *) fail "the final by hand did not end in 300 seconds: $STATE" ;; esac
curl -sf -o "$WORK/hand.png" "$ENGINE/api/jobs/$JID/result" || fail "the final by hand could not be saved"
"$TECOPA" render final --tracks "$GPX" --set "title=Smoke test" --out "$WORK/tool.png" >/dev/null \
  || fail "tecopa render final failed"
cmp -s "$WORK/hand.png" "$WORK/tool.png" || fail "the tool's final differs from the final made by hand"
"$TECOPA" render final --tracks "$GPX" --out "$WORK/tool.png" >/dev/null 2>&1 \
  && fail "tecopa wrote over an existing file"
echo "  render final, byte-identical, and no overwrite: OK"

# 8. Phase 3: the run list and the order status answer
OUT="$("$TECOPA" runs --json)" || fail "tecopa runs failed"
grep -q '"ok" : true' <<<"$OUT" || fail "tecopa runs did not answer ok"
mkdir "$WORK/order"
OUT="$("$TECOPA" order status "$WORK/order" --json)" || fail "tecopa order status failed"
grep -q '"prepared" : false' <<<"$OUT" || fail "an empty order folder is not reported as not prepared"
echo "  runs, order status: OK"

# 9. Phase 4: a studio report shows in the tool
curl -s -o /dev/null -H "Content-Type: application/json" \
  -d '{"tab":"smoketest0001","errors":[{"kind":"error","message":"smoke test error"}]}' \
  "$ENGINE/api/debug/studio" || fail "the studio report was not taken"
OUT="$("$TECOPA" studio errors --tab smoketest0001 --json)" || fail "tecopa studio errors failed"
grep -q 'smoke test error' <<<"$OUT" || fail "the studio report does not show in tecopa studio errors"
echo "  studio errors: OK"

# 10. Stop through the launcher, and the port closes
STOP="$("$TECOPA" engine stop --json)" || fail "engine stop failed: $STOP"
grep -q '"stopped" : true' <<<"$STOP" || fail "engine stop did not stop the engine"
if serving; then fail "port 8848 still answers after engine stop"; fi
STARTED=0
echo "  engine stop: OK"

echo "PASS: phases 1 to 4"
