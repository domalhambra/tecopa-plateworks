#!/usr/bin/env bash
# Register the tecopa MCP server in the Claude desktop app.
# Usage: tools/tecopa/register_desktop.sh
#
# Quit the Claude desktop app first, and run this from Terminal. A running app
# writes its own copy of the config file about once a minute, and that copy drops
# an entry added from outside. Claude Code is registered another way:
# `claude mcp add --scope user tecopa -- ~/.local/bin/tecopa mcp`.
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "usage: tools/tecopa/register_desktop.sh" >&2
  exit 2
fi

BIN="$HOME/.local/bin/tecopa"
DEFAULT_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
# TECOPA_DESKTOP_CONFIG is for a test on a copy of the file.
CONFIG="${TECOPA_DESKTOP_CONFIG:-$DEFAULT_CONFIG}"

if [[ ! -x "$BIN" ]]; then
  echo "No tecopa binary at $BIN. Run tools/tecopa/build.sh --install first." >&2
  exit 1
fi
if [[ ! -f "$CONFIG" ]]; then
  echo "No config file at $CONFIG. Start the Claude desktop app once, then quit it." >&2
  exit 1
fi
# only the app's own file is rewritten by the app. -a: pgrep leaves out its own
# ancestors by default, and a shell inside the app is a child of the app.
if [[ "$CONFIG" == "$DEFAULT_CONFIG" ]] && pgrep -a -f "^/Applications/Claude.app/Contents/MacOS/Claude" >/dev/null; then
  echo "The Claude desktop app is running. Quit it (Cmd-Q), then run this again." >&2
  exit 1
fi

BACKUP="$CONFIG.bak-$(date +%Y-%m-%d-%H%M%S)-before-tecopa"

/usr/bin/python3 - "$CONFIG" "$BIN" "$BACKUP" <<'EOF'
import json, os, shutil, sys, tempfile

config, binary, backup = sys.argv[1:4]
raw = open(config).read()
data = json.loads(raw)
servers = data.setdefault("mcpServers", {})
entry = {"command": binary, "args": ["mcp"]}

if servers.get("tecopa") == entry:
    print("Already registered: " + config)
    sys.exit(0)

shutil.copy2(config, backup)
servers["tecopa"] = entry
# the app writes two-space JSON with no final newline; keep its form
out = json.dumps(data, indent=2, ensure_ascii=False)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(config))
with os.fdopen(fd, "w") as handle:
    handle.write(out)
os.chmod(tmp, 0o600)
os.replace(tmp, config)

check = json.load(open(config))
if check["mcpServers"].get("tecopa") != entry:
    sys.exit("The entry is not in the file after the write: " + config)
print("Registered tecopa in " + config)
print("Copy before the change: " + backup)
EOF

echo "Start the Claude desktop app, then ask Claude to run the tecopa doctor tool."
