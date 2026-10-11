# The `tecopa` Tool, Phases 2 to 4: Render, Plates and Orders, Studio — Implementation Plan

> **For agentic workers:** Build one task at a time, in order, on the branch `build/tecopa-phases-2-4`. One builder and one independent reviewer for each task. Each task is test-first and ends with one commit.

**Goal:** Claude renders, runs plate and order work, and reads the studio's state and errors through the `tecopa` tool, with no browser drive.

**Architecture:** Phase 1 fixed the shapes: one `CatalogEntry` for each operation in `TecopaKit`, one thin CLI struct for each, and the MCP server reads the same catalog. Phases 2 to 4 add entries, three seams (HTTP POST, binary files, detached runs), and a few read-only engine routes behind the `TECOPA_DEBUG` gate. The tool still holds no render logic, no coordinate math and no spec rules.

**Tech stack:** Swift 6 toolchain in Swift 5 language mode, swift-argument-parser, the MCP Swift SDK, Foundation. Python 3.14 and FastAPI for the engine side. No new dependency.

**Spec:** `../specs/2026-10-09-tecopa-cli-and-mcp-design.md`. **Phase 1 record:** `2026-10-09-tecopa-tool-phase-1-diagnose.md`.

**Opened:** 2026-10-10. Dom opened phases 2 to 4 before the 2026-10-21 Now review ("Just go ahead with phases 2 to 4").

---

## Before you start

1. Read `CLAUDE.md` (the invariants), then the spec, then `docs/changing-things.md`, "Build the tecopa tool" and "Add a tecopa command".
2. Read `tools/tecopa/Sources/TecopaKit/Catalog.swift`, `EngineEntries.swift`, `ScriptRunner.swift` and `Tests/TecopaKitTests/Fakes.swift`. A new entry copies their form.
3. Python checks: `.venv/bin/python -m pytest -n auto -m "not slow" -q`. Swift checks: `swift test --package-path tools/tecopa`. Both must pass before each commit. Compare the failure set, not the totals.
4. Never: write `sources.json`, delete a plate or an order, touch a font file, install anything into `.venv`, weaken the terrain guard, or start a second uvicorn on port 8848.
5. Do not rebuild or reinstall the binary at `~/.local/bin/tecopa` inside a task. The last task does it one time, because macOS can ask for the Documents folder access again after each rebuild.

## Decisions made while planning (they refine the spec)

1. **One plan covers the three phases.** They share the seams, and each phase still ships with its own proof.
2. **The proof route takes form fields, not a spec document.** `POST /api/proof` has about 40 form fields and a crop in overview pixels. So `--spec file.json` is a flat JSON object of proof form fields, and `--set key=value` is one such field. The tool sends each value unchanged.
3. **The engine names its own form fields.** FastAPI ignores a form field that it does not know, and the tool must refuse a misspelled name, not ignore it. A new debug route, `GET /api/debug/forms`, returns the field names of each render route by introspection. The tool checks each `--set`, `--spec` and `--opt` name against that list. The tool holds no copy of the names.
4. **`--set` is the picture, `--opt` is the container.** `--set` goes to `/api/proof`. `--opt` goes to the output route: `format` and `embed_spec` for a final, the pacing fields for a film.
5. **The crop comes from the engine.** Without `--crop`, the tool uses the upload answer's `starter_crop`, which is for 17 × 22. When `print_w` or `print_h` is set, the tool asks a new debug route, `GET /api/debug/sessions/{sid}/starter_crop`, which calls `geo.starter_crop`. Coordinate math stays in `app/geo.py` (invariant 5).
6. **`render` also takes `--session`.** With a session id and no tracks, the tool renders the session's stamped spec. This is how Claude renders a final from the studio session that Dom has open.
7. **A fifth render command, `render fetch`.** `--no-wait` returns a job id, and an MCP call must return quickly. `render fetch --job <jid> --out <path>` saves the result of a finished job. The spec had no way to do this.
8. **`engine_version` in a render result is the running engine's.** It comes from `/api/debug/engine`, which is the value the engine stamps into the manifest. The tool does not decode a PNG. With the gate off the field is null.
9. **`/api/continue` gains one additive key, `proof_form`.** A continued poster keeps its look only if the next proof sends the same fields. The studio maps `prefill` to form fields in JavaScript, and the tool must not copy that mapping. The engine now returns the exact `/api/proof` form fields for the file's spec. A round-trip test proves the mapping.
10. **A render result also names `bytes` and `sha256`.** The phase 2 proof compares two files, and a caller can check a download.

## File map

