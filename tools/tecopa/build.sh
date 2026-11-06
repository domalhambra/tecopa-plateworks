#!/usr/bin/env bash
# Build (and optionally install) the tecopa tool.
# Usage: tools/tecopa/build.sh [--install | --bundle-helper <out path>]
#
# --bundle-helper builds the copy that ships in the app's Contents/Helpers/tecopa.
# It bakes no repo path, so it finds the app from its own path (phase 2 spec,
# decision 5), and copies the binary to <out path>.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
USAGE="usage: tools/tecopa/build.sh [--install | --bundle-helper <out path>]"
INSTALL=0
HELPER_OUT=""
case "${1:-}" in
  "") ;;
  --install) INSTALL=1 ;;
  --bundle-helper)
    HELPER_OUT="${2:-}"
    if [[ -z "$HELPER_OUT" ]]; then echo "$USAGE" >&2; exit 2; fi
    ;;
  *) echo "$USAGE" >&2; exit 2 ;;
esac

if [[ -n "$HELPER_OUT" ]]; then
  echo "Building the app's tecopa helper (no baked repo path)"
  # Without TECOPA_BAKED, Baked.swift's defaults compile: no repo, version "dev".
  swift build --package-path "$SCRIPT_DIR" -c release
  BIN="$(swift build --package-path "$SCRIPT_DIR" -c release --show-bin-path)/tecopa"
  mkdir -p "$(dirname "$HELPER_OUT")"
  # remove first: macOS caches the signature of a binary by path
  rm -f "$HELPER_OUT"
  cp "$BIN" "$HELPER_OUT"
  echo "Helper: $HELPER_OUT"
  exit 0
fi

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
