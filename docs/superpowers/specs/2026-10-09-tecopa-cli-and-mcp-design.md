# The `tecopa` Tool: a Swift CLI and MCP Server for the Engine — Design

**Date:** 2026-10-09
**Status:** Approved by Dom (brainstorming session, 2026-10-09). All four phases are built. Phase 1: `../plans/2026-10-09-tecopa-tool-phase-1-diagnose.md`. Phases 2 to 4: `../plans/2026-10-10-tecopa-tool-phases-2-to-4.md`. Each plan's "Decisions made while planning" refine this spec, and the two sections at the end of this file list each change.
**Build:** Phase 1 was built on 2026-10-09 and phases 2 to 4 on 2026-10-10. Dom opened each build before the 2026-10-21 Now review.
**Extends:** `2026-07-18-macos-launcher-app-design.md` (the launcher, port 8848, engine ownership)
**Amends:** nothing. No invariant in `CLAUDE.md` changes.

## Goal

Claude controls and diagnoses Tecopa Plateworks through one tool, with no browser
drive. The tool is one compiled Swift binary named `tecopa`. It is a command line and
an MCP (Model Context Protocol) server at the same time.

## Why

Today Claude has three slow paths into the app. It drives the studio in a browser. It
runs one of 19 separate scripts, each with its own arguments. It reads the launcher
log by hand. The engine has no route that lists sessions, jobs, or cache state, and
the studio reports no errors to the engine. A fault in the studio is therefore
invisible until Dom describes it.

The tool is Swift, not Python, for one reason. Diagnosis matters most when the venv or
the engine is broken. A Python tool in the repo's `.venv` fails together with the
thing it must diagnose. A compiled binary does not.

## Decisions (from brainstorming)

| # | Decision |
|---|---|
| 1 | The tool does four jobs: diagnose the engine, render without the studio, run plate and order work, and inspect the studio. |
| 2 | One Swift binary is both the CLI and the MCP server. Python and "inside the launcher app" were rejected. |
| 3 | The engine gains read-only debug routes. The studio gains one module that reports its state and its errors. |
| 4 | One spec covers all four jobs. The build has four phases. No code before the 2026-10-21 review. |
| 5 | The tool is a SwiftPM (Swift Package Manager) package with a shared core library. A single dependency-free file and a CLI with no MCP server were rejected. |
| 6 | The tool holds no render logic, no coordinate math, and no spec rules. Those stay in Python. |
| 7 | The launcher stays the one owner of the engine on port 8848. The tool never starts a second uvicorn. |
| 8 | The debug routes exist only when `TECOPA_DEBUG=1`. The default is off. |
| 9 | Studio reports stay in engine memory. Nothing goes to disk. |
| 10 | No command writes `sources.json`, deletes a plate or an order, touches a font file, or publishes anything. |

## Non-goals

- A second way to render. Every render goes through the engine's existing routes.
- A replacement for the studio. Photo placement and proof approval stay there.
- Distribution. The binary is a personal build for this Mac, the same as the launcher.
- A Swift test job in CI. CI runs on Linux and stays unchanged.
- An OpenAPI document. FastAPI auto-docs stay off (commit a3d4ba9).

## Architecture

`tecopa` is a thin shell. It gets its data in three ways only.

| Source | Used for | Works when the engine is down |
|---|---|---|
| HTTP to the engine | Status, sessions, jobs, renders | No |
| Files on disk | The launcher log, `regions/`, the orders folder, `sources.json` | Yes |
| A subprocess of an existing script | Plate, label, playa, verify, pack and order work | Yes |

### Layout

All new Swift files live under `tools/tecopa/`.

| Path | Purpose |
|---|---|
| `tools/tecopa/Package.swift` | The package manifest. Two outside dependencies: Apple's swift-argument-parser and the official MCP Swift SDK. |
| `tools/tecopa/Package.resolved` | The pinned dependency versions. Committed. |
| `tools/tecopa/Sources/TecopaKit/` | The core library: the engine HTTP client, launcher control, the log reader, the script runner, run records. |
| `tools/tecopa/Sources/tecopa/` | The executable: the root command, the shared options, one thin struct per command, and the MCP server. |
| `tools/tecopa/Tests/TecopaKitTests/` | The `swift test` target. |
| `tools/tecopa/build.sh` | Builds the release binary. `--install` copies it to `~/.local/bin/tecopa`. |
| `tools/tecopa/smoke_test.sh` | A manual end-to-end check against a live engine. |