| Path | Phase | Change |
|---|---|---|
| `app/debug.py` | 2, 4 | New routes: `forms`, `sessions/{sid}/starter_crop`, `studio` (POST and GET) |
| `app/main.py` | 2 | `/api/continue` returns `proof_form` |
| `app/static/debug.js` | 4 | New: the studio's report module |
| `tests/test_debug.py` | 2, 4 | Tests for each new route |
| `tools/tecopa/Sources/TecopaKit/Seams.swift`, `Runtime.swift`, `EngineClient.swift` | 2, 3 | POST with a multipart body, a reply with its content type, binary file read and exclusive write, a detached start |
| `tools/tecopa/Sources/TecopaKit/Multipart.swift` | 2 | New: the multipart encoder |
| `tools/tecopa/Sources/TecopaKit/Render.swift` | 2 | New: the five `render_*` entries |
| `tools/tecopa/Sources/TecopaKit/Reprint.swift` | 2 | New: `reprint_inspect`, `reprint`, `continue` |
| `tools/tecopa/Sources/TecopaKit/Runs.swift` | 3 | New: run records, `runs`, `runs_show`, `runs_cancel` |
| `tools/tecopa/Sources/TecopaKit/Plates.swift`, `Orders.swift` | 3 | New: the `plate_*` and `order_*` entries |
| `tools/tecopa/Sources/TecopaKit/Studio.swift` | 4 | New: `studio_state`, `studio_errors` |
| `tools/tecopa/Sources/TecopaKit/ScriptRunner.swift` | 3 | New rows in the script table |
| `tools/tecopa/Sources/TecopaKit/Catalog.swift` | all | `Catalog.all` lists the new entries |
| `tools/tecopa/Sources/tecopa/Commands.swift`, `Tecopa.swift` | all | One thin struct for each command |
| `tools/tecopa/Tests/TecopaKitTests/` | all | One test file for each new source file; `Fakes.swift` and `MCPServerTests.swift` grow |
| `tools/tecopa/smoke_test.sh` | all | One block for each phase proof |
| `docs/architecture.md`, `docs/changing-things.md`, `docs/decisions.md`, `docs/README.md`, the spec | all | See the last task of each phase |

---

# Phase 2: Render

## Task 1: The engine names its form fields and its starter crop

**Goal:** Two read-only debug routes that let the tool check a field name and get a crop without a copy of engine rules.

**Files:** `app/debug.py`, `tests/test_debug.py`.

**Routes:**

- `GET /api/debug/forms` returns `{"proof": [...], "final_submit": [...], "wallpapers_submit": [...], "timelapse_submit": [...], "reprint": [...], "continue": [...]}`. Each list holds the parameter names of that route function, read with `inspect.signature`, in declaration order. A file parameter (`file`, `files`) is in the list.
- `GET /api/debug/sessions/{sid}/starter_crop?print_w=<float>&print_h=<float>` returns `{"starter_crop": [x0, y0, x1, y1]}` in overview pixels. It calls `geo.starter_crop` with the session's tracks, the same call as `/api/upload` makes. An unknown session is 404 with the detail "Unknown session". A size that is not finite and positive is 422.

**Acceptance criteria:**

- [ ] `forms["proof"]` contains `session_id`, `x0`, `title`, `print_w`, `soft_light` and `bleed`, and equals `list(inspect.signature(main.proof).parameters)`.
- [ ] A test fails if a route function is renamed and the table is not updated (the route reads the functions by reference, not by name string).
- [ ] `starter_crop` with `print_w=17&print_h=22` equals the `starter_crop` that `/api/upload` returned for the same session.
- [ ] `starter_crop` with `print_w=11&print_h=17` has the aspect 11/17 within 1e-6.
- [ ] Both routes answer 404 with the gate off, and 403 for a Host header that is not local, the same as the other debug routes.
- [ ] Neither route changes the session (a test reads the session before and after).

**Verify:** `.venv/bin/python -m pytest tests/test_debug.py -q` passes, then the fast suite.

## Task 2: `/api/continue` returns `proof_form`

**Goal:** The engine gives the exact proof fields for a continued poster, so no client copies the mapping.

**Files:** `app/main.py` (the `continue_poster` route and one helper, `_proof_form_for(spec)`), `tests/test_editions.py`, `docs/MANIFEST.md` only if it lists the continue answer.

**Rules:**

- `proof_form` is a JSON object. Its keys are `/api/proof` form field names. It holds every field that `_build_spec` reads from the form, except `session_id` and the four crop fields.
- A title-less poster gives `"title": "-"`, the same rule as `prefill`.
- A journey-light poster gives `light_mode: "journey"` with `sun_azimuth_deg` and `sun_altitude_deg`, and no `sun_hour`.
- A wallpaper gives `output: "wallpaper"` and `wallpaper_preset`, or the three `custom_*` fields for a custom device.
- A key with a null value is left out, so each value can go into a form unchanged.
- `prefill` and every other key of the answer stay byte-for-byte the same.

**Acceptance criteria:**

