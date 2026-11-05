#!/usr/bin/env bash
# The two proofs of the native Mac app, phase 1 (spec section 8; plan tasks 22, 23).
#
#   byte_proof.sh --bundle "dist/Tecopa Plateworks.app" --proof 1
#   byte_proof.sh --bundle "dist/Tecopa Plateworks.app" --proof 2 --order "<past order folder>"
#
# Proof 1: the app's engine and the repo's .venv engine render the same track to
#   the same bytes: the proof PNG, the final PNG and a two-panel set (cmp).
# Proof 2: a copy of the signed app, with the repo renamed away, renders the same
#   bytes, writes nothing into itself, and prepares a past order through the bundle.
# Reports go to dist/proof/. Ports 8848 and 8849 must be free.
set -euo pipefail
unset CDPATH

usage() { echo "usage: byte_proof.sh --bundle APP --proof 1|2 [--order DIR]" >&2; exit 2; }
fail() { echo "FAIL: $*" | tee -a "${REPORT:-/dev/null}" >&2; exit 1; }

BUNDLE="" PROOF="" ORDER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --bundle) [ $# -ge 2 ] || usage; BUNDLE="$2"; shift 2 ;;
    --proof) [ $# -ge 2 ] || usage; PROOF="$2"; shift 2 ;;
    --order) [ $# -ge 2 ] || usage; ORDER="$2"; shift 2 ;;
    --repo) [ $# -ge 2 ] || usage; REPO="$2"; shift 2 ;;   # set by the re-run of proof 2
    *) usage ;;
  esac
done
[ -n "$BUNDLE" ] && { [ "$PROOF" = 1 ] || [ "$PROOF" = 2 ]; } || usage
[ "$PROOF" = 2 ] && [ -z "$ORDER" ] && usage
REPO="${REPO:-$(git -C "$(dirname "$0")" rev-parse --show-toplevel)}"
BUNDLE="$(cd "$BUNDLE" && pwd -P)"
AS="$HOME/Library/Application Support/Tecopa Plateworks"
REGIONS="$AS/regions"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$REPO/dist/proof"
REPORT="${REPORT:-$REPO/dist/proof/byte-proof-$PROOF-$STAMP.txt}"
export REPORT
PY=/usr/bin/python3
VER="$(/usr/libexec/PlistBuddy -c 'Print :TecopaEngineVersion' "$BUNDLE/Contents/Info.plist")"
ENGINE_PY="$BUNDLE/Contents/Resources/python-engine/bin/python3.14"
PREP_PY="$BUNDLE/Contents/Resources/python-prep/bin/python3.14"
CODE="$BUNDLE/Contents/Resources/engine"

# The engine environment the app builds (spec 5.3). EngineEnvironmentTests pins
# this list against the Swift builder.
ENGINE_ENV_KEYS=(PYTHONDONTWRITEBYTECODE PYTHONNOUSERSITE TECOPA_BLOBS TECOPA_DEBUG TECOPA_ENGINE_VERSION TECOPA_LABELS_SCRIPT TECOPA_PREP_PYTHON TECOPA_PREP_SCRIPT TECOPA_REGIONS TECOPA_UPLOADS)
ENGINE_ENV=()
set_engine_env() {   # after BUNDLE, CODE and the interpreters are final
  ENGINE_ENV=(HOME="$HOME" PATH=/usr/bin:/bin LANG=en_US.UTF-8
    PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
    TECOPA_BLOBS="$AS/blobs" TECOPA_DEBUG=1 TECOPA_ENGINE_VERSION="$VER"
    TECOPA_LABELS_SCRIPT="$CODE/scripts/build_labels.py" TECOPA_PREP_PYTHON="$PREP_PY"
    TECOPA_PREP_SCRIPT="$CODE/region_prep.py" TECOPA_REGIONS="$REGIONS" TECOPA_UPLOADS="$AS/uploads")
}