`tools/tecopa/.build/` is gitignored.

### One code path

Each command is one function in `TecopaKit` that returns a value which encodes to
JSON. The CLI command prints that value as text, or as JSON with `--json`. The MCP
tool of the same name returns the same JSON. Neither layer holds logic of its own.

### Repo path

The binary finds the repo in this order:

1. The `--repo` flag.
2. The `TECOPA_REPO` environment variable.
3. The path that `build.sh` baked into the binary at build time.

The launcher uses the same baked-path rule. A moved repo gives a clear error that
names the path and the rebuild command.

### Engine target

The default target is `http://127.0.0.1:8848`, the launcher's engine. `--port 8000`
selects a development engine. The tool never contacts any host except `127.0.0.1`.

### Engine ownership

The launcher owns uvicorn as a child process. This spec keeps that rule.

- `tecopa engine start` opens the launcher app.
- `tecopa engine stop` quits the launcher app, which stops the engine.
- `tecopa engine restart` does both, and waits for `/readyz` to answer.
- `tecopa engine status` probes `/readyz` and reports the per-region readiness.

A development engine on another port is started by hand, as it is today. The tool
reads it and does not control it.

### Venv rule

The script runner holds one fixed table that maps each script to its interpreter.
The table is an allowlist. A script with no row does not run. `region_prep.py`,
`scripts/bake_playa.py` and `scripts/dem_coverage.py` belong to `.venv-prep`. No flag
overrides the table. Invariant 13 is enforced in this one
place.

## Commands and tools

Each row is one CLI command and one MCP tool with the same name and the same JSON
result. MCP tools that do not write carry the read-only annotation, so Dom can allow
every read without a permission prompt.

| Phase | Command | Does | Writes |
|---|---|---|---|
| 1 Diagnose | `doctor` | Checks both venvs, the Python version, the port, `/readyz`, the launcher install, and the log tail | No |
| | `engine status` | Probes `/readyz` and, with the gate on, `/api/debug/engine` | No |
| | `engine start`, `engine stop`, `engine restart` | Opens or quits the launcher app | Control |
| | `logs` | Reads `~/Library/Logs/TecopaPlateworks.log` with `--lines`, `--grep`, `--since` | No |
| | `regions` | Lists plates from `/api/regions` with the readiness report | No |
| | `regions verify` | Runs `scripts/verify_regions.py` | No |
| | `jobs`, `sessions`, `caches` | Reads the debug routes | No |
| 2 Render | `render proof`, `render final`, `render wallpaper`, `render film` | Runs upload, spec, submit, poll and download as one step | Output file |
| | `render fetch` | Saves the result of a finished job | Output file |
| | `reprint inspect`, `reprint`, `continue` | The three verbs that read a poster file | Output file, except `inspect` |
| 3 Plates and orders | `plate plan` | Calls `/api/regions/plan` for a set of tracks | No |
| | `plate build`, `plate labels`, `plate playa`, `plate pack`, `plate install` | Runs the matching script in the correct venv | Yes |
| | `plate check` | Runs `python -m app.plates verify` on a poster PNG | No |
| | `order prepare` | Runs `scripts/order.py prepare` | Yes |
| | `order preview` | Runs `scripts/order.py preview` | Yes |
| | `order status` | Reads the order's `work/state.json` | No |
| | `runs`, `runs show`, `runs cancel` | Lists, reads and stops long script runs | Control |
| 4 Studio | `studio state`, `studio errors` | Reads what the studio last reported | No |

`tecopa mcp` starts the MCP server on stdio. It is the only command with no tool.

> Amended 2026-10-11: `order preview` is new, a tracked run as `order prepare` is, and
> the catalog has 34 entries. The final of a set of panels is one zip. `render final`,
> `render fetch` and `reprint` write that zip to `--out` unchanged. The tool has no
> format logic, so this took tests and one sentence in each of three summaries. See
> `2026-10-11-print-sizes-panel-sets-and-size-preview-design.md`, §8.

### Render input

`render` takes these arguments:

- `--tracks`, one or more GPX, KML or KMZ files.
- `--region`, optional. Without it the engine detects the plate from the tracks.
- `--spec file.json`, optional. A full or partial spec.
- `--set key=value`, repeated. One spec field for each use.
- `--out`, required. The output path.

The tool sends every value to the engine unchanged. The engine validates. The tool
has no copy of `STYLE_BOUNDS` and no default for any spec field.