- [ ] Round trip: build a session, send a proof with non-default values for at least 12 style fields, make a final, send the final to `/api/continue`, then send `proof_form` plus the answer's `starter_crop` to `/api/proof` for the new session. The new stamped spec equals the first spec in every field except `edition`, and `crop` within 1e-3 metres.
- [ ] The same round trip passes for a title-less poster, a journey-light poster and a wallpaper preset.
- [ ] Every key of `proof_form` is in `inspect.signature(main.proof).parameters`.
- [ ] The existing continue tests pass unchanged.

**Verify:** `.venv/bin/python -m pytest tests/test_editions.py tests/test_provenance.py tests/test_oblique.py tests/test_output_fitness.py -q`, then the fast suite.

## Task 3: The Swift seams for a render

**Goal:** The tool can POST a multipart form, read a reply's content type, read a binary file, and write a new file without an overwrite.

**Files:** `Seams.swift`, `Runtime.swift`, `EngineClient.swift`, new `Multipart.swift`, `Tests/TecopaKitTests/Fakes.swift`, new `MultipartTests.swift`, `EngineClientTests.swift`, `SeamsTests.swift`.

**Shapes:**

```swift
public struct HTTPReply: Sendable { public let status: Int; public let contentType: String?; public let body: Data }

public protocol HTTPFetching: Sendable {
    func get(_ url: URL, timeout: TimeInterval) async throws -> (status: Int, body: Data)   // unchanged
    func send(_ request: URLRequest, timeout: TimeInterval) async throws -> HTTPReply      // new
}

public struct Multipart {
    public init(boundary: String = "tecopa-" + UUID().uuidString)
    public mutating func field(_ name: String, _ value: String)
    public mutating func file(_ name: String, filename: String, _ data: Data)
    public var contentType: String { get }
    public func body() -> Data
}

// Runtime
public var readData: @Sendable (String) -> Data?
public var writeNew: @Sendable (String, Data) throws -> Void     // fails if the path exists

// EngineClient
public func post(_ path: String, _ form: Multipart, timeout: TimeInterval = 300) async throws -> HTTPReply
public func download(_ path: String, timeout: TimeInterval = 300) async throws -> HTTPReply
public func json(_ reply: HTTPReply, for path: String) throws -> JSONValue   // a non-2xx is `refused` with the engine's body
```

**Rules:**

- `send` uses the same session rules as `get`: no proxy, no redirect followed, 127.0.0.1 only. `post` and `download` build the URL with `address(_:)`.
- A field name or a filename with `"`, CR or LF is a usage failure. The encoder never writes one into a header.
- `writeNew` creates the file with `O_CREAT | O_EXCL`, writes to it, and removes it if the write fails. An existing path is a usage failure: "A file is already at <path>." The tool never overwrites.
- `FakeWorld` records each POST (path, fields in order, file names and byte counts), answers from `serve("POST /path", …)` or a new `serveData`, holds binary files, and records each write.
- A timeout on `post` or `download` is the same `engine_unreachable` failure as on `get`, with the hint "It may be busy with a render."

**Acceptance criteria:**

- [ ] `Multipart` output for two fields and one file equals an expected byte string in a test, CRLF line ends included.
- [ ] `post` to a path that does not start with a slash is a usage failure, and no request is sent.
- [ ] A 422 with a JSON body comes back as `refused`, status 422, with the body unchanged.
- [ ] `writeNew` on an existing file throws, and the file's bytes are unchanged (real temp directory test).
- [ ] The redirect test from phase 1 also covers `send`.

**Verify:** `swift test --package-path tools/tecopa` passes with more tests than 128 and 0 failures.

## Task 4: The `render` entries

**Goal:** `render proof`, `render final`, `render wallpaper`, `render film` and `render fetch` as catalog entries and CLI commands.

**Files:** new `Render.swift`, `Catalog.swift`, `Commands.swift`, `Tecopa.swift`, new `RenderTests.swift`.

**Parameters** (each entry takes the ones that apply):

| Name | Kind | Meaning |
|---|---|---|
| `tracks` | stringArray | GPX, KML or KMZ paths. One of `tracks` and `session` is required, never both. |
| `session` | string | A session id (hexadecimal). The tool sends no upload. |
| `region` | string | A region id. Sent as `region_id` with the upload. |
| `spec` | string | The path of a JSON file: one flat object of proof form fields. |
| `set` | stringArray | `key=value`. A proof form field. Wins over `spec`. |
| `opt` | stringArray | `key=value`. A field of the output route. Not for `render proof`. |
| `crop` | string | `x0,y0,x1,y1` in overview pixels. |
| `presets` | stringArray | `render wallpaper` only, required. Wallpaper preset ids. |
| `out` | string | The output path. Required, except with `no_wait`. |
| `no_wait` | boolean | Return the job id at once. Not for `render proof`. |
| `job` | string | `render fetch` only: the job id. |

