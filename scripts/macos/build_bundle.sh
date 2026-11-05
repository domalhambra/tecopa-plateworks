#!/usr/bin/env bash
# Build dist/Tecopa Plateworks.app: the Mac app with its own Python and engine
# (native Mac app phase 1 spec 4.1, 5, 7; plan task 19).
#
#   scripts/macos/build_bundle.sh
#
# Needs: a clean tree (tracked changes only), XcodeGen, Xcode, uv, the repo's .venv
# (it runs the checks), and dist/.wheelhouse from make_bundle_locks.sh.
# Signs ad hoc. The Developer ID and the hardened runtime are phase 4, and wait for
# Dom's yes. It writes nothing outside dist/ and macos/build/.
set -euo pipefail
unset CDPATH

stop() { echo "build_bundle: $*" >&2; exit 1; }

REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$REPO"
APP="$REPO/dist/Tecopa Plateworks.app"
RES="$APP/Contents/Resources"
REPORT="$REPO/dist/build-report.txt"
CHECK=("$REPO/.venv/bin/python" -I -B "$REPO/scripts/macos/bundle_checks.py")
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20260127/cpython-3.14.2%2B20260127-aarch64-apple-darwin-install_only.tar.gz"
PBS_SHA256="e8891a012ad178d7afc0db4dcad611d6156e6402947578fc91acbbdf1930eebd"
TGZ="$REPO/dist/.downloads/cpython-3.14.2+20260127-aarch64-apple-darwin-install_only.tar.gz"
WH="$REPO/dist/.wheelhouse"
ENGINE_PATHS=(app config region_prep.py scripts/order.py scripts/build_labels.py
              scripts/dem_coverage.py scripts/bake_playa.py scripts/render_mockups.py)

# ------------------------------------------------------------- 1. Refuse
echo "1/13 Check the tree"
git diff --quiet HEAD && git diff --cached --quiet \
  || stop "The work tree is not clean. Commit tracked changes first."
[ -L "$REPO/dist" ] && stop "dist is a symlink."
[ -L "$APP" ] && stop "$APP is a symlink."
[ -d "$WH" ] || stop "No wheelhouse at $WH. Run scripts/macos/make_bundle_locks.sh."
for t in xcodegen xcodebuild uv codesign ditto; do
  command -v "$t" >/dev/null || stop "$t is not installed."
done
VERSION="$(git rev-parse --short HEAD)"
mkdir -p "$REPO/dist/.downloads"
: > "$REPORT"
echo "version $VERSION" >> "$REPORT"

# ---------------------------------------------------------- 2. Interpreter
echo "2/13 Get Python 3.14.2"
if [ ! -f "$TGZ" ]; then
  curl -fL --retry 3 -o "$TGZ.partial" "$PBS_URL"
  mv "$TGZ.partial" "$TGZ"
fi
[ "$(shasum -a 256 "$TGZ" | awk '{print $1}')" = "$PBS_SHA256" ] \
  || stop "The interpreter download does not match its pinned SHA-256."

# ---------------------------------------------------------------- 3. Build
echo "3/13 Build the app"
xcodegen generate --quiet --spec "$REPO/macos/project.yml" --project "$REPO/macos"
xcodebuild -project "$REPO/macos/TecopaPlateworks.xcodeproj" -scheme TecopaPlateworks \
  -configuration Release -derivedDataPath "$REPO/macos/build" \
  ARCHS=arm64 ONLY_ACTIVE_ARCH=NO build > "$REPO/dist/xcodebuild.log" 2>&1 \
  || stop "xcodebuild failed. See dist/xcodebuild.log."
git diff --quiet HEAD || stop "The build changed a tracked file: $(git diff --name-only HEAD | head -3)"
rm -rf "$APP"
ditto "$REPO/macos/build/Build/Products/Release/TecopaPlateworks.app" "$APP"

# ------------------------------------------------------------ 4. Version
echo "4/13 Bake the engine version $VERSION"
PB=/usr/libexec/PlistBuddy
"$PB" -c "Set :TecopaEngineVersion $VERSION" "$APP/Contents/Info.plist"
[ "$("$PB" -c 'Print :TecopaEngineVersion' "$APP/Contents/Info.plist")" = "$VERSION" ] \
  || stop "TecopaEngineVersion did not take."
[ "$("$PB" -c 'Print :CFBundleIdentifier' "$APP/Contents/Info.plist")" = "org.plateworks.tecopa" ] \
  || stop "The bundle id is not org.plateworks.tecopa."