### Render output

The tool refuses to overwrite an existing file. The JSON result names the output
path, the session id, the job id, and the `engine_version` from the manifest.

### Long runs

A plate build can take many minutes, and an MCP call must return quickly. A script
that can run long therefore starts detached, and the command returns a run id at
once.

- One record for each run lives under `~/Library/Application Support/TecopaPlateworks/runs/`.
- A record holds the command, the process id, the start time, the log path, and the exit code.
- `runs show` returns the state and the tail of the run's log.
- `runs cancel` sends SIGTERM to the run's process.

This is a record of script runs only. The engine still has no PID file, as the
launcher spec requires.

The engine's own render jobs are different. `render` polls `/api/jobs/{jid}` and
returns when the job ends. `render --no-wait` returns the job id at once.

### Never exposed

- No command writes or re-stamps `sources.json` (invariant 12).
- No command deletes a plate, an order, a run log, or a render.
- No command reads or writes a font file (invariant 10).
- No command deploys or publishes.
- `allow_plate_mismatch` is sent only with an explicit `--allow-plate-mismatch` flag.

## The debug routes

### The gate

The debug routes exist only when `TECOPA_DEBUG=1`. With the gate off, each route
returns 404, the same as a route that does not exist. The launcher sets the variable
when it starts the engine. This needs one line in `TecopaPlateworksLauncher.swift`
and one launcher rebuild.

### The routes

A new module, `app/debug.py`, holds one `APIRouter`. `app/main.py` includes it when
the gate is on.

| Route | Returns |
|---|---|
| `GET /api/debug/engine` | `engine_version`, the process id, the uptime, the Python version, every `TECOPA_*` variable, the store kind, the three queue widths |
| `GET /api/debug/jobs` | Every job in the three queues: id, queue name, state, progress text, the submit, start and end times, error text |
| `GET /api/debug/sessions` | Each session: id, region id, track count, hotspot count, whether a spec exists |
| `GET /api/debug/sessions/{sid}` | The spec as JSON and a summary of each track. Track geometry only with `?full=1`. |
| `GET /api/debug/caches` | `BASE_CACHE.stats()` and `INK_CACHE.stats()` |
| `POST /api/debug/studio` | Receives one report from the studio |
| `GET /api/debug/studio` | The latest state for each browser tab, and the last 50 errors |

Every route is read-only except the studio post, and the studio post changes only
the report buffer. No debug route changes a session, a job, a cache, or a plate.

### Engine additions

- `ThreadJobQueue.snapshot()` returns a copy of every job's status under the queue's lock.
- `MemoryStore.ids()` and `SqliteStore.ids()` return the session ids.

Both are read-only. `ThreadJobQueue` also records each job's start time and its own width, so `submit` and `__init__` each gained one line.

## The studio hook

One new module, `app/static/debug.js`. It is the studio's 23rd ES module.

- It catches uncaught errors and rejected promises.
- It watches the store. After a change it waits 2 seconds, then posts one report.
- A report holds a tab id, the session id, the target, the view, and the last API error.
- The tab id is random and new on each page load.
- If the first post gets a 404, the gate is off and the module stops for that page load.
- A failed post is silent. The hook must never break the studio.

The engine keeps the reports in a fixed-size buffer in memory: the latest state for
each tab, and the last 50 errors. A post larger than 64 KB gets a 413. A restart of
the engine empties the buffer.

## Errors

The tool reports what the engine says and adds nothing.

- An engine 4xx or 5xx body passes through unchanged in the result.
- A 422 at the zoom cap and a 503 that names drift are correct answers. The tool never retries around them.
- Each failure has a `kind`, a `message`, and a `hint`.
- An unreachable engine gives the hint "run `tecopa doctor`".
- With the gate off, a debug command says so and names `TECOPA_DEBUG`.

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 1 | The engine or a script refused |
| 2 | Usage error |
| 3 | Engine unreachable |
| 4 | Environment fault: a missing repo, venv, script, or launcher |
| 64 | A usage error that the argument parser finds, the parser's standard code |

An MCP tool returns the same failure as a tool result with the error flag set.

## Tests