**Flow:**

1. Check the arguments. Refuse `out` if a file is there or its folder is missing. This is before any request.
2. If `set`, `spec` or `opt` names a field: get `/api/debug/forms` and refuse an unknown name with the list of names. The reserved names `session_id`, `x0`, `y0`, `x1`, `y1`, `files`, `file`, `presets` are refused in `set`, `spec` and `opt`.
3. With `tracks`: POST `/api/upload` with one `files` part for each path, and `region_id` if given. Keep `session` and `starter_crop` from the answer. Do not keep the track geometry in the result.
4. The crop: `crop`, else the debug `starter_crop` route when `print_w` or `print_h` is set, else the upload's `starter_crop`. With `session` and no `crop`, and with any `set` or `spec`, the tool asks the debug route.
5. The proof: POST `/api/proof`. It is skipped only for `session` with no `set`, no `spec` and no `crop`, where the stamped spec is used.
6. `render proof` writes the proof PNG to `out`. The other three POST their route (`/api/final/submit`, `/api/wallpapers/submit`, `/api/timelapse/submit`) with `session_id` and the `opt` fields.
7. With `no_wait`, return the job id. Else poll `GET /api/jobs/{jid}` each second through `runtime.sleep`, for at most 900 seconds. `done` leads to `GET /api/jobs/{jid}/result` and `writeNew`. `error` is a `refused` failure with the job's error text.
8. A poll that runs out of time is a failure that names the job id and the hint "Run `tecopa render fetch`."

**Result:** `{"out", "bytes", "sha256", "session", "job", "engine_version", "region", "skipped"}`. `skipped` is the wallpaper route's list. `frames` is added for a film. A key with no value is left out.

**Rules:**

- The tool sends each value as the caller wrote it. It has no default for any field and no range check.
- Every engine 4xx and 5xx passes through as `refused` with the engine's body. No retry.
- `render fetch` on a job that is not `done` is `refused` with the engine's 409 body.
- A session id and a job id are hexadecimal, checked before they go into a URL path.
- CLI: `tecopa render proof --tracks a.gpx b.gpx --set title=Lassen --out p.png`. `--set`, `--opt`, `--tracks` and `--presets` repeat or take several values.
- `render_proof`, `render_final`, `render_wallpaper`, `render_film` and `render_fetch` are not read-only: each writes a file.

**Acceptance criteria:**

- [ ] A `FakeWorld` test for each command checks the requests in order, the form fields sent, and the bytes written.
- [ ] An existing `out` fails before any request (the fake records none).
- [ ] An unknown `set` name fails before the upload, and the message lists the engine's names.
- [ ] `set` wins over `spec` for the same key, and a `spec` file that is not a flat object of scalars is a usage failure.
- [ ] A job that ends in `error` gives `refused` with the engine's text, and no file is written.
- [ ] `no_wait` returns after the submit, with no poll.
- [ ] The poll stops at 900 seconds of fake time with the job id in the failure.

**Verify:** `swift test --package-path tools/tecopa`, 0 failures.

## Task 5: `reprint inspect`, `reprint` and `continue`

**Goal:** The three verbs that read a poster file.

**Files:** new `Reprint.swift`, `Catalog.swift`, `Commands.swift`, new `ReprintTests.swift`.

**Entries:**

- `reprint_inspect` (`file`): POST `/api/reprint/inspect`, return the answer. Read-only.
- `reprint` (`file`, `out`, `opt`, `allow_plate_mismatch`, `no_wait`): POST `/api/reprint`. A 2xx reply that is not JSON is the poster: write it to `out`. A JSON reply with `job` is a film: poll and fetch as in task 4.
- `continue` (`file`, `tracks`, `set`, `opt`, `crop`, `out`, `allow_plate_mismatch`, `no_wait`): POST `/api/continue`. Then POST `/api/upload` with `session_id` and the new tracks, if any. Then the proof with `proof_form`, changed by `set`, and the crop: `crop`, else the continue answer's `starter_crop`. Then the final, as in task 4. The result adds `edition`.

**Rules:**

- `allow_plate_mismatch` is sent only when the caller gives it as true. A 422 that names a plate mismatch passes through unchanged.
- A file over 96 MB is refused by the engine, not by the tool.
- `continue` shares the render flow code with task 4. It does not copy it.

**Acceptance criteria:**

- [ ] `reprint` writes the reply bytes for a still, and follows the job for a film (two fake tests).
- [ ] `continue` sends `proof_form` values unchanged, and a `set` value replaces one of them.
- [ ] No request carries `allow_plate_mismatch` unless the argument is true.
- [ ] `reprint_inspect` is read-only in the catalog, and the other two are not.