# --------------------------------------------------- 5. Engine and plates
echo "5/13 Copy the engine and the plate files (tracked files at HEAD only)"
mkdir -p "$RES/engine" "$RES/plates"
git archive --format=tar HEAD -- "${ENGINE_PATHS[@]}" | tar -xf - -C "$RES/engine"
git archive --format=tar HEAD:regions | tar -xf - -C "$RES/plates"
[ -z "$(find "$RES/plates" -name dem.tif)" ] || stop "A dem.tif reached the bundle."
n="$(find "$RES/plates" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
[ "$n" -ge 11 ] || stop "Only $n plate folders in the bundle."
echo "plates $n" >> "$REPORT"

# ------------------------------------------------------------- 5b. Helper
echo "5b/13 Build the tecopa command that ships inside the app"
mkdir -p "$APP/Contents/Helpers"
bash "$REPO/tools/tecopa/build.sh" --bundle-helper "$APP/Contents/Helpers/tecopa" > "$REPO/dist/tecopa-build.log" 2>&1 \
  || stop "The tecopa command did not build. See dist/tecopa-build.log."

# --------------------------------------------------------------- 6. Checks
echo "6/13 Check for fonts and missing modules"
"${CHECK[@]}" fonts "$RES/engine" || stop "A font file is in the engine (invariant 10)."
"${CHECK[@]}" fonts "$RES/plates" || stop "A font file is in the plates (invariant 10)."
"${CHECK[@]}" imports "$RES/engine" || stop "The engine imports a module the bundle lacks."

# --------------------------------------------------------- 7. Two Pythons
echo "7/13 Install the two Pythons (invariant 13: never one)"
for copy in engine prep; do
  dest="$RES/python-$copy"
  tmp="$(mktemp -d)"
  tar -xzf "$TGZ" -C "$tmp"
  mv "$tmp/python" "$dest"
  rmdir "$tmp"
  py="$dest/bin/python3.14"
  [ "$("$py" -I -c 'import sys; print(sys.version.split()[0])')" = "3.14.2" ] \
    || stop "python-$copy is not 3.14.2."
  [ ! -e "$dest/lib/python3.14/EXTERNALLY-MANAGED" ] || stop "python-$copy is marked externally managed."
  uv pip install --quiet --python "$py" --no-index --find-links "$WH" --only-binary :all: \
    --no-deps --require-hashes --link-mode copy -r "$REPO/requirements-bundle-$copy.txt" \
    || stop "Installing python-$copy failed."
  "${CHECK[@]}" fonts "$dest" --allow "$REPO/scripts/macos/python_font_allowlist.txt" \
    || stop "python-$copy holds a font outside the allowlist."
done

# ------------------------------------------------------------- 8. zlib
echo "8/13 Record zlib (proof 1 compresses the manifest with it)"
{
  echo "otool -L libpython:"; otool -L "$RES/python-engine/lib/libpython3.14.dylib"
  zv="$("$RES/python-engine/bin/python3.14" -I -c 'import zlib; print(zlib.ZLIB_RUNTIME_VERSION)')"
  echo "zlib $zv"
  [ "$zv" = "1.2.12" ] || echo "WARNING: zlib $zv, the reference venv has 1.2.12"
} >> "$REPORT"

# ------------------------------------------------------------ 9. Bytecode
echo "9/13 Compile bytecode (unchecked-hash, so nothing writes into the bundle)"
for copy in engine prep; do
  "$RES/python-$copy/bin/python3.14" -I -m compileall -f -q -j0 \
    --invalidation-mode unchecked-hash -x 'badsyntax|bad_coding' \
    "$RES/python-$copy/lib/python3.14" >/dev/null || stop "compileall failed in python-$copy."
  "${CHECK[@]}" pyc "$(ls "$RES/python-$copy/lib/python3.14/__pycache__"/os.cpython-314.pyc)" \
    || stop "python-$copy's stdlib bytecode is not unchecked-hash."
done
"$RES/python-engine/bin/python3.14" -I -m compileall -f -q -j0 \
  --invalidation-mode unchecked-hash "$RES/engine" >/dev/null || stop "compileall failed in engine."

# ----------------------------------------------- 10. The engine starts clean
echo "10/13 Start the bundled engine once: sys.path, the studio, no writes into the bundle"
probe="$(mktemp -d)"
mkdir -p "$probe/cwd/app" "$probe/regions" "$probe/blobs" "$probe/uploads"
echo 'raise SystemExit("the decoy app/ in the cwd was imported")' > "$probe/cwd/app/__init__.py"
touch "$probe/stamp"
port="$("$REPO/.venv/bin/python" -I -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
(
  cd "$probe/cwd"
  exec env -i HOME="$HOME" PATH=/usr/bin:/bin LANG=en_US.UTF-8 \
    TECOPA_REGIONS="$probe/regions" TECOPA_BLOBS="$probe/blobs" TECOPA_UPLOADS="$probe/uploads" \
    TECOPA_PREP_PYTHON="$RES/python-prep/bin/python3.14" \
    TECOPA_PREP_SCRIPT="$RES/engine/region_prep.py" \
    TECOPA_LABELS_SCRIPT="$RES/engine/scripts/build_labels.py" \
    TECOPA_ENGINE_VERSION="$VERSION" TECOPA_DEBUG=1 \
    PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 \
    "$RES/python-engine/bin/python3.14" -P -m uvicorn app.main:app \
      --app-dir "$RES/engine" --host 127.0.0.1 --port "$port"
) > "$probe/engine.log" 2>&1 &
epid=$!
up=""
for _ in $(seq 1 120); do
  body="$(curl -s --max-time 2 "http://127.0.0.1:$port/readyz" || true)"
  case "$body" in *'"ready"'*'"regions"'*) up=1; break ;; esac
  kill -0 "$epid" 2>/dev/null || break
  sleep 0.5
