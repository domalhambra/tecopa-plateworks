#!/usr/bin/env bash
# Pin the Mac app bundle's two Python environments, with hashes, from one wheelhouse
# (native Mac app phase 1 spec 5.1, plan task 9).
#
#   scripts/macos/make_bundle_locks.sh
#
# Reads the reference environments .venv (the engine) and .venv-prep (region prep),
# downloads the wheel for every pin into dist/.wheelhouse/, and writes
# requirements-bundle-engine.txt and requirements-bundle-prep.txt with sha256 hashes.
# build_bundle.sh installs from these, with no network and no sdists.
# The two environments stay apart (invariant 13): each lock comes from its own venv.
set -euo pipefail
unset CDPATH

REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$REPO"
if ! git diff --quiet HEAD || ! git diff --cached --quiet; then
  echo "The work tree has uncommitted changes to tracked files. Commit them first." >&2
  exit 1
fi

WH="$REPO/dist/.wheelhouse"
CHECK=("$REPO/.venv/bin/python" -I -B "$REPO/scripts/macos/bundle_checks.py")
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WH"

lock_one() {   # <venv> <out> <drop-test-stack: yes|no>
  local venv="$1" out="$2" drop="$3" pins="$WORK/$(basename "$2").pins"
  # Always `python -m pip`: a venv's bin/pip shebang names the folder it was made in.
  "$venv/bin/python" -m pip freeze --exclude-editable --all \
    | grep -v -E '^(pip|setuptools|wheel)==' > "$pins.all"
  if [ "$drop" = yes ]; then
    "$REPO/.venv/bin/python" -I -c '
import re, sys
sys.path.insert(0, sys.argv[2])
from scripts.macos.bundle_checks import TEST_STACK, _norm
for line in open(sys.argv[1]):
    if _norm(line.split("==")[0]) not in {_norm(n) for n in TEST_STACK}:
        sys.stdout.write(line)' "$pins.all" "$REPO" > "$pins"
  else
    cp "$pins.all" "$pins"
  fi
  # No --platform: pip picks for this Mac exactly as it did when it built the venv,
  # so the engine's wheels are the very files proof 1 compares against.
  "$venv/bin/python" -m pip download --quiet --only-binary :all: --no-deps \
    -d "$WH" -r "$pins"
  "${CHECK[@]}" lock "$pins" "$WH" "$out"
  echo "$(wc -l < "$out" | tr -d ' ') pins -> $(basename "$out")"
}

lock_one "$REPO/.venv" "$REPO/requirements-bundle-engine.txt" yes
lock_one "$REPO/.venv-prep" "$REPO/requirements-bundle-prep.txt" no
"${CHECK[@]}" pins "$REPO/requirements-lock.txt" "$REPO/requirements-bundle-engine.txt"
echo "wheelhouse: $WH ($(ls "$WH" | wc -l | tr -d ' ') wheels)"