**Verify:** `swift test --package-path tools/tecopa`, 0 failures.

## Task 6: Phase 2 documents, MCP test, smoke block and proof

**Goal:** Phase 2 is documented and proven.

**Files:** `MCPServerTests.swift`, `tools/tecopa/smoke_test.sh`, `docs/architecture.md`, `docs/changing-things.md`, `docs/decisions.md`, `docs/README.md`, the spec (status line, the command table, "Changes made while phases 2 to 4 were built").

**Acceptance criteria:**

- [ ] The MCP test lists every phase 2 tool and checks each read-only annotation.
- [ ] `smoke_test.sh` has a render block: `render final` on `tests/fixtures/sample.gpx`, then the same requests with `curl`, then `cmp` of the two files.
- [ ] The documents name each new command, the two debug routes, the `proof_form` key and the `--set` and `--opt` rule. `tests/test_docs.py` passes.
- [ ] **Proof (invariant 3):** on one engine build, the final PNG from `tecopa render final` is byte-identical to the final from the same form fields sent with `curl`. The `cmp` output and both SHA-256 values go into this plan under "What changed while it ran".

**Verify:** the fast Python suite, `swift test`, and the proof run against the launcher's engine on the branch.

---

# Phase 3: Plates and orders

## Decisions for phase 3 (they refine the spec)

11. **Three of the scripts write `sources.json`.** `region_prep.py` writes it whole, and `scripts/build_labels.py` and `scripts/bake_playa.py` add one asset entry. The spec says no command writes or re-stamps it. The rule is now exact: a command may create an entry, and never replaces one. `plate build` refuses when `regions/<id>` exists. `plate labels` refuses when `sources.json` already lists `labels.json`. `plate playa` refuses when it already lists `playa.json`. A drifted asset therefore stays drifted (invariant 12).
12. **`plate install` takes a local file only, and never `--replace`.** `--replace` deletes the installed plate, and a URL makes the script download up to 2 GiB.
13. **`plate pack --resync` is sent only with an explicit `--resync`.** It changes the zip's copy of `sources.json`, never the plate's.
14. **The script table also holds a module row.** `plate check` and `plate install` run `python -m app.plates`, which is not a script path.
15. **Long commands are tracked runs: `plate build`, `plate labels`, `plate playa`, `order prepare`.** Each one reads the network. `plate pack`, `plate install` and `plate check` read only the disk, so they run in the call.
16. **`bake_playa.py` exits 0 when a plate fails.** A run record can name a failure text. `runs show` reports the state `failed` when the exit code is not 0, or when the log holds that text.
17. **`dem_coverage.py` gets no row.** No command in the spec's table runs it. `order prepare` calls it by itself.
18. **The phase 3 proof builds its plate through `order prepare`, in a folder outside the repo.** That is a real `region_prep.py` build as a tracked run, and it writes nothing under `regions/`. A real `plate build` into `regions/` waits for Dom's next plate.

## Task 7: Tracked runs

**Goal:** A script can start detached, and `runs`, `runs show` and `runs cancel` read and stop it.

**Files:** new `Runs.swift`, `Seams.swift` (a detached start on `ProcessRunning`), `Runtime.swift`, `Catalog.swift`, `Commands.swift`, `Fakes.swift`, new `RunsTests.swift`.

**Shapes:**

- The folder is `<home>/Library/Application Support/TecopaPlateworks/runs/`. A run id is `YYYYMMDD-HHMMSS-<6 hex>`.
- `<id>.json` is the record: `{"id", "command", "argv", "cwd", "pid", "started", "log", "exit_file", "failure_text"}`. `command` is the catalog name, for example `plate_build`.
- `<id>.log` holds the script's stdout and stderr. `<id>.exit` holds the exit code, written when the script ends.
- The detached start runs `/bin/sh -c 'log=$1; code=$2; shift 2; "$@" >>"$log" 2>&1; echo $? >"$code"' tecopa-run-<id> <log> <exit file> <program> <arguments…>`. No argument goes through shell parsing. The child is in its own session, so it outlives the tool and a terminal close. `PYTHONUNBUFFERED=1` is set, so the log is current.
- `ScriptRunner.start(_ row, _ arguments, command:, failureText:, runtime) -> JSONValue` checks the table, the interpreter, then starts and writes the record. It returns `{"run": id, "pid", "log"}`.

**Entries:**

- `runs` (read-only): every record, newest first, each with its state.
- `runs_show` (`run`, `lines` 1 to 2000, default 40; read-only): the record, the state, the exit code, and the tail of the log.
- `runs_cancel` (`run`): sends SIGTERM to the run's process group. Not read-only.

**State rules:**