answers() { curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$1/readyz"; }
wait_engine() {   # port seconds
  for _ in $(seq 1 $(( $2 * 2 ))); do
    body="$(curl -s --max-time 2 "http://127.0.0.1:$1/readyz" || true)"
    case "$body" in *'"ready"'*'"regions"'*) return 0 ;; esac
    sleep 0.5
  done
  return 1
}
json() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

quit_app() {
  osascript -e 'quit app id "org.plateworks.tecopa"' >/dev/null 2>&1 || true
  for _ in $(seq 1 40); do answers 8848 || return 0; sleep 0.5; done
  fail "the app's engine is still on 8848 after quit"
}

# ------------------------------------------------------------- preconditions
echo "proof $PROOF of $BUNDLE ($VER), $STAMP" > "$REPORT"
answers 8848 && fail "port 8848 already answers"
[ "$PROOF" = 1 ] && answers 8849 && fail "port 8849 already answers"
pgrep -f '/Contents/MacOS/TecopaPlateworks( |$)' >/dev/null && fail "a Tecopa Plateworks app is running"
if [ -f "$AS/settings.json" ] && grep -q '"TECOPA_FONT' "$AS/settings.json"; then
  fail "settings.json binds a font; proof 1 runs with no fonts bound (spec 8.1)"
fi
[ -d "$REGIONS/lassen_ca" ] && [ -f "$REGIONS/lassen_ca/dem.tif" ] \
  || fail "no lassen_ca DEM in $REGIONS: start the app once, then run seed_dem_cache.sh"
WORK="$(mktemp -d)"
mkdir -p "$WORK/ref" "$WORK/cand"
cp "$REPO/tests/fixtures/sample.gpx" "$WORK/sample.gpx"
# Fresh blobs and uploads for the candidate (spec 8.1): move the old ones aside.
for d in blobs uploads; do
  [ -e "$AS/$d" ] && mv "$AS/$d" "$WORK/old-$d"
done

owner_check() {
  local pid exe dbg
  pid="$(lsof -nP -iTCP:8848 -sTCP:LISTEN -t | head -1)"
  dbg="$(curl -s http://127.0.0.1:8848/api/debug/engine)"
  [ "$(json 'd["pid"]' <<<"$dbg")" = "$pid" ] || fail "the engine on 8848 (pid $pid) is not the one the debug route reports"
  exe="$("$PY" -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$(json 'd["executable"]' <<<"$dbg")")"
  [ "$exe" = "$ENGINE_PY" ] || fail "the engine on 8848 runs $exe, not the bundle's interpreter"
  [ "$(json 'd["engine_version"]' <<<"$dbg")" = "$VER" ] || fail "the engine version is not $VER"
  [ "$(json 'sum(k.startswith("TECOPA_FONT") for k in d["env"])' <<<"$dbg")" = 0 ] || fail "the candidate has a font bound"
  echo "owner: pid $pid, $exe, engine $VER" >> "$REPORT"
}

