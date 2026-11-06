#!/usr/bin/env bash
# Make the signed, notarized release of Tecopa Plateworks.app and its disk image
# (native Mac app phase 4; the shape of Desqueeze's make_release.sh).
#
#   scripts/macos/make_release.sh [--no-notarize]
#
# Builds dist/Tecopa Plateworks.app with build_bundle.sh, then signs every Mach-O
# inside out with the Developer ID, the hardened runtime and a time stamp, never
# --deep and with no entitlements (the 2026-11-05 spike: both Pythons load their
# wheels and render the same bytes under the hardened runtime with none). Then it
# notarizes and staples the app, makes dist/Tecopa Plateworks-<version>.dmg, and
# notarizes and staples that. The notary profile is a Keychain profile:
#   TECOPA_NOTARY_PROFILE, default desqueeze-notary (it works for this team).
# No font is in the app (invariant 10): build_bundle.sh checks.
set -euo pipefail
unset CDPATH

stop() { echo "make_release: $*" >&2; exit 1; }

NOTARIZE=1
[ "${1:-}" = "--no-notarize" ] && NOTARIZE=0
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$REPO"
APP="$REPO/dist/Tecopa Plateworks.app"
RES="$APP/Contents/Resources"
IDENTITY="${TECOPA_SIGN_IDENTITY:-Developer ID Application: DOMINIC ALEKSANDR ALHAMBRA (3JX6D7F3T4)}"
PROFILE="${TECOPA_NOTARY_PROFILE:-desqueeze-notary}"
CHECK=("$REPO/.venv/bin/python" -I -B "$REPO/scripts/macos/bundle_checks.py")

# Every app this script builds or stages registers with LaunchServices, and the
# newest copy then answers the bundle id: `open -b`, Spotlight and the Dock
# launched dist/ instead of /Applications (2026-11-05). Unregister them on exit.
LSREGISTER=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
STAGED=()
unregister() {
  local p
  for p in "$APP" "$REPO/macos/build/Build/Products/Release/TecopaPlateworks.app" ${STAGED[@]+"${STAGED[@]}"}; do
    "$LSREGISTER" -u "$p" >/dev/null 2>&1 || true
  done
}
trap unregister EXIT

security find-identity -v -p codesigning | grep -qF "$IDENTITY" || stop "No signing identity: $IDENTITY"
if [ "$NOTARIZE" = 1 ]; then
  xcrun notarytool history --keychain-profile "$PROFILE" >/dev/null 2>&1 \
    || stop "The notary profile $PROFILE does not work. Make it: xcrun notarytool store-credentials $PROFILE"
fi

echo "1/6 Build the bundle"
bash "$REPO/scripts/macos/build_bundle.sh"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :TecopaEngineVersion' "$APP/Contents/Info.plist")"
SHORT="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")"

echo "2/6 Sign with the Developer ID and the hardened runtime, inside out"
sign() {
  local words
  if ! words="$(codesign --force --options runtime --timestamp --sign "$IDENTITY" "$@" 2>&1)"; then
    printf '%s\n' "$words" >&2
    stop "codesign could not sign ${!#}."
  fi
}
n=0
while IFS= read -r -d '' f; do sign "$f"; n=$((n + 1)); done < <("${CHECK[@]}" macho "$RES")
for helper in "$APP"/Contents/Helpers/*; do
  [ -f "$helper" ] && { sign --identifier "org.plateworks.tecopa.$(basename "$helper")" "$helper"; n=$((n + 1)); }
done
sign "$APP"
echo "   signed $n nested Mach-O files and the app"

echo "3/6 Prove the signature"
codesign --verify --deep --strict "$APP" || stop "codesign --verify failed."
found="$(codesign --display --verbose=2 "$APP" 2>&1)"
grep -q 'flags=.*runtime' <<< "$found" || stop "The app is not signed with the hardened runtime."
grep -q "^Authority=$IDENTITY\$" <<< "$found" || stop "The app is not signed by $IDENTITY."
[ -z "$(codesign --display --entitlements - --xml "$APP" 2>/dev/null)" ] || stop "The app has an entitlement. It must have none."

DMG="$REPO/dist/Tecopa Plateworks-$SHORT-$VERSION.dmg"
if [ "$NOTARIZE" = 1 ]; then
  echo "4/6 Notarize and staple the app (an upload of about 500 MB; minutes)"
  zip="$REPO/dist/notarize-app.zip"
  rm -f "$zip"
  ditto -c -k --keepParent "$APP" "$zip"
  xcrun notarytool submit "$zip" --keychain-profile "$PROFILE" --wait | tee "$REPO/dist/notary-app.txt"
  grep -q "status: Accepted" "$REPO/dist/notary-app.txt" || stop "The notary service did not accept the app. See dist/notary-app.txt."
  rm -f "$zip"
  # The ticket can lag the acceptance by some seconds.
  for _ in 1 2 3 4 5 6; do xcrun stapler staple "$APP" && break; sleep 10; done
  xcrun stapler validate "$APP" || stop "The app's ticket is not stapled."
else
  echo "4/6 Skip notarization (--no-notarize)"
fi

echo "5/6 Make the disk image"
stage="$(mktemp -d)"
STAGED+=("$stage/Tecopa Plateworks.app")
ditto "$APP" "$stage/Tecopa Plateworks.app"
ln -s /Applications "$stage/Applications"
rm -f "$DMG"
hdiutil create -volname "Tecopa Plateworks" -srcfolder "$stage" -fs APFS -format ULFO -ov "$DMG" >/dev/null
unregister
rm -rf "$stage"
codesign --force --timestamp --sign "$IDENTITY" "$DMG"

if [ "$NOTARIZE" = 1 ]; then
  echo "6/6 Notarize and staple the disk image"
  xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait | tee "$REPO/dist/notary-dmg.txt"
  grep -q "status: Accepted" "$REPO/dist/notary-dmg.txt" || stop "The notary service did not accept the disk image."
  for _ in 1 2 3 4 5 6; do xcrun stapler staple "$DMG" && break; sleep 10; done
  spctl --assess --type open --context context:primary-signature --verbose "$DMG" \
    || stop "Gatekeeper refuses the disk image."
  spctl --assess --type execute --verbose "$APP" || stop "Gatekeeper refuses the app."
else
  echo "6/6 Skip notarization (--no-notarize)"
fi
echo "Release: $DMG ($(du -sh "$DMG" | cut -f1))"