- `running`: no exit file, and `ps -o command= -p <pid>` contains `tecopa-run-<id>`.
- `done`: exit code 0, and the log does not contain the record's `failure_text`.
- `failed`: any other exit code, or the failure text is in the log.
- `lost`: no exit file and no such process. The Mac restarted, or the run was killed.
- `runs cancel` refuses unless the state is `running`. This also stops a signal to a process id that macOS gave to another program.

**Rules:** A run id is checked against its pattern before it goes into a path. No command deletes a record or a log.

**Acceptance criteria:**

- [ ] A real test starts `/bin/sh -c 'echo hi; exit 3'` detached in a temp home, waits for the exit file, and reads state `failed`, exit code 3 and the log text.
- [ ] A real test starts `sleep 30`, cancels it, and finds the process gone within 5 seconds.
- [ ] A fake test covers each state, the newest-first order, and the `lines` limits.
- [ ] A run with `failure_text` "FAILED" and exit code 0 is `failed` when the log holds the text.
- [ ] `runs_cancel` on a `done` run is refused and sends no signal.

**Verify:** `swift test --package-path tools/tecopa`, 0 failures.

## Task 8: The `plate` entries

**Goal:** `plate plan`, `plate build`, `plate labels`, `plate playa`, `plate pack`, `plate install` and `plate check`.

**Files:** new `Plates.swift`, `ScriptRunner.swift` (rows, and the module row form), `Catalog.swift`, `Commands.swift`, new `PlatesTests.swift`, `ScriptRunnerTests.swift`.

**Script table rows:**

| Row | Venv | Used by |
|---|---|---|
| `region_prep.py` | `.venv-prep` | `plate build` |
| `scripts/build_labels.py` | `.venv` | `plate labels` |
| `scripts/bake_playa.py` | `.venv-prep` | `plate playa` |
| `scripts/pack_region.py` | `.venv` | `plate pack` |
| module `app.plates` | `.venv` | `plate install`, `plate check` |
| `scripts/order.py` | `.venv` | `order prepare` (task 9) |

**Entries:**

| Entry | Arguments | Runs | Kind |
|---|---|---|---|
| `plate_plan` | `tracks` | POST `/api/regions/plan` with one `files` part for each path | Read-only, HTTP |
| `plate_build` | `id`, `name`, `bbox` (four numbers, as strings), `epsg` (integer), `resolution` (optional) | `region_prep.py --id … --name … --bbox w s e n --epsg … [--resolution …]` | Tracked run |
| `plate_labels` | `id` | `scripts/build_labels.py <id>` | Tracked run |
| `plate_playa` | `id` | `scripts/bake_playa.py <id>`, failure text `FAILED` | Tracked run |
| `plate_pack` | `id`, `resync` | `scripts/pack_region.py <id> [--resync]` | In the call |
| `plate_install` | `file` | `-m app.plates install <file>` | In the call |
| `plate_check` | `poster` | `-m app.plates verify <poster>` | In the call, read-only |

**Rules:**

- Every `id` passes `ScriptRunner.isRegionID`. `name` must not start with `-`. Each `bbox` value and `resolution` must parse as a finite number (`resolution` may be `auto`), so none can be read as a flag. The tool checks the form only: the script and the engine own the ranges.
- The three guards of decision 11 read `regions/<id>` and `regions/<id>/sources.json` through `runtime.fileExists` and `runtime.readFile`. A `sources.json` that cannot be parsed is a refusal, not a pass.
- `plate labels` and `plate playa` refuse when `regions/<id>/sources.json` is missing: the plate is not built.
- `plate_install` needs an existing local file whose name ends with `.trailplate.zip`. It never passes `--replace` or `--root`.
- `plate_pack` exit 2 and `plate_install` exit 1 are `refused`, with the script's stderr in the body. `plate_check` exit 1 is data (`{"verified": false, "output": …}`), the same idea as `regions verify`. A traceback in stderr is an environment failure.
- Each tracked entry returns the run id and the hint "Run `tecopa runs show <id>`."

**Acceptance criteria:**

- [ ] Each entry has a fake test that checks the exact argv, the interpreter path (venv), and the working directory (the repo).
- [ ] `plate_build` for an existing `regions/<id>` is refused and starts nothing.
- [ ] `plate_labels` with a `labels.json` entry in `sources.json` is refused. The same for `plate_playa` and `playa.json`.
- [ ] No test can make the tool pass `--replace`, `--root`, `--out-root`, `--regions-root` or `--out`.
- [ ] A table test fails if `region_prep.py` or `scripts/bake_playa.py` is not in `.venv-prep` (invariant 13).

**Verify:** `swift test --package-path tools/tecopa`, 0 failures.

## Task 9: The `order` entries

**Goal:** `order prepare` and `order status`.

**Files:** new `Orders.swift`, `Catalog.swift`, `Commands.swift`, new `OrdersTests.swift`.