done
[ -n "$up" ] || { tail -20 "$probe/engine.log" >&2; kill "$epid" 2>/dev/null; stop "The bundled engine did not start."; }
curl -s "http://127.0.0.1:$port/api/debug/engine" > "$probe/engine.json"
studio="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port/")"
kill "$epid"; wait "$epid" 2>/dev/null || true
[ "$studio" = 200 ] || stop "The bundled engine did not serve the studio (HTTP $studio)."
"$REPO/.venv/bin/python" -I - "$probe/engine.json" "$probe/cwd" "$RES" <<'PY' || stop "The engine's sys.path or interpreter is wrong."
import json, os, sys
d = json.load(open(sys.argv[1]))
cwd, res = os.path.realpath(sys.argv[2]), os.path.realpath(sys.argv[3])
bad = [p for p in d["sys_path"] if p == "" or os.path.realpath(p) == cwd
       or os.path.realpath(p).startswith(cwd + "/")]
if bad:
    sys.exit(f"sys.path holds the cwd: {bad}")
if os.path.realpath(d["executable"]) != os.path.join(res, "python-engine", "bin", "python3.14"):
    sys.exit(f"the engine runs {d['executable']}")
PY
[ -z "$(find "$APP" -newer "$probe/stamp" -print -quit)" ] \
  || stop "The engine wrote into the bundle: $(find "$APP" -newer "$probe/stamp" | head -3)"
rm -rf "$probe"

# --------------------------------------------------------------- 11-12. Sign
echo "11/13 Clear extended attributes"
xattr -cr "$APP"
echo "12/13 Sign ad hoc, inside out, never --deep"
sign() {
  local words
  if ! words="$(codesign --force --sign - --timestamp=none "$@" 2>&1)"; then
    printf '%s\n' "$words" >&2
    stop "codesign could not sign ${!#}."
  fi
}
signed=0
while IFS= read -r -d '' f; do sign "$f"; signed=$((signed + 1)); done \
  < <(find "$RES/python-engine" "$RES/python-prep" -type f \( -name '*.so' -o -name '*.dylib' \) -print0)
while IFS= read -r -d '' f; do sign "$f"; signed=$((signed + 1)); done \
  < <("${CHECK[@]}" macho "$RES" --exclude-suffix .so .dylib)
sign --identifier org.plateworks.tecopa.tecopa "$APP/Contents/Helpers/tecopa"
signed=$((signed + 1))
sign "$APP"
echo "signed $signed nested Mach-O files" >> "$REPORT"

# ---------------------------------------------------------------- 13. Prove
echo "13/13 Verify"
codesign --verify --deep --strict --verbose=2 "$APP" >> "$REPORT" 2>&1 \
  || { tail -5 "$REPORT" >&2; stop "codesign --verify failed."; }
found="$(codesign --display --verbose=2 "$APP" 2>&1)"
grep -q '^Identifier=org.plateworks.tecopa$' <<< "$found" || stop "The signature's identifier is wrong."
grep -q '^Signature=adhoc$' <<< "$found" || stop "The app is not signed ad hoc."
[ -z "$(codesign --display --entitlements - --xml "$APP" 2>/dev/null)" ] || stop "The app has an entitlement."
[ "$(lipo -archs "$APP/Contents/MacOS/TecopaPlateworks")" = arm64 ] || stop "The app is not arm64 only."
verified=0
while IFS= read -r -d '' f; do
  codesign --verify --strict "$f" 2>/dev/null || stop "Not signed: $f"
  verified=$((verified + 1))
done < <("${CHECK[@]}" macho "$RES")
codesign --verify --strict "$APP/Contents/Helpers/tecopa" || stop "The tecopa helper is not signed."
verified=$((verified + 1))
[ "$verified" -eq "$signed" ] || stop "Signed $signed Mach-O files but found $verified."
{ echo "xattr:"; xattr -lr "$APP"; du -sh "$APP"; } >> "$REPORT"
echo "Built $APP ($VERSION, $(du -sh "$APP" | cut -f1)). Report: dist/build-report.txt"
