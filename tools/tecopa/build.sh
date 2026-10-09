#!/usr/bin/env bash
# Build (and optionally install) the tecopa tool.
# Usage: tools/tecopa/build.sh [--install]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
INSTALL=0
[[ "${1:-}" == "--install" ]] && INSTALL=1

VERSION="$(git -C "$REPO" describe --always --dirty 2>/dev/null || echo dev)"
GEN="$SCRIPT_DIR/Sources/TecopaKit/Baked.generated.swift"

echo "Building tecopa  (version $VERSION)"
echo "  repo: $REPO"

# Bake the absolute repo path and the version, the same rule as the launcher: a
# clear error on a moved repo beats a search that guesses. The file is gitignored
# and compiles only under TECOPA_BAKED.
ESC_REPO="${REPO//\\/\\\\}"
ESC_REPO="${ESC_REPO//\"/\\\"}"
cat > "$GEN" <<EOF
#if TECOPA_BAKED
public let bakedRepoPath: String? = "$ESC_REPO"
public let bakedVersion: String = "$VERSION"
#endif
EOF

swift build --package-path "$SCRIPT_DIR" -c release -Xswiftc -DTECOPA_BAKED
BIN="$SCRIPT_DIR/.build/release/tecopa"
echo "Built: $BIN"

if [[ "$INSTALL" == 1 ]]; then
  mkdir -p "$HOME/.local/bin"
  # remove first: macOS caches the signature of a binary by path, and a copy over a
  # binary that has run can be killed at launch
  rm -f "$HOME/.local/bin/tecopa"
  cp "$BIN" "$HOME/.local/bin/tecopa"
  echo "Installed: $HOME/.local/bin/tecopa"
fi
