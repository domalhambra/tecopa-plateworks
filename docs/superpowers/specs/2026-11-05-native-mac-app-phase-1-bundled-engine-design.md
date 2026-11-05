# Native Mac app, phase 1: the bundled engine: design

**Date:** 2026-11-05
**Status:** Approved by Dom, 2026-11-05. Not built. Three actions keep their own gate and each waits for Dom's typed yes: the Developer ID signing spike (section 7), the install over the launcher (section 9), and the zlib fallback (section 8.1).
**Extends:** `docs/superpowers/handoffs/2026-11-05-native-mac-app.md` (the plan, phases 0 to 5).
**Will supersede, when phase 1 ships:** `2026-07-18-macos-launcher-app-design.md` (the launcher).
**Will amend, when phase 1 ships:** `2026-10-09-tecopa-cli-and-mcp-design.md`, decision 7, the
Repo path section and the Venv rule (section 9 below).

## 1. Goal

One app bundle, `Tecopa Plateworks.app`, that carries its own Python and engine, starts the engine
on port 8848, and opens the existing web studio in the browser. Nothing it runs reads the repo.

Phase 1 carries the plan's largest risk. If a poster from the bundled engine does not equal the
venv's poster byte for byte (invariant 3), the plan changes before any native UI is built.

**Done means both proofs in section 8 pass:**

1. A test poster from the bundle is byte-equal to the venv's.
2. The ad hoc signed bundle starts and renders that poster with the repo moved away, and its
   signature is still valid afterwards.

## 2. Decisions from Dom (2026-11-05)

| Question | Answer | What it does to phase 1 |
| --- | --- | --- |
| Shell, studio, tooling | SwiftUI shell, native studio, native tooling | Phase 1 builds the shell only. The studio stays in the browser. |
| Audience | Just Dom for now | No About-box AGPL notice, no source offer, no update path. Section 10 keeps them possible. |
| Bundle id | New: `org.plateworks.tecopa` | Replaces `guide.badwater.tecopa`. Invariant 9 and the `tecopa` tool change (section 9). |
| Curated plates | DEMs are a cache. One cold copy of each DEM in Dropbox, so an exact reprint stays possible. Restore from Dropbox first, rebuild from 3DEP second. | Phase 1 fixes the cache location, seeds it, and writes the first archive. Restore and evict are phase 2. |
| Paid size | Read it from the order desk | Phase 2. Phase 1 does nothing with it. |

## 3. Non-goals

- No native studio, Orders window, Settings window or plate builder (phases 2 and 3).
- No Developer ID release, notarization or DMG (phase 4). Section 7 names one early signing
  spike, which waits for Dom's yes.