recipe() {   # side port
  local E="http://127.0.0.1:$2" O="$WORK/$1" up sid x0 y0 x1 y1 reg rec jid st crop
  up="$(curl -s -F "files=@$WORK/sample.gpx" -F region_id=lassen_ca "$E/api/upload")"
  read -r sid x0 y0 x1 y1 reg rec <<<"$(json '" ".join(map(str, [d["session"], *d["starter_crop"], d["region"], d.get("recovered", False)]))' <<<"$up")"
  [ "$reg" = lassen_ca ] && [ "$rec" = False ] || fail "$1: the upload did not land on lassen_ca ($reg, recovered $rec)"
  [ "$(curl -s -o "$O/proof.png" -w '%{http_code}' -F session_id="$sid" -F x0="$x0" -F y0="$y0" \
       -F x1="$x1" -F y1="$y1" -F "title=Byte proof" "$E/api/proof")" = 200 ] || fail "$1: proof failed"
  jid="$(curl -s -F session_id="$sid" -F format=png "$E/api/final/submit" | json 'd["job"]')"
  for _ in $(seq 1 150); do
    st="$(curl -s "$E/api/jobs/$jid")"
    case "$st" in *'"done"'*) break ;; *'"state":"error"'*) fail "$1: final failed: $st" ;; esac
    sleep 2
  done
  curl -sf -o "$O/final.png" "$E/api/jobs/$jid/result" || fail "$1: no final"
  crop="$(curl -s "$E/api/debug/sessions/$sid/starter_crop?print_w=36&print_h=22")"
  read -r x0 y0 x1 y1 <<<"$(json '" ".join(map(str, d["starter_crop"]))' <<<"$crop")"
  [ "$(curl -s -o "$O/set_proof.png" -w '%{http_code}' -F session_id="$sid" -F x0="$x0" -F y0="$y0" \
       -F x1="$x1" -F y1="$y1" -F "title=Byte proof set" -F print_w=36 -F print_h=22 \
       -F panels=2 -F panel_gap=2 "$E/api/proof")" = 200 ] || fail "$1: set proof failed"
  jid="$(curl -s -F session_id="$sid" -F format=png "$E/api/final/submit" | json 'd["job"]')"
  for _ in $(seq 1 300); do
    st="$(curl -s "$E/api/jobs/$jid")"
    case "$st" in *'"done"'*) break ;; *'"state":"error"'*) fail "$1: set failed: $st" ;; esac
    sleep 2
  done
  curl -sf -o "$O/panels.zip" "$E/api/jobs/$jid/result" || fail "$1: no set"
  [ "$(unzip -Z1 "$O/panels.zip" | wc -l | tr -d ' ')" = 2 ] || fail "$1: the set does not hold 2 panels"
}

env_record() {   # python -> one JSON line
  "$1" -P -c '
import hashlib, json, os, platform, sys
from PIL import features
import numpy, scipy, rasterio, pyproj
from pyproj import datadir
from app import render
def tree(d):
    h = hashlib.sha256()
    for root, dirs, files in os.walk(d):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(root, f)
            h.update(os.path.relpath(p, d).encode()); h.update(open(p, "rb").read())
    return h.hexdigest()
import importlib.metadata as md
wheels = {}
for dist in md.distributions():
    # Each installed file with its own sha256, from RECORD, minus what the installer
    # writes (pip and uv differ there): bytecode, scripts, INSTALLER, REQUESTED,
    # direct_url.json, uv_cache.json and RECORD itself.
    rec = [l.rsplit(",", 2)[:2] for l in (dist.read_text("RECORD") or "").splitlines() if l]
    keep = sorted(f"{name},{h}" for name, h in rec if "__pycache__" not in name
                  and not name.startswith("../") and "/bin/" not in name
                  and not name.endswith(("INSTALLER", "REQUESTED", "direct_url.json",
                                         "uv_cache.json", "RECORD")))
    wheels[dist.metadata["Name"].lower()] = hashlib.sha256("\n".join(keep).encode()).hexdigest()[:16]
gdal = os.path.join(os.path.dirname(rasterio.__file__), "gdal_data")
f = render._load_font(None, 24)
font = getattr(f, "path", None)
font_sha = hashlib.sha256(open(font, "rb").read()).hexdigest() if font else None
print(json.dumps({"must": {
    "python": platform.python_version(),
    "pil_zlib": features.version("zlib"), "lcms2": features.version("littlecms2"),
    "freetype": features.version("freetype2"),
    "numpy": numpy.__version__, "scipy": scipy.__version__, "rasterio": rasterio.__version__,
    "gdal": rasterio.__gdal_version__, "pyproj": pyproj.__version__, "proj": pyproj.proj_version_str,
    "font_sha256": font_sha,
    "proj_data": tree(datadir.get_data_dir()), "gdal_data": tree(gdal) if os.path.isdir(gdal) else None,
    "wheels": {k: v for k, v in wheels.items() if k not in ("pytest","pytest-xdist","execnet","iniconfig","pluggy","pyflakes","pygments","pip")},
  }, "recorded": {"sys.version": sys.version, "zlib": __import__("zlib").ZLIB_RUNTIME_VERSION,
                  "proj_dir": datadir.get_data_dir(), "gdal_dir": gdal, "font": font}}, sort_keys=True))
' 2>/dev/null
}

