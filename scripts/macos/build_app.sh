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