**Entries:**

- `order_prepare` (`folder`): a tracked run of `scripts/order.py prepare <folder>`. The folder must be an absolute path to an existing folder. The script refuses a folder inside the repo, and the tool passes that refusal through in the run's log.
- `order_status` (`folder`; read-only): reads `<folder>/work/state.json` and returns `{"prepared": true, "state": …, "report": <text of work/report.txt or null>}`. With no state file it returns `{"prepared": false}`. A state file that is not JSON is a `refused` failure that names the file.

**Rules:** `order_status` leaves out nothing from `state.json`. No command writes under the order folder except the script.

**Acceptance criteria:**

- [ ] `order_prepare` argv is `[<repo>/.venv/bin/python, scripts/order.py, prepare, <folder>]` with the repo as the working directory, and a relative folder is a usage failure.
- [ ] `order_status` covers the three cases: prepared, not prepared, not readable.

**Verify:** `swift test --package-path tools/tecopa`, 0 failures.

## Task 10: Phase 3 documents, MCP test, smoke block and proof

**Files:** `MCPServerTests.swift`, `smoke_test.sh`, `docs/architecture.md`, `docs/changing-things.md` ("Build a new plate" and "Run an order" each name the `tecopa` command beside the script), `docs/decisions.md`, the spec.

**Acceptance criteria:**

- [ ] The MCP test lists every phase 3 tool with the correct read-only annotation.
- [ ] The documents state decision 11 in plain words, and the list of tracked commands.
- [ ] **Proof:** `tecopa order prepare` on a new order folder outside the repo, with `tests/fixtures/sample.gpx` in `in/`, an `order.toml`, and `TECOPA_ORDERS_DIR` set to that folder's parent. The run ends in state `done`, `order status` shows the plate, and `tecopa regions verify` then gives the same findings as before the run. The run record, the state and the two verify outputs go into "What changed while it ran".

**Verify:** the fast Python suite, `swift test`, and the proof run.

---

# Phase 4: Studio

## Decisions for phase 4 (they refine the spec)

19. **The hook compares, it does not subscribe.** The store notifies only for `setField` and `applySnapshot`. The session, the target, the view and the crop change by direct assignment. So the hook builds its small state object each 2 seconds and posts only when the object changed.
20. **"The last API error" is the error toast.** The studio keeps no last error: each caller catches an `ApiError` and shows a toast. The hook watches the `#toast` element and reports each message of the kind `error`. It also reports uncaught errors and rejected promises. `api.js` does not change.
21. **A report never holds journey data.** The state object holds the session id, the target, the view, the region id, the output kind, the edition, and the two proof flags. It never holds tracks, markers, labels, filenames, the crop or the title.
22. **With the gate off, the first post gets a 405, not a 404.** The static mount answers a POST with 405. The rule is now: any first reply that is not 2xx stops the hook for that page load.
23. **The studio post is guarded against another web page.** A page on another site can send a simple POST to 127.0.0.1 with a local Host header. The route therefore needs `Content-Type: application/json`, which a cross-site page cannot send without a preflight that the engine does not answer. It also refuses an `Origin` header that is not local. Each string has a length limit, and the buffer holds at most 20 tabs and 50 errors.
24. **"Read-only" changes to "changes only the report buffer" in the code comments and the documents.** The historical entry in `docs/decisions.md` stays, and a new dated entry records the change.
25. **Spec check 3, read on 2026-10-10.** `tests/test_marketing_page.py` tests only the published Ghost pages. The studio's promise is that it goes online only to build a plate. The hook posts to its own origin only, and a new text test holds every studio module to that: no module names an outside host.

## Task 11: The studio report routes

**Goal:** The engine receives and returns studio reports, in memory only.

**Files:** `app/debug.py` (a `StudioReports` class and two routes), `app/main.py` (the comment above the include), `tests/test_debug.py`.

**Shapes:**

- `POST /api/debug/studio`, JSON body: `{"tab": "<8 to 32 of a-z0-9>", "state": {…} or absent, "errors": [{"kind", "message", "source", "line", "stack"}] or absent}`. Answer: 204.
- `GET /api/debug/studio`: `{"tabs": [{"tab", "received", "state"}], "errors": [{"tab", "received", "kind", "message", "source", "line", "stack"}]}`, each list newest first. `received` is the engine's clock.
- `state` keeps only these keys: `session`, `target`, `view`, `region`, `output`, `edition`, `has_spec`, `proof_stale`. Any other key is dropped.
- `kind` is one of `error`, `rejection`, `toast`. Limits: `message` 2,000 characters, `stack` 8,000, `source` 300. A longer string is cut. At most 20 errors in one post.

**Rules:**

