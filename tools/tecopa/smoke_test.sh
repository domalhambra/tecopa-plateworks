#!/usr/bin/env bash
# The phase 1 proof: build, install, then drive the real launcher end to end.
# With the engine stopped, doctor names the state. With it running, the jobs tool
# answers through MCP. Requires port 8848 to be free, and a human for the one-time
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
cleanup() {
  local rc=$?
  if [[ "$rc" -ne 0 && "$STARTED" == 1 ]]; then
    echo "  cleanup: stopping the engine this run started" >&2
    "$TECOPA" engine stop >/dev/null 2>&1 || echo "  cleanup: engine stop failed. Quit the launcher by hand." >&2
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
echo "  MCP tools/list: OK"

# 7. Stop through the launcher, and the port closes
STOP="$("$TECOPA" engine stop --json)" || fail "engine stop failed: $STOP"
grep -q '"stopped" : true' <<<"$STOP" || fail "engine stop did not stop the engine"
if serving; then fail "port 8848 still answers after engine stop"; fi
STARTED=0
echo "  engine stop: OK"

echo "PASS: phase 1 proof"