| Layer | Test | Runs |
|---|---|---|
| `TecopaKit` | `swift test`: the HTTP client against a stub, the venv table, run records, the repo path order, the overwrite refusal | Mac only |
| MCP | One test starts `tecopa mcp`, lists the tools, and checks that every command has a tool with the correct read-only annotation | Mac only |
| Debug routes | `tests/test_debug.py`: each route, the 404 with the gate off, the 413, the buffer limits | Mac and CI |
| Engine additions | `snapshot()` in `tests/test_server_foundation.py`, `ids()` for both stores | Mac and CI |
| Studio hook | `node --check`, a text check in `tests/test_static_registry.py`, one browser drive | Mac |
| End to end | `tools/tecopa/smoke_test.sh` against a live engine | Mac, manual |

The Swift code has no CI, the same as the launcher. A break in it is found only on
the Mac.

## Documentation

A phase is not done until its documents are.

| Document | Change |
|---|---|
| `docs/architecture.md` | Module map rows for `app/debug.py`, `app/static/debug.js` and the Swift package. A `TECOPA_DEBUG` and a `TECOPA_REPO` row in the environment table. "22 ES modules" becomes 23. A delivery row for the binary. |
| `docs/changing-things.md` | Two procedures: build the `tecopa` tool, and add a command. |
| `CLAUDE.md` | One router row that sends a change to the tool to this spec. The file stays under 2,000 tokens. |
| `docs/decisions.md` | One dated entry: Swift not Python, the gate, launcher ownership kept. |
| `docs/README.md` | A row for this spec now. A row for the plan when it is written. |
| `.gitignore` | `tools/tecopa/.build/` |

## Registration

- Register `tecopa mcp` at user scope in Claude Code, so each session on this Mac has it.
- Register it in the Claude desktop app only after the file-grant check below passes.
- Dom runs or approves each registration. It is a change to his Claude configuration.

## Phases

Each phase ships alone and has one proof.

| Phase | Contains | Proof |
|---|---|---|
| 1 Diagnose | The package, `doctor`, `engine`, `logs`, `regions`, the gate, the engine, jobs, sessions and caches routes, the MCP server | With the engine stopped, `tecopa doctor` names the cause. With it running, Claude lists jobs through MCP. |
| 2 Render | `render`, `reprint`, `continue` | A final PNG from `tecopa` is byte-identical to the studio's for the same spec and seed (invariant 3). |
| 3 Plates and orders | `plate`, `order`, `runs` | A small plate build completes as a tracked run. Then `regions verify` passes. |
| 4 Studio | The studio routes, `app/static/debug.js`, `studio state`, `studio errors` | An error thrown in the browser shows in `tecopa studio errors`. |

Phase 1 comes first because the other three depend on its package and its gate.
Phases 2, 3 and 4 do not depend on each other.

## Checks the plan must make first

| # | Check | Why |
|---|---|---|
| 1 | The official MCP Swift SDK builds with Swift 6.4 on this Mac, and its license fits AGPL-3.0-or-later. | Not verified in this session. If it fails, the fallback is a hand-written stdio JSON-RPC layer inside `TecopaKit`. |
| 2 | The binary can read the repo under `~/Documents` when Claude Code starts it, and when the Claude desktop app starts it. | macOS protects that folder. A child process inherits the grant of the app that starts it. The launcher spec records the same trap. |
| 3 | The privacy claims in `tests/test_marketing_page.py` stay true with the studio hook. | The hook posts only to the local engine, but the claims are tested and the test must be read before the hook is built. |
| 4 | Quitting the launcher app from a script stops the engine cleanly. | `scripts/macos/smoke_test.sh` does this with `osascript`. The plan confirms that it works from the binary. |

## Changes made while phase 1 was built

The phase 1 plan records each one under "What changed while it ran".

- Global options go after the subcommand.
- An MCP tool name uses an underscore for each space in the command.
- Each MCP tool also takes an optional `port`.
- `engine start` waits up to 160 seconds, not 75.
- `logs --since` takes a duration (`90s`, `30m`, `2h`, `1d`), and `--lines` is limited to 1 to 2000.
- `regions verify` reports a crash of the script as a failure, and returns the script's stderr.
- The debug routes refuse a request whose Host header is not local, with a 403.
- `engine stop` and `engine restart` refuse while a job is running or queued, unless `--force` is given, and report how many jobs and sessions they ended.
- Check 2 names the wrong mechanism for the desktop app. That app starts each server through its `disclaimer` helper, so the binary does not inherit the app's grant: it answers for its own access. The check passed in that launch form on 2026-10-09. `tools/tecopa/register_desktop.sh` registers the server there, with the app quit.