- A body over 64 KB is 413, checked on the bytes read and not only on `Content-Length`.
- A content type that is not `application/json` is 415. An `Origin` header that is not `http://127.0.0.1[:port]`, `http://localhost[:port]` or `http://[::1][:port]` is 403. No `Origin` header passes.
- A body that is not an object, or a bad `tab`, is 422.
- The buffer keeps the latest state for each of at most 20 tabs (the oldest tab is dropped) and the last 50 errors. A lock guards it.
- Nothing is written to disk, and nothing is logged except one `event=debug.studio` line with the tab id and the counts.
- The router still never imports `app.main`.

**Acceptance criteria:**

- [ ] One test for each rule above: 204, 413, 415, 403 for a foreign Origin, 422, the key filter, each length cut, the 20-tab limit, the 50-error limit, newest first.
- [ ] The foreign-Host test covers both new routes, POST included.
- [ ] A post does not change a session, a job or a cache.
- [ ] Gate off: a POST to the live app is not 2xx.

**Verify:** `.venv/bin/python -m pytest tests/test_debug.py -q`, then the fast suite.

## Task 12: The studio hook, `app/static/debug.js`

**Goal:** The studio reports its state and its errors to the engine, and can never break.

**Files:** new `app/static/debug.js`, `app/static/app.js` (one import and one `init` call), `tests/test_static_registry.py`.

**Behavior:**

- `init()` makes a random tab id, adds the `error` and `unhandledrejection` listeners, starts a `MutationObserver` on `#toast`, and starts a 2-second timer.
- Each tick: build the state object from `store.state`. If it differs from the last one sent, or errors wait, send one POST with `Content-Type: application/json` to `/api/debug/studio`.
- The first reply that is not 2xx, or a failed fetch, stops the hook for the page load: the timer, the observer and the listeners are removed.
- Every path is inside `try`/`catch`. The hook never throws, never shows a toast, and writes nothing to the console.
- At most 20 errors wait. More are dropped, oldest first.
- The module imports only `./store.js`.

**Acceptance criteria:**

- [ ] `node --check app/static/debug.js` and `node --check app/static/app.js` pass.
- [ ] Text tests in `tests/test_static_registry.py`: `app.js` imports `./debug.js`; `debug.js` holds exactly one `fetch(` and its target is `/api/debug/studio`; `debug.js` names none of `tracks`, `hotspots`, `files`, `crop`, `title`; no file under `app/static/*.js` holds `http://` or `https://`.
- [ ] Browser drive with the gate on: load the studio, wait 3 seconds, and `GET /api/debug/studio` shows one tab with `target` and `view`. Throw an error in the page, wait 3 seconds, and the error is in the list.
- [ ] Browser drive with the gate off (a development engine on another port): the page loads and works, and one failed POST is the only trace.

**Verify:** the two `node --check` runs, `.venv/bin/python -m pytest tests/test_static_registry.py -q`, the fast suite, and the browser drive.

## Task 13: `studio state` and `studio errors`

**Goal:** The two entries that read the studio reports.

**Files:** new `Studio.swift`, `Catalog.swift`, `Commands.swift`, new `StudioTests.swift`, `MCPServerTests.swift`.

**Entries:** `studio_state` returns `{"tabs": …}` and `studio_errors` returns `{"errors": …}`, both from `client.debug("/studio")`. Both are read-only. `studio_errors` takes `tab` (optional) and keeps only that tab's errors. With no report yet, each returns an empty list.

**Acceptance criteria:**

- [ ] Fake tests for both entries, the `tab` filter, and the gate-off message.
- [ ] The MCP test lists both tools as read-only, and the pinned tool count is correct.

**Verify:** `swift test --package-path tools/tecopa`, 0 failures.

## Task 14: Phase 4 documents and proof, then the whole branch

**Files:** `docs/architecture.md` (the module map row for `app/static/debug.js`, "22 ES modules" becomes 23, the debug rows, the gated-routes bullet), `docs/changing-things.md`, `docs/decisions.md` (one dated entry for phases 2 to 4), `docs/README.md` (a row for this plan, the spec row's status), the spec (status, the command table, "Changes made while phases 2 to 4 were built"), `tools/tecopa/smoke_test.sh`.

**Acceptance criteria:**

- [ ] `tests/test_docs.py` passes.
- [ ] **Phase 4 proof:** an error thrown in the studio page shows in `tecopa studio errors`. The output goes into "What changed while it ran".
- [ ] The full Python suite passes: `.venv/bin/python -m pytest -n auto -q`.
- [ ] `swift test --package-path tools/tecopa` passes.
- [ ] `tools/tecopa/build.sh --install` is run one time, then `tecopa doctor`, then the access check in the desktop app's launch form.
- [ ] One independent review of the whole branch finds no open item.

**Verify:** each command above, with its output recorded.

---

## What changed while it ran

(Each task's result goes here.)
