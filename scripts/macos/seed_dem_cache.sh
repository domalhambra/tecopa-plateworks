#!/usr/bin/env bash
# Fill the Mac app's DEM cache once, from this checkout (native Mac app phase 1
# spec 5.6). The app never reads the repo, so it cannot do this itself; from
# phase 2 on, the Dropbox restore fills the cache.
#
#   seed_dem_cache.sh [--from DIR] [--to DIR]
#
# --from defaults to this repo's regions/, --to to the app's cache,
# ~/Library/Application Support/Tecopa Plateworks/regions. Start the app once first:
# it seeds each plate's files, and this script refuses a plate it has not seeded, or
# one whose region.json differs from the source (the DEM would ORPHAN).
# Each DEM is copied to dem.tif.partial, checked against the source's sha256, then
# renamed into place. A different dem.tif already in the cache is never overwritten.
# Exit 0 when every plate is done, 1 when any failed (all are tried), 2 on usage.
set -uo pipefail
unset CDPATH

usage() { echo "usage: seed_dem_cache.sh [--from DIR] [--to DIR]" >&2; exit 2; }

REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null || true)"
FROM="${REPO:+$REPO/regions}"
TO="$HOME/Library/Application Support/Tecopa Plateworks/regions"
while [ $# -gt 0 ]; do
  case "$1" in
    --from) [ $# -ge 2 ] || usage; FROM="$2"; shift 2 ;;
    --to)   [ $# -ge 2 ] || usage; TO="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[ -n "$FROM" ] && [ -d "$FROM" ] || { echo "no source plates at '$FROM'" >&2; exit 2; }

sha() { shasum -a 256 "$1" | awk '{print $1}'; }

failed=0
for dir in "$FROM"/*/; do
  id="$(basename "$dir")"
  case "$id" in .*) continue ;; esac
  src="$FROM/$id/dem.tif"
  dst="$TO/$id"
  if [ ! -f "$src" ]; then echo "$id: no dem.tif" >&2; failed=1; continue; fi
  if [ ! -f "$dst/region.json" ]; then
    echo "$id: not seeded. Start the app once first." >&2; failed=1; continue
  fi
  if ! cmp -s "$FROM/$id/region.json" "$dst/region.json"; then
    echo "$id: region.json differs; the DEM would orphan" >&2; failed=1; continue
  fi
  want="$(sha "$src")"
  if [ -e "$dst/dem.tif" ]; then
    if [ "$(sha "$dst/dem.tif")" = "$want" ]; then
      echo "$id  already  $want"
    else
      echo "$id: dem.tif differs from the source; not overwritten" >&2; failed=1
    fi
    continue
  fi
  if ! cp "$src" "$dst/dem.tif.partial"; then
    echo "$id: copy failed" >&2; rm -f "$dst/dem.tif.partial"; failed=1; continue
  fi
  if [ "$(sha "$dst/dem.tif.partial")" != "$want" ]; then
    echo "$id: the copy does not match the source" >&2; rm -f "$dst/dem.tif.partial"
    failed=1; continue
  fi
  mv "$dst/dem.tif.partial" "$dst/dem.tif"
  echo "$id  ok  $want"
done
exit "$failed"