## Changes made while phases 2 to 4 were built

The plan of 2026-10-10 records each one under its decisions.

**Render**

- `--spec` is a flat JSON object of `/api/proof` form fields, because the proof route takes form fields and not a spec document. `--set` is one such field. A new option, `--opt`, is one field of the output route.
- The tool checks each field name against a new debug route, `GET /api/debug/forms`. The engine names its own fields, and the tool holds no copy.
- The crop comes from the engine: the upload answer's `starter_crop`, or `GET /api/debug/sessions/{sid}/starter_crop` for another print size. `--crop` overrides it.
- `render` takes `--session`. A change to a session starts from `GET /api/debug/sessions/{sid}/proof_form`, so one `--set` keeps the rest of the look.
- A fifth command, `render fetch`, saves the result of a finished job. `--no-wait` had no way to get its file.
- `/api/continue` returns one additive key, `proof_form`. `continue` sends it to the proof unchanged.
- A result names `out`, `bytes`, `sha256`, the session, the job, and the engine's own warnings. `engine_version` is the running engine's, from `/api/debug/engine`, and is left out with the gate off.
- A path argument is absolute at the MCP level. The command line converts a relative path.
- A poll that times out is one more wait, because a studio proof blocks the engine's event loop. A poll that gets no answer ends the wait and names the job.

**Plates and orders**

- A command may create a `sources.json` entry and never replaces one. The spec's "No command writes `sources.json`" could not hold: `region_prep.py`, `scripts/build_labels.py` and `scripts/bake_playa.py` each write it.
- `plate install` takes a local file only and never passes `--replace`. `plate pack --resync` needs the explicit flag.
- `plate build`, `plate labels`, `plate playa` and `order prepare` are tracked runs. `plate pack`, `plate install` and `plate check` run in the call.
- A run has five states: `running`, `done`, `failed`, `cancelled` after `runs cancel`, and `lost` for a run with no exit code and no process. The process is matched by its run name as a whole word. `runs show` reads at most the last 1 MB of the log, and the failure-text rule reads the last 4 MB.
- A script gets the tool's environment without `PYTHONHOME`, `PYTHONPATH`, `PYTHONSTARTUP` and `__PYVENV_LAUNCHER__`, so no caller variable changes what the table's interpreter loads. `order prepare` still reads `TECOPA_PREP_PYTHON`, which is the order script's own setting.
- "No command deletes a plate" holds for `regions/`. `order prepare` rebuilds the order's own plate under `work/plate/`, as the script always did.
- `plate build --bbox` is one word with commas, because the argument parser reads a negative number as an option.
- `scripts/dem_coverage.py` has no row in the script table. No command runs it.

**Studio**

- The hook compares its state each 2 seconds and does not subscribe, because the store announces only some changes.
- "The last API error" is the error toast. The studio keeps no last error.
- With the gate off the first post gets a 405, not a 404. Any first reply that is not 2xx stops the hook. A post with no answer does not stop it: the hook waits 30 seconds, so an engine restart does not end the reports.
- The studio post needs a JSON content type and refuses an Origin header that is not local. The buffer holds 20 tabs and 50 errors.
- `studio errors` takes `--tab` and `--kind` (`error`, `rejection` or `toast`).
- A studio post that carried no error is logged at DEBUG, and its access line is dropped, so the reports do not fill the launcher log.
- The debug routes are no longer all read-only. The studio post changes its report buffer and nothing else.
- Check 3 was made on 2026-10-10. `tests/test_marketing_page.py` tests only the published Ghost pages. A new text test holds each studio module to its own origin.

## Rejected

| Option | Why not |
|---|---|
| A Python `tecopa` in `.venv` | It fails when the venv fails. It adds the MCP package to the pinned lock file. |
| The MCP server inside the launcher app | Control exists only while the app runs. The 256-line launcher grows much larger. |
| One Swift file built with `swiftc`, no dependencies | A hand-written protocol layer with no test target. A diagnosis tool must not add a new thing to diagnose. It stays as the fallback for check 1. |
| A CLI with no MCP server | The Claude desktop app and Cowork have no shell, so they get no access. |
| The tool starts its own uvicorn | Two owners of one engine. The launcher spec rejected PID files and orphan detection for this reason. |
| Debug routes always on | Any other host that runs the engine gets routes that list sessions and tracks. |
| Studio reports written to a file | The product has no database by default. A report file is the start of one. |