# ----------------------------------------------------------------- proof 1
if [ "$PROOF" = 1 ]; then
  REF="$WORK/ref"
  mkdir -p "$REF/cwd" "$REF/blobs" "$REF/uploads"
  ( cd "$REF/cwd" && exec env -i HOME="$HOME" PATH=/usr/bin:/bin LANG=en_US.UTF-8 \
      TECOPA_REGIONS="$REGIONS" TECOPA_BLOBS="$REF/blobs" TECOPA_UPLOADS="$REF/uploads" \
      TECOPA_ENGINE_VERSION="$VER" TECOPA_DEBUG=1 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 \
      "$REPO/.venv/bin/python" -P -m uvicorn app.main:app --app-dir "$REPO" \
        --host 127.0.0.1 --port 8849 ) > "$REF/engine.log" 2>&1 &
  REFPID=$!
  # Always stop what this run started, pass or fail.
  trap 'kill $REFPID 2>/dev/null || true; osascript -e "quit app id \"org.plateworks.tecopa\"" >/dev/null 2>&1 || true' EXIT
  open "$BUNDLE"
  wait_engine 8849 90 || fail "the reference engine did not start (see $REF/engine.log)"
  wait_engine 8848 90 || fail "the app's engine did not start"
  owner_check
  recipe ref 8849 & r1=$!
  recipe cand 8848 & r2=$!
  wait $r1 || fail "the reference recipe failed"
  wait $r2 || fail "the candidate recipe failed"
  for f in proof.png final.png set_proof.png panels.zip; do
    a="$(shasum -a 256 "$WORK/ref/$f" | cut -d' ' -f1)"; b="$(shasum -a 256 "$WORK/cand/$f" | cut -d' ' -f1)"
    echo "anchor $f $a" >> "$REPORT"
    echo "cand   $f $b" >> "$REPORT"
    cmp -s "$WORK/ref/$f" "$WORK/cand/$f" || fail "$f differs between the venv and the bundle"
  done
  ref_env="$( cd "$REF/cwd" && PYTHONPATH="$REPO" env_record "$REPO/.venv/bin/python")"
  cand_env="$( cd "$REF/cwd" && PYTHONPATH="$CODE" env_record "$ENGINE_PY")"
  echo "env ref  $ref_env" >> "$REPORT"
  echo "env cand $cand_env" >> "$REPORT"
  "$PY" - "$ref_env" "$cand_env" <<'PY' >> "$REPORT" || fail "the environments differ (see the report)"
import json, sys
a, b = (json.loads(x)["must"] for x in sys.argv[1:3])
diff = {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k) and k != "wheels"}
wa, wb = a["wheels"], b["wheels"]
diff.update({f"wheel {k}": (wa.get(k), wb.get(k)) for k in set(wa) & set(wb) if wa[k] != wb[k]})
for k, v in sorted(diff.items()):
    print("env differs:", k, v)
sys.exit(1 if diff else 0)
PY
  kill $REFPID 2>/dev/null || true
  quit_app
  echo "PASS: proof 1" | tee -a "$REPORT"
  exit 0
fi