- No restore, eviction or rebuild of DEMs (phase 2). No track deletion (the privacy rule needs
  Dom's decision; see the handoff).
- No engine rule moves into Swift. Swift holds no render logic, coordinate math or spec rules.

## 4. Layout

### 4.1 The bundle (read-only, signed)

```
Tecopa Plateworks.app/Contents/
  MacOS/TecopaPlateworks             the Swift app
  Info.plist                         TecopaEngineVersion = git short commit, baked at build
  Resources/
    engine/                          the repo's relative layout, kept exactly
      app/                           including app/static (the web studio)
      scripts/order.py, build_labels.py, dem_coverage.py, bake_playa.py,
              render_mockups.py, verify_regions.py, pack_region.py
      region_prep.py
      config/sizes.toml, papers.toml
    plates/<id>/                     git-tracked plate files only, never dem.tif
    python-engine/                   standalone CPython 3.14.2 + engine packages
    python-prep/                     standalone CPython 3.14.2 + region-prep packages
```

- The engine tree keeps the repo's relative layout because code depends on it:
  `scripts/dem_coverage.py:19` and `scripts/bake_playa.py` import from the parent folder,
  `app/mockups.py:18` imports `scripts.render_mockups`, and `app/sizes.py:42` and
  `app/papers.py:41-46` find `config/` from `__file__`.
- `engine/` and `plates/` are both assembled from `git ls-files` (`regions` for plates). An
  ignored file, such as `dem.tif` or a font dropped in a folder, can never enter the bundle.
  Plates are about 23 MB for 11.
- A build check greps `from scripts.` and `import scripts` across the bundled `app/`. It fails
  when a module named there is missing from the bundled `scripts/`.
- The `tecopa` command runs `scripts/verify_regions.py` (regions verify) and
  `scripts/pack_region.py` (plate pack) from the engine, so both ship. A second build check
  (`bundle_checks.py table`) reads every `.script(` row of `ScriptRunner.table` in
  `tools/tecopa` and fails naming any row whose file is missing under `engine/`.
- `assets/`, `marketing/`, `tests/`, `docs/` and every font stay out (invariant 10: never put a
  font in the bundle or the DMG). A build check fails on any `.otf`, `.ttf`, `.ttc`, `.otc`,
  `.dfont`, `.woff` or `.woff2` under `engine/` or `plates/`. The Python copies get an
  allowlist instead, because a wheel may ship a freely licensed font. Neither venv holds one
  today.
- `config/` is read-only in phase 1. A change to `sizes.toml` or `papers.toml` (prices,
  papers) needs an app rebuild. Phase 2 decides whether Settings needs a writable copy.

### 4.2 Data (writable, outside the bundle)

| Path | Holds | Class |
| --- | --- | --- |
| `~/Library/Application Support/Tecopa Plateworks/` | The engine's working directory | state |
| `…/regions/<id>/` | Seeded plate files plus the cached `dem.tif` | state (cache) |
| `…/blobs/`, `…/uploads/` | Engine blobs, uploaded tracks | state |
| `…/settings.json` | Font bindings, orders folder, intake folder. Hand-edited in phase 1; the Settings window writes it in phase 2. | state |
| `~/Library/Logs/TecopaPlateworks.log` | Engine and app log, unchanged, so `LogReader` and `tecopa doctor` keep working | log |
| `~/Tecopa Orders/` (`TECOPA_ORDERS_DIR`) | Orders, unchanged. Its `_cache/` holds the HyRiver request cache that Prepare uses; in-app plate builds share it (5.4, change 3). | user data |
| `~/Library/CloudStorage/Dropbox/Apps/Plateworks Lab/Tecopa/` | The intake. Read-only to Tecopa, unchanged. | user data |
| `~/Library/CloudStorage/Dropbox/Tecopa Plateworks/Plates/` | The cold DEM archive (section 6) | archive |

The bundle is never written. Section 8, proof 2, checks it.

## 5. The engine process

### 5.1 Python

- **Interpreter:** python-build-standalone CPython **3.14.2**, `aarch64-apple-darwin`,
  `install_only`, not stripped, not free-threaded. The build script pins its URL and SHA-256.
  It downloads the tarball, not uv's managed copy, which carries `EXTERNALLY-MANAGED`. 3.14.2
  matches the venv's python.org 3.14.2. A later 3.14.x is a deliberate change that repeats
  proof 1.
- **Two copies, never mixed (invariant 13).** `python-engine/` and `python-prep/` each hold
  their own `site-packages`. Neither is a venv: a venv's `pyvenv.cfg` holds an absolute
  path and does not survive a move.
- **Locks.** Two new locks, pinned to the reference environments' versions and hashed
  (`uv pip compile --generate-hashes`, or the wheelhouse files hashed into the lock;
  `pip freeze` alone has no hashes, and `--require-hashes` refuses it):
  - `requirements-bundle-engine.txt`: `requirements-lock.txt` plus the extras the README
    names (pandas, geopandas, pyogrio, python-dateutil, six, imageio-ffmpeg), minus the test
    stack. The extras stay so proof 1's wheel comparison matches the reference `.venv`.
  - `requirements-bundle-prep.txt`: the versions in `.venv-prep`, whose stack is unpinned today.

  A test checks that every pin in `requirements-lock.txt` appears in the engine lock at the same
  version, except a named test stack: pytest, pytest-xdist, execnet, iniconfig, pluggy,
  pyflakes, Pygments.
- **Install:** `uv pip install --python <copy>/bin/python3.14 --only-binary :all: --no-deps
  --require-hashes -r <lock>`, from one wheelhouse shared with the reference venv, so the
  platform tags match exactly (numpy and scipy `macosx_14_0_arm64`).
- **Bytecode:** `compileall -f -j0 --invalidation-mode unchecked-hash` over the stdlib, both
  site-packages and `engine/`, before signing. `-f` matters: without it compileall keeps the
  timestamp `.pyc` files the interpreter ships. A build check reads one stdlib `.pyc` header
  and asserts the unchecked-hash flag. At run time `PYTHONDONTWRITEBYTECODE=1`.
- **Wheel binaries are copied byte for byte.** No `install_name_tool`, no thinning, no strip.
  `@loader_path` and `@rpath` stay valid because the relative layout is kept. Dead absolute
  `LC_RPATH` entries in some wheels (rasterio, Pillow, pyproj) are known and accepted.

### 5.2 How the engine finds its code

- uvicorn gets `--app-dir <bundle>/Contents/Resources/engine`, absolute. That puts the engine
  folder at `sys.path[0]`.
- `-P` alone is **not** enough. The uvicorn CLI's `--app-dir` defaults to `""` and is inserted
  at `sys.path[0]` (`uvicorn/main.py:362-366, 549-550`), which puts the working directory back.
  An explicit `--app-dir` replaces that `""`. Keep `-P` as well, for the interpreter's own
  entry.
- A build check starts the engine, reads its `sys.path`, and fails if `""` or the Application
  Support folder is on it. A stray `app/` there must never shadow the bundled code.
- **No `PYTHONPATH`.** The prep subprocesses inherit the engine's environment, so it would reach
  them, and it is the easiest way to break invariant 13 by accident. `--app-dir` makes a `.pth`
  file unnecessary too. Scripts run by path: `region_prep.py` gets its
  own folder as `sys.path[0]`, and `scripts/order.py`, `dem_coverage.py` and `bake_playa.py`
  add the engine folder themselves.

### 5.3 Command and environment

```
<bundle>/Contents/Resources/python-engine/bin/python3.14 -P -m uvicorn app.main:app \
    --app-dir <bundle>/Contents/Resources/engine --host 127.0.0.1 --port 8848
cwd = ~/Library/Application Support/Tecopa Plateworks/
```

One environment builder in TecopaKit (section 9) sets every path as an absolute value, so
nothing relies on a relative default:

| Variable | Value |
| --- | --- |
| `TECOPA_REGIONS` | `<AS>/regions` |
| `TECOPA_BLOBS`, `TECOPA_UPLOADS` | `<AS>/blobs`, `<AS>/uploads` |
| `TECOPA_PREP_PYTHON` | `<bundle>/…/python-prep/bin/python3.14` |
| `TECOPA_PREP_SCRIPT`, `TECOPA_LABELS_SCRIPT` | the bundled `region_prep.py`, `scripts/build_labels.py` |
| `TECOPA_ENGINE_VERSION` | `TecopaEngineVersion` from Info.plist |
| `TECOPA_ORDERS_DIR`, `TECOPA_INTAKE_DIR`, `TECOPA_FONT*` | from `settings.json`; unset when absent |
| `TECOPA_DEBUG` | `1` (the `tecopa` tool's debug routes) |
| `PYTHONDONTWRITEBYTECODE`, `PYTHONNOUSERSITE` | `1` |
| removed | `PYTHONPATH`, `PYTHONHOME`, `PROJ_LIB`, `PROJ_DATA`, `GDAL_DATA`, `GDAL_*`, `DYLD_*`, `TECOPA_RELIEF_WORKERS` |

A Finder-launched app does not inherit shell variables, so `settings.json` is the only source
of font bindings. Today no `TECOPA_FONT*` is bound anywhere on this Mac (section 11).

`TECOPA_ENGINE_VERSION` is always set. Without it, `app/provenance.py:54` shells out to `git` on
import and stamps `unknown` in a bundle.

### 5.4 Engine code changes (each test-first)

Five small changes, so a working directory outside the repo is safe. None changes a render.

1. `app/main.py:2446` serves the studio from `os.path.join(os.path.dirname(__file__), "static")`,
   not the cwd-relative `"app/static"`.
2. `app/orderprep.py:165` sets `curated_root` from `TECOPA_REGIONS` when it is set, as
   `app/main.py:35` does. Today Prepare and Preview ignore it and would look inside the
   bundle. With no curated plate visible, they silently build an order plate instead
   (`orderprep.py:195-197`).
3. `app/main.py:875-879`, the in-app plate build, passes `out_root = abspath(REGIONS_ROOT)` and
   the HyRiver cache environment from `orderprep.cache_env()`, with the working directory set to
   that cache's folder. `cache_env()` takes no argument and roots the cache in
   `<orders>/_cache` (`app/order.py:59-61`), so in-app builds share Prepare's request cache.
   That is an HTTP cache of public 3DEP and hydrography responses, not customer data. Today the
   build writes `regions/`, `cache/aiohttp_cache.sqlite` and `cache/failed_ids*.txt` relative to
   the working directory.
4. `app/orderprep.py:214`, the 3DEP coverage query, runs with `cwd = cache_dir`, not the code
   root.
5. `app/order.py:70`, `refuse_inside_repo`. In the bundle, `_repo_root()` names
   `Contents/Resources/engine`, so the guard that keeps customer orders out of the public
   checkout stops guarding the checkout. A `TECOPA_ORDERS_DIR` in the hand-edited
   `settings.json` that points into the repo would no longer be refused. The guard also refuses
   any path that has a `.git` folder among its ancestors, and keeps refusing the code root.

### 5.5 Ownership, start and quit

The launcher's rules carry over (launcher spec, Launch flow and Quit). What changes:

- **Start.** Probe `/readyz` with `EngineClient`.
  - The engine's shape (`ready` and `regions` keys): adopt. Own nothing, open the browser.
  - Another reply: alert "Port 8848 is in use by another program." Quit.
  - No reply but the port is held: alert that an engine on 8848 is not answering. Never spawn.
  - Port free: spawn, then wait up to 60 s for a reply with the engine's shape, **200 or 503**.
    A 503 whose region entry shows `dem_present: false` means a plate is not cached, not that
    the engine is down. Then open `http://127.0.0.1:8848/`.
- **Quit.** If the app owns the engine, read the jobs with TecopaKit. If any are running or
  queued, confirm: "N jobs are running. Quitting ends them." Then SIGTERM, wait 5 s, SIGKILL.
  In adopt mode, quit touches nothing.
- **Unexpected engine exit:** an alert naming the log, then quit. **Dock reopen:** open the
  browser.
- **To check while building:** whether SIGTERM to uvicorn also ends a running render worker or
  `region_prep` child. The launcher never checked.
- **No Documents prompt.** The app reads nothing under `~/Documents`, so
  `NSDocumentsFolderUsageDescription` goes. A font file or intake folder under a protected
  folder would bring a prompt back; `settings.json` should point at `~/Library/Fonts`.
  Whether macOS asks before a non-sandboxed app reads `~/Library/CloudStorage/Dropbox` is
  unverified on this OS. The first run will tell.

### 5.6 Plate seeding at launch

The engine reads one regions root. The bundle's plate files and the cached DEMs combine there
by **copy, never symlink**: Starlette's `StaticFiles` refuses symlinks that leave its root,
which would break `/regions/<id>/overview.png`.

At each launch, before the engine starts:

1. Read `<AS>/regions/.seeded.json` (bundle version and the sha256 of each seeded file).
2. A plate folder that does not exist: copy `plates/<id>/` to a staging folder inside
   `<AS>/regions/.seed-tmp/`, then rename it into place.
3. A seeded file that differs from the bundle: replace it atomically. The bundle is git canon.
4. Never touch `dem.tif`, and never touch a plate id the bundle does not carry (a plate built in
   the app). Never write `sources.json` from any other source (invariant 12).
5. When a bundle update changes `region.json` under a cached DEM, the plate can ORPHAN. Log it
   and let `/readyz` report it. Phase 2's restore repairs it.

The app never reads the repo, so it cannot fill the DEM cache itself. A one-time script,
`scripts/macos/seed_dem_cache.sh`, copies the 11 current DEMs from the repo checkout into
`<AS>/regions/<id>/` and checks each sha256 against the source file after the copy. It runs
before proof 2 renames the repo. From phase 2 on, the Dropbox restore fills the cache.

## 6. The Dropbox DEM archive

The archive is cold and write-once. It exists so an exact reprint stays possible after the
cache is cleared or 3DEP revises its data.

```
~/Library/CloudStorage/Dropbox/Tecopa Plateworks/Plates/
  <id>/
    index.json                      generations, and which one is "current"
    <sha256>/dem.tif
    <sha256>/RECORD.json            id, sha256, bytes, label, archived_at, git commit,
                                    sha256 of region.json and sources.json at that time
```

- Keyed by the DEM's own sha256, so a rebuild can never overwrite an original.
- Write to `dem.tif.partial`, hash it, then rename. Never overwrite an existing sha folder.
- Kept outside `Apps/Plateworks Lab/`, the intake's folder.

**What phase 1 archives** (about 4.6 GB; Dom checks the free Dropbox space first):

| Bytes | Label |
| --- | --- |
| The 11 DEMs on disk now | `current-2026-11-01`. Every poster since the Lanczos swap was painted on these. |
| `backups/dem-before-lanczos-2026-11/lassen_ca`, `tecopa_ca` | `sidecar-original`. They match `sources.json`. |
| The other four files in that backup | `pre-lanczos-2026-08` |

`verify_regions.py` reports DRIFT on six plates. That is the Lanczos swap Dom approved
(`decisions.md`, 2026-11-01), not damage: only `dem.tif` changed, and `sources.json` stays as
it was. So a restore targets the sha in `index.json` `current`, or a poster manifest's
`region_pack` sha, **never the `sources.json` sha**. Restoring by `sources.json` would put the
striped pre-Lanczos DEM back.

The July sidecar bytes for `elko_bonneville`, `rifle_aspen`, `susanville_reno` and
`tushar_beaver_ut` were not found. A poster painted on them reprints only with
`allow_plate_mismatch=true` unless an older drive holds them (section 11).

Restore, rebuild-from-3DEP and evict are phase 2. Two rules from this design bind it:

- A refill from 3DEP runs a dedicated entry point (`dem_candidate.committed_plan`, then
  `region_prep.build_dem_cog`, to a temp file, then rename). Never `region_prep.main` or
  `regionbuild.run_build`: they rewrite committed files, and on failure `run_build` deletes
  the plate folder (`regionbuild.py:127`).
- Never evict a DEM under an order verb. A curated plate with no DEM drops out of Preview and
  Prepare silently. Restore first, or refuse.

## 7. Build and signing

- **XcodeGen**, Desqueeze's shape: `macos/project.yml`, app target `Tecopa Plateworks`,
  `PRODUCT_BUNDLE_IDENTIFIER org.plateworks.tecopa`, executable `TecopaPlateworks`, macOS 14,
  not sandboxed, no entitlements file. `CFBundleDisplayName` is "Tecopa Plateworks" in full
  (invariant 14).
- The app links **TecopaKit** as a local package (`tools/tecopa/Package.swift` gains a
  `TecopaKit` library product). AppKit and SwiftUI stay in the app target.
- **`scripts/macos/build_bundle.sh`** refuses a dirty tree. It bakes `git rev-parse --short
  HEAD` into Info.plist, assembles `Resources/` (section 4.1), installs both Pythons (5.1), runs
  `compileall`, and signs.
- **Signing, inside out, never `--deep`**, as in Desqueeze's `make_release.sh`: every `.so` and
  `.dylib` in both Python copies (about 690), then every other Mach-O found by magic bytes
  (both `python3.14`, imageio-ffmpeg's `ffmpeg`), then the app. Verify with
  `codesign --verify --deep --strict`. Phase 1 signs ad hoc (`--sign -`).
- **Entitlements: none by default.** Add one only after a recorded failure under the hardened
  runtime, with the failure in the commit.
- **Early signing spike (needs Dom's typed yes; the handoff says anything signed waits for
  it):** sign the phase 1 bundle once with the Developer ID and the hardened runtime, locally,
  not notarized, not distributed. Then run proof 1. This finds out now whether the hardened
  runtime needs `disable-library-validation` or `allow-unsigned-executable-memory`, and whether
  690 Mach-O files under `Contents/Resources` pass `--strict`. Otherwise those surprises arrive
  in phase 4. The notary profile `desqueeze-notary` already works on this Mac and can be reused
  in phase 4.
- **Size:** about 1.3 GB uncompressed (engine site-packages 521 MB, prep 705 MB, two
  interpreters).

## 8. Proofs

`scripts/macos/byte_proof.sh` runs both proofs and writes one report. Before either proof:

- Port 8848 and port 8849 are free, and no copy of the old launcher is running.
- The app is in **owner mode**: it spawned the engine. `lsof -iTCP:8848 -sTCP:LISTEN` resolves
  to a pid whose executable is `<bundle>/Contents/Resources/python-engine/bin/python3.14`, and
  that pid equals the one `/api/debug/engine` reports. The report records the check. Without
  it, the app could adopt a venv engine already on 8848, and `cmp` would pass trivially.

### 8.1 Proof 1: byte-equal

| | Value |
| --- | --- |
| Reference | Today's `.venv` (python.org 3.14.2), started by `byte_proof.sh` on port 8849, with its working directory outside the repo |
| Candidate | The bundle's engine, started by the app, on port 8848 |
| Both sides | `TECOPA_ENGINE_VERSION` = the bundle's baked `TecopaEngineVersion`; `TECOPA_DEBUG=1` (the second case needs a debug route); no `TECOPA_FONT*`; the cleared variables in 5.3; one shared `TECOPA_REGIONS` (`region_pack` hashes the DEM from disk into the manifest); fresh, separate blobs and uploads |
| Track | `tests/fixtures/sample.gpx`, `region_id=lassen_ca`, the upload's `starter_crop`, `title=Byte proof` |
| Calls | `POST /api/upload`, `POST /api/proof`, `POST /api/final/submit` (PNG), poll `/api/jobs/{id}`, fetch the result |
| Second case | The two-panel set from `tools/tecopa/smoke_test.sh` step 7b, compared as a zip |
| Pass | `cmp` reports the proof PNG, the final PNG and the panel zip equal. Pixels alone are not a pass. PDF finals are not byte-stable (`smoke_test.sh:128`) and are not compared. |

**The anchor is made at the bundle's commit, not fixed in this spec.** The engine version is
written into every manifest (`app/provenance.py:54`, `:136`), so a hash made under one version
string can never match another. The reference side runs under the bundle's baked version, so
both sides stamp the same string. The report stores the reference hashes as the anchor that
proof 2 compares against.

A trial run on 2026-11-05 showed the reference side is stable. At commit `74cbc38` it rendered
the same track twice in-process, through FastAPI's TestClient and the synchronous `/api/final`,
with `TECOPA_ENGINE_VERSION=proofpin`, and got identical bytes (final sha256 `63e888d2…3146`).
That trial is not the anchor: it used a different path and a different version string.

Each run records `sys.version`, `zlib.ZLIB_RUNTIME_VERSION`, Pillow's zlib, littlecms2 and
freetype versions, numpy, scipy, rasterio, GDAL, pyproj and PROJ versions, the PROJ and GDAL
data folders, the resolved default font and its sha256, the macOS build, and the sha256 of each
wheel's `RECORD`. A difference fails the proof even when `cmp` passes.

**When `cmp` fails, diagnose in this order:** decoded pixels, then `provenance.extract` dicts,
then a chunk-by-chunk compare (IHDR, pHYs, iCCP, zTXt, IDAT). zTXt or iCCP bytes that differ
over equal content point at the interpreter's zlib. IDAT that differs over equal pixels points at
Pillow's build. Different pixels point at the wheels, fonts or PROJ and GDAL data.

**A failure stops phase 1 and goes to Dom with the diagnosis.** The handoff says the plan changes
here. One fallback exists: rebuild the reference venv on the bundle's python-build-standalone
interpreter, which removes a zlib difference. The proof then tests packaging only, not two
CPython builds, and the anchor is re-made from that reference. Taking it needs Dom's yes and a
row in `decisions.md`. To find out early, the build checks with `otool -L` whether the 3.14.2
tarball's `libpython` links `/usr/lib/libz.1.dylib`, before proof 1 runs.

### 8.2 Proof 2: the repo moved away

1. Run `scripts/macos/seed_dem_cache.sh` (5.6). Ad hoc sign the bundle. Record
   `xattr -lr <bundle>`. Rename the repo checkout.
2. Start the app from Finder, in owner mode. `/readyz` answers with the engine's shape.
3. Repeat proof 1's recipe against `<AS>/regions`. The hashes equal proof 1's anchor.
4. `codesign --verify --deep --strict` still passes, and `xattr -lr <bundle>` is unchanged.
   Nothing wrote into the bundle. Signing is the authority here: it catches any added or
   changed sealed file.
5. Prepare one order through the bundle. Phase 1 has no Orders window and no Prepare route, and
   `tecopa order prepare` still runs the repo venv (section 9), so `byte_proof.sh` runs:

   ```
   <bundle>/Contents/Resources/python-engine/bin/python3.14 -P \
       <bundle>/Contents/Resources/engine/scripts/order.py prepare <copy>
   ```

   with the full 5.3 environment from `EngineHost`, the working directory at `<AS>`, and
   `TECOPA_ORDERS_DIR=~/Tecopa Orders/_proof`. `<copy>` is a copy of a past order made under
   `~/Tecopa Orders/_proof/`, never anywhere else: it holds a customer's tracks. The copy is
   deleted at the end of the proof (to the Trash).
   - Pass: Prepare exits 0, and `work/state.json` names `<AS>/regions` as the plate root and the
     plate as curated. An exit 0 alone can hide a silent order-plate build.
   - An order prepared by the venv stores `<repo>/regions` in `work/state.json`
     (`orderprep.py:581`) and refuses with NO_PLATE once the repo moves. Prepare runs again on
     the copy. Never rewrite `state.json` by hand.
6. A region-prep smoke run, with no network: `python-prep/bin/python3.14 <bundle>/…/engine/region_prep.py
   --help`, and an import of rasterio and py3dep, both run with the 5.3 environment. Neither
   proof otherwise starts the prep interpreter, because a curated plate never needs it.
7. Rename the repo back.

## 9. TecopaKit and the `tecopa` tool

Phase 1 changes only what the new bundle id and the bundled engine force:

- **`EngineHost` (new, Foundation only):** the layout, the environment builder (5.3), spawn,
  the readiness wait and stop. The app and `tecopa doctor` share it.
- **`EngineLayout`:** `.bundle(url)` or `.repo(path)`, each giving the code root, the engine
  interpreter, the prep interpreter and the data root.
- **`Launcher`:** `bundleID = "org.plateworks.tecopa"`. Start with `open -g -b`, stop with
  `quit app id`. The start wait drops from 160 s to 70 s. The Documents and `build_app.sh`
  hints go.
- **`Doctor`:** the launcher row becomes an app row (bundle id, both interpreters run, engine
  version from Info.plist). The venv rows read the layout.
- **`ScriptRunner`** keeps its allowlist table and its app/prep column, so invariant 13 is still
  enforced in one place. In phase 1 it still runs order scripts from the repo venvs, so during
  phase 1 the CLI's order verbs and the app's engine can run different checkouts. Phase 2
  moves `tecopa` into `Contents/Helpers/` and makes `~/.local/bin/tecopa` a symlink to it.
- **Recorded now, with this spec:** `decisions.md` rows dated 2026-11-05 for each decision in
  section 2. The bundle-id row marks three older rows superseded: "The bundle id is
  `guide.badwater.tecopa` and is name-neutral", the bundle-id part of "Env vars, `localStorage`
  keys, the bundle id…", and "keep the bundle id `guide.badwater.tecopa`".
- **Amendments, made when phase 1 ships:**
  - `tecopa` spec decision 7: "The Tecopa Plateworks app (`org.plateworks.tecopa`) is the one
    owner of the engine on port 8848."
  - Its Repo path section gains the app bundle as a source, and its Venv rule says "interpreter".
  - `CLAUDE.md` invariant 9: "`TECOPA_*` are name-neutral. The bundle id is
    `org.plateworks.tecopa` (Dom, 2026-11-05): it names the business's domain, and it does not
    move again." The old rule kept the id neutral so a rebrand would not make macOS see a new
    app. That cost is paid once, now, while there is a new app anyway.
  - `docs/changing-things.md` Rebuild the macOS launcher becomes Build the Mac app.
    `docs/architecture.md`'s `scripts/macos/` row names the new files and the new id.
  - The launcher spec is marked superseded.
- **Install waits for Dom's yes.** Putting the new app at `/Applications/Tecopa Plateworks.app`
  replaces the launcher at that path, so the install is the removal. Until Dom says yes, phase 1
  builds and proves the app from `dist/`, and the launcher stays in `/Applications`. Two apps
  with one name and one port is the worse state, so the proofs require both ports free and the
  launcher not running. The first quit from each calling app raises one new Automation prompt.

## 10. Kept possible, not built

- A public release: the About box, the AGPL notice and source offer, and an update path.
  Nothing in this design blocks them.
- Settings writing `settings.json` (phase 2). The keys are the ones in 5.3.

## 11. Open items

| Item | Owner | Blocks |
| --- | --- | --- |
| The faces the canon names (Advocate Narr, Valkyrie A, Century Supra A) are not installed; `~/Library/Fonts` has the B cuts and Hermes Maia. No `TECOPA_FONT*` is bound. | Dom | Real-looking posters from the app. Not proof 1, which runs with no fonts bound. |
| Free Dropbox space for the 4.6 GB first archive | Dom | Section 6 archive |
| Do any delivered posters carry the four lost July DEMs? Does an older drive hold them? Search for sha `576ab5d6…`, `93840989…`, `46d9d174…`, `18d721ff…`. | Dom | Exact reprints of those posters |
| The python-build-standalone release tag for 3.14.2 and its SHA-256; whether its `libpython` links `/usr/lib/libz.1.dylib` | build | Proof 1 |
| Whether SIGTERM ends render workers and `region_prep` children | build | Quit behaviour |
| Whether hardened ad hoc signing loads ad hoc signed wheel dylibs | build (signing spike) | Phase 4 |
| Whether macOS prompts before the app reads `~/Library/CloudStorage/Dropbox` | build | The archive step, the intake |

## 12. Phase 0 record (2026-11-05)

The handoff said the Mac was wiped. On this date it was not missing anything phase 0 lists,
except where noted:

- Xcode 27.2, XcodeGen, uv, Homebrew and python.org Python 3.14.2 are installed.
- `.venv` and `.venv-prep` exist and import. The full suite passed: 3,472 passed, 23 skipped,
  0 failed, in 7 min 10 s.
- All 11 plates have real DEMs. `scripts/verify_regions.py` reports six DRIFT findings, the
  Lanczos swap (section 6), and no ORPHAN.
- The Red River ICC profiles are in `/Library/ColorSync/Profiles/`.
- The Developer ID Application identity (team `3JX6D7F3T4`) is in the Keychain. No Tecopa
  notary profile exists; `desqueeze-notary` works.
- The launcher is in `/Applications`, `~/.local/bin/tecopa` is installed, and its MCP server
  is connected.
- Gaps: the type-role fonts (section 11). `gdalinfo` is not installed; nothing here needs it.

## 13. Amendments made while planning (2026-11-05)

An adversarial review of the implementation plan (`superpowers/plans/2026-11-05-native-mac-app-phase-1-bundled-engine.md`)
found three places where this design could not work as written. Dom delegated these
decisions on 2026-11-05.

- **8.1, the environment record.** "A difference fails the proof" cannot hold for every
  field: `sys.version` and the data-folder paths differ between python.org and
  python-build-standalone by construction, and a wheel's `RECORD` holds its installer and
  its scripts. The record is split. The versions, the font's sha256, a tree hash of the
  PROJ and GDAL data and each wheel's `RECORD` minus installer files must match. The
  `sys.version`, the paths and the zlib version are recorded only. `cmp` stays the pass.
- **5.5, quit.** No quit skips the confirm because it came as an Apple Event: the Dock's
  Quit, logout and `osascript` all arrive that way. The one exception is
  `tecopa engine stop --force`. It writes `<AS>/.quit-forced` first, and a marker younger
  than 15 s skips the confirm.
- **9, `Launcher`.** The tool opens the app by its path (`open -g <path>`, with
  `TECOPA_APP` as an override), not by bundle id. LaunchServices may hold several copies
  under one id, Xcode's own build among them. It still quits by bundle id.