# ----------------------------------------------------------------- proof 2
ANCHOR="$(ls -t "$REPO"/dist/proof/byte-proof-1-*.txt 2>/dev/null | head -1)"
[ -n "$ANCHOR" ] && grep -q '^PASS: proof 1' "$ANCHOR" || fail "no passing proof 1 report to compare against"
cp "$ANCHOR" "$WORK/anchor.txt"
"$REPO/scripts/macos/seed_dem_cache.sh" >> "$REPORT" || fail "seed_dem_cache.sh did not report every plate"
# dist/ is inside the repo: prove a copy of the app that lives outside it.
ditto "$BUNDLE" "$WORK/Tecopa Plateworks.app"
BUNDLE="$WORK/Tecopa Plateworks.app"
ENGINE_PY="$BUNDLE/Contents/Resources/python-engine/bin/python3.14"
PREP_PY="$BUNDLE/Contents/Resources/python-prep/bin/python3.14"
CODE="$BUNDLE/Contents/Resources/engine"
codesign --verify --deep --strict "$BUNDLE" || fail "the copied app's signature is not valid"
xattr -lr "$BUNDLE" > "$WORK/xattr.before"
COPY="$HOME/Tecopa Orders/_proof/$(basename "$ORDER")"
[ -d "$ORDER" ] || fail "no order at $ORDER"
mkdir -p "$HOME/Tecopa Orders/_proof"
rm -rf "$COPY.tmp"; ditto "$ORDER" "$COPY.tmp"; rm -rf "$COPY"; mv "$COPY.tmp" "$COPY"
rm -f "$COPY/work/state.json"   # a venv-prepared state names <repo>/regions (spec 8.2 step 5)

MOVED="$REPO.moved-$STAMP"
mv "$REPO" "$MOVED"
trap 'osascript -e "quit app id \"org.plateworks.tecopa\"" >/dev/null 2>&1 || true; sleep 2; mv "$MOVED" "$REPO" 2>/dev/null && echo "repo restored to $REPO"' EXIT

open "$BUNDLE"
wait_engine 8848 90 || fail "the app's engine did not start with the repo moved away"
owner_check
recipe cand 8848
for f in proof.png final.png set_proof.png panels.zip; do
  want="$(grep "^anchor $f " "$WORK/anchor.txt" | awk '{print $3}')"
  got="$(shasum -a 256 "$WORK/cand/$f" | cut -d' ' -f1)"
  echo "moved $f $got" >> "$REPORT"
  [ "$got" = "$want" ] || fail "$f does not match proof 1's anchor"
done
quit_app
codesign --verify --deep --strict "$BUNDLE" || fail "the app's signature broke: something wrote into it"
xattr -lr "$BUNDLE" | diff -q - "$WORK/xattr.before" >/dev/null || fail "the app's extended attributes changed"

# Prepare one order through the bundle (spec 8.2 step 5).
set_engine_env
( cd "$AS" && env -i "${ENGINE_ENV[@]}" TECOPA_ORDERS_DIR="$HOME/Tecopa Orders/_proof" \
    "$ENGINE_PY" -P "$CODE/scripts/order.py" prepare "$COPY" ) >> "$REPORT" 2>&1 \
  || fail "order prepare through the bundle failed"
"$PY" - "$COPY/work/state.json" "$REGIONS" <<'PY' >> "$REPORT" || fail "the order did not use the curated plate in the app's cache"
import json, sys
s = json.load(open(sys.argv[1]))
plate = s.get("plate", {})
print("prepare plate:", json.dumps(plate)[:300])
assert plate.get("root") == sys.argv[2], plate.get("root")
assert plate.get("kind", "curated") == "curated", plate.get("kind")
PY
# The region-prep interpreter runs (spec 8.2 step 6).
( cd "$AS" && env -i "${ENGINE_ENV[@]}" "$PREP_PY" -P "$CODE/region_prep.py" --help ) >/dev/null \
  || fail "region_prep.py --help failed in python-prep"
( cd "$AS" && env -i "${ENGINE_ENV[@]}" "$PREP_PY" -P -c 'import rasterio, py3dep' ) \
  || fail "python-prep cannot import rasterio and py3dep"
osascript -e "tell application \"Finder\" to delete POSIX file \"$COPY\"" >/dev/null 2>&1 || true
echo "PASS: proof 2" | tee -a "$REPORT"
