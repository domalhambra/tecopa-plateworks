# The `tecopa` Tool, Phase 1 (Diagnose) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One compiled Swift binary, `tecopa`, reads the engine's status, jobs, sessions, caches and log, starts and stops the launcher's engine, and gives the same commands to Claude as MCP tools.

**Architecture:** A SwiftPM package in `tools/tecopa/`. The library `TecopaKit` holds every operation as one entry in a catalog. The executable `tecopa` is a thin ArgumentParser shell over that catalog, and `tecopa mcp` serves the same catalog over stdio. The Python engine gains a read-only router, `app/debug.py`, that exists only under `TECOPA_DEBUG=1`.

**Tech Stack:** Swift 6.4 (language mode 5), SwiftPM, swift-argument-parser 1.8.2, the MCP Swift SDK 0.12.1, XCTest. Python 3.14, FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md`. This plan is phase 1 of 4.

**Build starts:** after the 2026-10-21 Now review. Do not run Task 1 before Dom says the build is open.

---

## Before you start

- Read `CLAUDE.md` (invariants 3, 8, 12, 13) and `docs/architecture.md`.
- Two venvs. `.venv` runs the app and the tests. Never install anything new into either venv for this plan. Phase 1 adds no Python dependency.
- Fast suite: `.venv/bin/python -m pytest -n auto -m "not slow" -q`. Full suite before any push to `main`: `.venv/bin/python -m pytest -n auto -q`. Compare the failure set, not the totals.
- Swift commands run from the repo root with `--package-path tools/tecopa`.
- The Swift code has no CI. Run `swift test --package-path tools/tecopa` before each Swift commit.
- Commit to `main` only when green. Present-tense commit messages that say why.

## Decisions made while planning (they refine the spec)

1. **This plan covers phase 1 only.** Phases 2, 3 and 4 each get a plan after phase 1 ships, the same as the order pipeline's sub-projects. Their code depends on shapes that phase 1 fixes.
2. **An MCP tool name uses an underscore.** The CLI command `engine status` is the MCP tool `engine_status`. A tool name cannot hold a space.
3. **Every result has one envelope.** Success is `{"ok": true, "data": …}`. Failure is `{"ok": false, "error": {"kind", "message", "hint", "status", "body"}}`. `--json` prints it and an MCP tool returns it.
4. **The script table is an allowlist.** A script that has no row does not run. Phase 1 has one row, `scripts/verify_regions.py`. The spec sentence "every other script runs in `.venv`" was incomplete: `scripts/dem_coverage.py` also needs `.venv-prep`. Phase 3 adds its rows by name.
5. **`ThreadJobQueue` records two more facts.** Each job gets a `started` time, and the queue keeps `max_concurrency`. The spec's jobs route needs both.
6. **Without `?full=1`, the session detail replaces the spec's `tracks` list with its length.** `spec_to_json` puts track geometry inside the spec, so the spec alone would leak it.
7. **`logs --since` takes a duration**: `90s`, `30m`, `2h`, `1d`. A log line with no timestamp takes the timestamp of the nearest stamped line above it. `--grep` is a case-insensitive substring, not a regular expression.
8. **`doctor` exits 4 when a check fails and 0 when checks only warn.** A stopped engine is a warning, because stopped is a normal state.
9. **A usage error from the argument parser exits 64**, the parser's standard code. Exit 2 is for a usage fault that `tecopa` itself finds. Task 14 corrects the spec's table.
10. **The repo path is baked with a compile flag.** `build.sh` writes a gitignored `Baked.generated.swift` and builds with `-DTECOPA_BAKED`. A plain `swift build` or `swift test` compiles the committed `nil` default.
11. **`engine start`, `stop` and `restart` refuse any port except 8848.** They control the launcher, and the launcher owns only that port.
12. **The studio routes wait for phase 4.** Phase 1 builds the gate and the engine, jobs, sessions and caches routes.
13. **Licenses, checked by reading on 2026-10-09.** swift-argument-parser is Apache-2.0. The MCP Swift SDK is Apache-2.0 for new code and MIT for older code. Both fit AGPL-3.0-or-later. Task 1 still proves that the SDK builds.

## Found while planning

The installed launcher is broken. `/Applications/Tecopa Plateworks.app` has the baked path `/Users/dom/Documents/Claude/Projects/Badwater OS/Tecopa Plateworks`, which no longer exists. Its last log line is from 2026-09-02. Task 4 rebuilds and reinstalls it. Task 11 gives `doctor` a check for this fault.

## File map

| File | Change | Responsibility |
|---|---|---|
| `app/jobs.py` | modify | `started`, `max_concurrency`, `snapshot()` |
| `app/store.py` | modify | `ids()` on both stores |
| `app/session.py` | modify | `ids()`, `kind()` |
| `app/debug.py` | create | The gate and the read-only router |
| `app/main.py` | modify | Include the router when the gate is on |
| `tests/conftest.py` | modify | Remove `TECOPA_DEBUG` from the test environment |
| `tests/test_server_foundation.py` | modify | Tests for the queue and store additions |
| `tests/test_debug.py` | create | Tests for the gate and each route |
| `scripts/macos/TecopaPlateworksLauncher.swift` | modify | Set `TECOPA_DEBUG=1` for the engine |
| `tools/tecopa/Package.swift` | create | The package manifest |
| `tools/tecopa/build.sh` | create | Release build, baked path, `--install` |
| `tools/tecopa/smoke_test.sh` | create | The phase proof against a live engine |
| `tools/tecopa/Sources/TecopaKit/JSONValue.swift` | create | Any JSON value, parse and print |
| `tools/tecopa/Sources/TecopaKit/TecopaFailure.swift` | create | The failure type, exit codes, the envelope |
| `tools/tecopa/Sources/TecopaKit/Baked.swift` | create | The `nil` default for the baked path |
| `tools/tecopa/Sources/TecopaKit/RepoLocator.swift` | create | Flag, then variable, then baked path |
| `tools/tecopa/Sources/TecopaKit/Seams.swift` | create | `HTTPFetching`, `ProcessRunning` and their real types |
| `tools/tecopa/Sources/TecopaKit/Runtime.swift` | create | What one call needs: port, repo, the seams |
| `tools/tecopa/Sources/TecopaKit/EngineClient.swift` | create | HTTP to the engine, the gate-off message |
| `tools/tecopa/Sources/TecopaKit/Catalog.swift` | create | The entry type, the list, the one call path |
| `tools/tecopa/Sources/TecopaKit/EngineEntries.swift` | create | `engine_status`, `regions`, `jobs`, `sessions`, `caches` |
| `tools/tecopa/Sources/TecopaKit/LogReader.swift` | create | The log tail, `--grep`, `--since`, the `logs` entry |
| `tools/tecopa/Sources/TecopaKit/Launcher.swift` | create | Open and quit the launcher, the three control entries |
| `tools/tecopa/Sources/TecopaKit/ScriptRunner.swift` | create | The script table, the `regions_verify` entry |
| `tools/tecopa/Sources/TecopaKit/Doctor.swift` | create | The checks and the `doctor` entry |
| `tools/tecopa/Sources/tecopa/Tecopa.swift` | create | The root command |
| `tools/tecopa/Sources/tecopa/Shared.swift` | create | Global options and `execute` |
| `tools/tecopa/Sources/tecopa/Commands.swift` | create | One thin struct per command |
| `tools/tecopa/Sources/tecopa/MCPServer.swift` | create | The catalog over stdio |
| `tools/tecopa/Tests/TecopaKitTests/*.swift` | create | One test file per task, listed per task |
| `.gitignore` | modify | The build folder and the generated file |
| docs | modify | Task 14 |

---

### Task 1: Prove the Swift stack before any repo code

**Goal:** Prove that swift-argument-parser and the MCP Swift SDK build with Swift 6.4 on this Mac, that the SDK names this plan uses exist, and that a binary started from Claude Code can read the repo under `~/Documents`.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Create: `$TMPDIR/tecopa-probe/Package.swift` (throwaway, not committed)
- Create: `$TMPDIR/tecopa-probe/Sources/probe/Probe.swift` (throwaway)
- Create: `$TMPDIR/tecopa-probe/Tests/probeTests/ProbeTests.swift` (throwaway)

**Acceptance Criteria:**
- [ ] `swift build` of the probe exits 0 and prints no error.
- [ ] `swift test` of the probe reports 1 test passed, which proves XCTest is available.
- [ ] The probe's reply to `tools/list` contains `"name":"ping"` and `"readOnlyHint":true`.
- [ ] The probe's reply to `tools/call` contains `pong` and the first 10 characters of the repo's `README.md`.
- [ ] The result (PASS or FAIL for each line above, with the output) is written under "Task 1 result" at the end of this plan.

**Verify:** the two `printf … | probe` commands in Step 4 → the two expected lines.

**Steps:**

- [ ] **Step 1: Ask Dom before the download.** `swift build` fetches two packages from GitHub: `apple/swift-argument-parser` and `modelcontextprotocol/swift-sdk`. State the two names and wait for his yes.

- [ ] **Step 2: Write the probe package**

`$TMPDIR/tecopa-probe/Package.swift`:

```swift
// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "probe",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(url: "https://github.com/apple/swift-argument-parser.git", from: "1.8.2"),
        .package(url: "https://github.com/modelcontextprotocol/swift-sdk.git", from: "0.12.1"),
    ],
    targets: [
        .executableTarget(
            name: "probe",
            dependencies: [
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
                .product(name: "MCP", package: "swift-sdk"),
            ]),
        .testTarget(name: "probeTests", dependencies: ["probe"]),
    ],
    swiftLanguageModes: [.v5]
)
```

`$TMPDIR/tecopa-probe/Sources/probe/Probe.swift`:

```swift
import ArgumentParser
import Foundation
import MCP

@main
struct Probe: AsyncParsableCommand {
    @Option var repo: String

    func run() async throws {
        let repoPath = repo
        let server = Server(
            name: "probe", version: "0.0.1",
            capabilities: .init(tools: .init(listChanged: false)))

        await server.withMethodHandler(ListTools.self) { _ in
            .init(tools: [
                Tool(
                    name: "ping",
                    description: "Returns pong and the start of README.md",
                    inputSchema: .object([
                        "type": .string("object"),
                        "properties": .object([
                            "word": .object(["type": .string("string")])
                        ]),
                    ]),
                    annotations: .init(readOnlyHint: true))
            ])
        }

        await server.withMethodHandler(CallTool.self) { params in
            let word = params.arguments?["word"]?.stringValue ?? "none"
            let handle = FileHandle(forReadingAtPath: repoPath + "/README.md")
            let head = (try? handle?.read(upToCount: 10)).flatMap { $0 } ?? Data()
            let text = "pong \(word) \(String(decoding: head, as: UTF8.self))"
            return .init(content: [.text(text)], isError: false)
        }

        try await server.start(transport: StdioTransport())
        await server.waitUntilCompleted()
    }
}
```

`$TMPDIR/tecopa-probe/Tests/probeTests/ProbeTests.swift`:

```swift
import XCTest

final class ProbeTests: XCTestCase {
    func testXCTestRuns() { XCTAssertEqual(1 + 1, 2) }
}
```

- [ ] **Step 3: Build and test the probe**

Run: `swift build --package-path "$TMPDIR/tecopa-probe" && swift test --package-path "$TMPDIR/tecopa-probe"`
Expected: `Build complete!` and `Executed 1 test, with 0 failures`.

If the build fails on a name (`annotations:`, `readOnlyHint`, `waitUntilCompleted`, `params.arguments`, `stringValue`), open the SDK source under `$TMPDIR/tecopa-probe/.build/checkouts/swift-sdk/Sources/MCP/` and find the correct name. Record the correct name under "Task 1 result". Task 12 must then use it.

If the SDK cannot build at all, stop. Report to Dom. The spec's fallback is a hand-written stdio JSON-RPC layer, and that needs a revised Task 12.

- [ ] **Step 4: Drive the probe over stdio**

```bash
REPO="$(git rev-parse --show-toplevel)"
PROBE="$TMPDIR/tecopa-probe/.build/debug/probe"
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}'
READY='{"jsonrpc":"2.0","method":"notifications/initialized"}'
( printf '%s\n' "$INIT" "$READY" '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'; sleep 2 ) | "$PROBE" --repo "$REPO"
( printf '%s\n' "$INIT" "$READY" '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ping","arguments":{"word":"hello"}}}'; sleep 2 ) | "$PROBE" --repo "$REPO"
```

Expected, first command: one line with `"id":2` that contains `"name":"ping"` and `"readOnlyHint":true`.
Expected, second command: one line with `"id":3` that contains `pong hello # Tecopa P`.

The second line proves the file grant from Claude Code. If the text after `pong hello` is empty, macOS refused the read. Record that as FAIL and report to Dom before Task 5.

- [ ] **Step 5: Record the result.** Fill "Task 1 result" at the end of this plan. Commit the plan change.

```bash
git add docs/superpowers/plans/2026-10-09-tecopa-tool-phase-1-diagnose.md
git commit -m "plan: the Swift stack probe passes, so the tecopa package can start"
```

---

### Task 2: The queue and the stores can list what they hold

**Goal:** `ThreadJobQueue` returns a copy of every job with its times, and both stores return their session ids, so a debug route can read them without a private attribute.

**Files:**
- Modify: `app/jobs.py`
- Modify: `app/store.py`
- Modify: `app/session.py`
- Test: `tests/test_server_foundation.py`

**Acceptance Criteria:**
- [ ] `ThreadJobQueue.snapshot()` returns one row per job, newest first, with `jid`, `state`, `error`, `progress`, `created`, `started`, `finished`, and no `result`.
- [ ] A change to a returned row does not change the queue.
- [ ] `ThreadJobQueue(max_concurrency=0).max_concurrency == 1`.
- [ ] `MemoryStore.ids()` and `SqliteStore.ids()` return the ids of every created session.
- [ ] `session.ids()` and `session.kind()` exist.
- [ ] No existing test changes its result.

**Verify:** `.venv/bin/python -m pytest tests/test_server_foundation.py -q` → all pass.

**Steps:**

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_server_foundation.py`:

```python
def _wait_done(q, jid, seconds=5.0):
    deadline = time.time() + seconds
    while q.status(jid)["state"] not in ("done", "error") and time.time() < deadline:
        time.sleep(0.01)


def test_job_queue_snapshot_lists_every_job_without_results():
    # the debug route reads this; a result can be a large blob key or any object,
    # so a snapshot never carries it
    q = jobs.ThreadJobQueue()
    jid = q.submit(lambda: "big-result")
    _wait_done(q, jid)
    rows = q.snapshot()
    assert [r["jid"] for r in rows] == [jid]
    row = rows[0]
    assert row["state"] == "done" and row["error"] is None
    assert "result" not in row
    assert row["created"] <= row["started"] <= row["finished"]


def test_job_queue_snapshot_is_newest_first_and_a_copy():
    q = jobs.ThreadJobQueue()
    first = q.submit(lambda: 1)
    time.sleep(0.01)
    second = q.submit(lambda: 2)
    _wait_done(q, first)
    _wait_done(q, second)
    rows = q.snapshot()
    assert [r["jid"] for r in rows] == [second, first]
    rows[0]["state"] = "MUTATED"
    assert q.snapshot()[0]["state"] == "done"


def test_job_queue_records_its_width():
    assert jobs.ThreadJobQueue(max_concurrency=3).max_concurrency == 3
    assert jobs.ThreadJobQueue(max_concurrency=0).max_concurrency == 1


def test_stores_list_their_session_ids(tmp_path):
    for s in (store.MemoryStore(), store.SqliteStore(str(tmp_path / "ids.db"))):
        assert s.ids() == []
        a = s.create(_session())
        b = s.create(_session())
        assert sorted(s.ids()) == sorted([a, b])


def test_session_module_lists_ids_and_names_its_store():
    from app import session
    sid = session.create({"region_id": "r", "hotspots": [], "tracks": [], "spec": None})
    assert sid in session.ids()
    assert session.kind() in ("MemoryStore", "SqliteStore")
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `.venv/bin/python -m pytest tests/test_server_foundation.py -q -k "snapshot or width or ids or names_its_store"`
Expected: 5 failed, with `AttributeError` for `snapshot`, `max_concurrency`, `ids` and `kind`.

- [ ] **Step 3: Change `app/jobs.py`.** Three edits.

In `__init__`, replace the semaphore line:

```python
        self.max_concurrency = max(1, max_concurrency)
        self._slots = threading.Semaphore(self.max_concurrency)
```

In `submit`, give each new record a `started` key:

```python
            self._jobs[jid] = {"state": "queued", "result": None, "error": None,
                               "created": time.time(), "started": None,
                               "finished": None, "progress": None}
```

In `run`, stamp the start:

```python
                with self._lock:
                    self._jobs[jid]["state"] = "running"
                    self._jobs[jid]["started"] = t0
```

Add this method after `status`:

```python
    def snapshot(self) -> list[dict]:
        """Every job record, newest first, for the debug route. A copy, taken under
        the lock. `result` is left out: it can be a large blob key or any object, and
        a debug reader needs the state, not the payload."""
        with self._lock:
            rows = [{"jid": j, "state": r["state"], "error": r["error"],
                     "progress": r["progress"], "created": r["created"],
                     "started": r.get("started"), "finished": r["finished"]}
                    for j, r in self._jobs.items()]
        rows.sort(key=lambda r: r["created"], reverse=True)
        return rows
```

- [ ] **Step 4: Change `app/store.py`.** Add to `MemoryStore`, after `has`:

```python
    def ids(self) -> list[str]:
        with self._lock:
            return list(self._d)
```

Add to `SqliteStore`, after `has`:

```python
    def ids(self) -> list[str]:
        with self._conn() as c:
            return [row[0] for row in c.execute("SELECT id FROM sessions")]
```

- [ ] **Step 5: Change `app/session.py`.** Append:

```python
def ids() -> list[str]:
    return _STORE.ids()

def kind() -> str:
    """The store's class name, for the debug route: MemoryStore or SqliteStore."""
    return type(_STORE).__name__
```

- [ ] **Step 6: Run the file, then the fast suite**

Run: `.venv/bin/python -m pytest tests/test_server_foundation.py -q`
Expected: all pass.
Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`
Expected: the same failure set as `main` before this task.

- [ ] **Step 7: Commit**

```bash
git add app/jobs.py app/store.py app/session.py tests/test_server_foundation.py
git commit -m "jobs, store: a queue lists its jobs and a store lists its sessions, so a debug route can read them"
```

---

### Task 3: The debug router and its gate

**Goal:** `app/debug.py` serves the engine, jobs, sessions and caches routes under `/api/debug/`, and `app/main.py` includes them only when `TECOPA_DEBUG=1`.

**Files:**
- Create: `app/debug.py`
- Modify: `app/main.py` (the import line near line 18, and after `app = FastAPI(...)` near line 112)
- Modify: `tests/conftest.py` (near line 20, before the store setup)
- Test: `tests/test_debug.py`

**Acceptance Criteria:**
- [ ] `debug.enabled` is true only for the exact value `"1"`.
- [ ] With the gate off, `GET /api/debug/engine` on the live app returns 404.
- [ ] `GET /api/debug/engine` returns `engine`, `engine_version`, `pid`, `uptime_s`, `python`, `env`, `store`, `queues`.
- [ ] `GET /api/debug/jobs` returns each job with its `queue` name and no `result`.
- [ ] `GET /api/debug/sessions` returns `sid`, `region_id`, `tracks`, `hotspots`, `has_spec` for each session.
- [ ] `GET /api/debug/sessions/{sid}` returns no coordinates. With `?full=1` it returns them. An unknown id returns 404 with detail `Unknown session`.
- [ ] `GET /api/debug/caches` returns the `stats()` of each cache.

**Verify:** `.venv/bin/python -m pytest tests/test_debug.py -q` → 9 passed.

**Steps:**

- [ ] **Step 1: Keep the gate off in the suite.** In `tests/conftest.py`, add these lines directly above the comment that starts `# Isolate the app's writable stores`:

```python
# The debug routes are gated on TECOPA_DEBUG=1 and tests/test_debug.py asserts that the
# live app has none of them. A shell that exports the variable would otherwise flip
# that test, so the suite always imports app.main with the gate off.
os.environ.pop("TECOPA_DEBUG", None)
```

- [ ] **Step 2: Write the failing tests.** Create `tests/test_debug.py`:

```python
# tests/test_debug.py
# The read-only debug routes behind TECOPA_DEBUG=1 (the `tecopa` tool reads them).
# The router is built on a small app of its own here, so the gate-on shape is tested
# without re-importing app.main. The gate-off shape is tested on the live app.
import time
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import basecache, debug, jobs, session
from app.ingest import Track
from app.spec import CompositionSpec


def _client():
    q = jobs.ThreadJobQueue(max_concurrency=2)
    app = FastAPI()
    app.include_router(debug.build_router(
        queues={"render": q}, caches={"base": basecache.BaseCache(1000)},
        started=time.time() - 5))
    return TestClient(app), q


def _track():
    return Track("t-0", np.array([[1100.0, 2100.0], [3900.0, 5900.0]]), "2024-06-01")


def _make_session(with_spec=False):
    t = _track()
    spec = None
    if with_spec:
        spec = CompositionSpec(region_id="lassen_ca", crs="EPSG:32610",
                               crop=(1000.0, 2000.0, 4000.0, 6000.0),
                               print_w_in=9, print_h_in=12, native_resolution_m=10,
                               tracks=[t.coords], hotspots=[], seed=7,
                               title_text="LASSEN")
    return session.create({"region_id": "lassen_ca", "tracks": [t],
                           "hotspots": [{"x": 1.0, "y": 2.0, "weight": 1, "label": "Camp"}],
                           "spec": spec})


def test_gate_reads_only_the_exact_value():
    assert debug.enabled({"TECOPA_DEBUG": "1"})
    assert not debug.enabled({})
    assert not debug.enabled({"TECOPA_DEBUG": "0"})
    assert not debug.enabled({"TECOPA_DEBUG": "true"})


def test_gate_off_means_the_live_app_has_no_debug_routes():
    # conftest removes TECOPA_DEBUG, so app.main was imported with the gate off
    from app.main import app
    assert TestClient(app).get("/api/debug/engine").status_code == 404


def test_engine_reports_identity_and_queue_widths():
    c, _ = _client()
    body = c.get("/api/debug/engine").json()
    assert body["engine"] == "tecopa-plateworks"
    assert body["engine_version"]
    assert body["queues"] == {"render": 2}
    assert body["uptime_s"] >= 5
    assert body["pid"] > 0
    assert body["store"] in ("MemoryStore", "SqliteStore")
    assert all(k.startswith("TECOPA_") for k in body["env"])


def test_jobs_lists_each_queue_without_results():
    c, q = _client()
    jid = q.submit(lambda: "secret-result")
    deadline = time.time() + 5
    while q.status(jid)["state"] != "done" and time.time() < deadline:
        time.sleep(0.01)
    rows = c.get("/api/debug/jobs").json()["jobs"]
    assert len(rows) == 1
    assert rows[0]["queue"] == "render" and rows[0]["jid"] == jid
    assert rows[0]["state"] == "done" and "result" not in rows[0]


def test_sessions_lists_a_summary_row():
    c, _ = _client()
    sid = _make_session()
    rows = {r["sid"]: r for r in c.get("/api/debug/sessions").json()["sessions"]}
    assert rows[sid] == {"sid": sid, "region_id": "lassen_ca", "tracks": 1,
                         "hotspots": 1, "has_spec": False}


def test_session_detail_holds_no_geometry_unless_asked():
    c, _ = _client()
    sid = _make_session(with_spec=True)
    body = c.get(f"/api/debug/sessions/{sid}").json()
    assert body["tracks"] == [{"track_id": "t-0", "points": 2, "day": "2024-06-01"}]
    assert body["spec"]["title_text"] == "LASSEN"
    assert body["spec"]["tracks"] == 1          # a count, never the coordinates
    assert "coords" not in str(body)


def test_session_detail_full_returns_the_geometry():
    c, _ = _client()
    sid = _make_session(with_spec=True)
    full = c.get(f"/api/debug/sessions/{sid}?full=1").json()
    assert full["tracks"][0]["coords"] == [[1100.0, 2100.0], [3900.0, 5900.0]]
    assert full["spec"]["tracks"] == [[[1100.0, 2100.0], [3900.0, 5900.0]]]


def test_unknown_session_is_a_404_that_names_the_cause():
    c, _ = _client()
    r = c.get("/api/debug/sessions/nope")
    assert r.status_code == 404 and r.json()["detail"] == "Unknown session"


def test_caches_reports_each_cache():
    c, _ = _client()
    body = c.get("/api/debug/caches").json()
    assert body == {"base": {"entries": 0, "bytes": 0, "max_bytes": 1000,
                             "hits": 0, "misses": 0}}
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `.venv/bin/python -m pytest tests/test_debug.py -q`
Expected: a collection error, `ImportError: cannot import name 'debug' from 'app'`.

- [ ] **Step 4: Create `app/debug.py`**

```python
# app/debug.py
"""Read-only debug routes for the `tecopa` tool, behind TECOPA_DEBUG=1.

The studio is the only client the engine was built for, and it holds its own state.
A diagnosis from outside the browser needs to see what the engine holds: which jobs
are queued or failed, which sessions exist, what the caches are doing. These routes
show that and change nothing.

The gate is off by default. A route that lists sessions and tracks must not exist on
a host that did not ask for it, so with the gate off app.main never includes this
router and every /api/debug path is a plain 404. The macOS launcher sets the gate.

Design: docs/superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md."""
from __future__ import annotations
import os
import platform
import time
from fastapi import APIRouter, HTTPException
from app import provenance, serialize, session


def enabled(env=None) -> bool:
    """True only for the exact value "1". Anything else, the routes do not exist."""
    env = os.environ if env is None else env
    return env.get("TECOPA_DEBUG", "") == "1"


def _session_row(sid: str, data: dict) -> dict:
    return {"sid": sid, "region_id": data.get("region_id"),
            "tracks": len(data.get("tracks") or []),
            "hotspots": len(data.get("hotspots") or []),
            "has_spec": data.get("spec") is not None}


def _session_detail(sid: str, data: dict, full: bool) -> dict:
    spec = serialize.spec_to_json(data["spec"]) if data.get("spec") else None
    if full:
        tracks = [serialize.track_to_json(t) for t in data.get("tracks") or []]
    else:
        tracks = [{"track_id": t.track_id, "points": int(len(t.coords)), "day": t.day}
                  for t in data.get("tracks") or []]
        if spec is not None:
            # spec_to_json carries the track geometry too; without full=1 a reader
            # gets the count and never the coordinates
            spec["tracks"] = len(spec.get("tracks") or [])
    return {"sid": sid, "region_id": data.get("region_id"), "spec": spec,
            "tracks": tracks, "hotspots": data.get("hotspots") or [],
            "edition": data.get("edition", 1), "lineage": data.get("lineage", [])}


def build_router(*, queues: dict, caches: dict, started: float) -> APIRouter:
    """`queues` maps a name to a ThreadJobQueue, `caches` a name to a BaseCache,
    `started` is the engine's start time. Passed in, not imported, so this module
    never imports app.main."""
    r = APIRouter(prefix="/api/debug")

    @r.get("/engine")
    async def engine():
        return {"engine": provenance.ENGINE,
                "engine_version": provenance.ENGINE_VERSION,
                "pid": os.getpid(),
                "uptime_s": round(time.time() - started, 1),
                "python": platform.python_version(),
                "env": {k: v for k, v in sorted(os.environ.items())
                        if k.startswith("TECOPA_")},
                "store": session.kind(),
                "queues": {name: q.max_concurrency for name, q in queues.items()}}

    @r.get("/jobs")
    async def list_jobs():
        rows = [{"queue": name, **row}
                for name, q in queues.items() for row in q.snapshot()]
        rows.sort(key=lambda row: row["created"], reverse=True)
        return {"jobs": rows}

    @r.get("/sessions")
    async def list_sessions():
        rows = []
        for sid in session.ids():
            try:
                rows.append(_session_row(sid, session.get(sid)))
            except KeyError:        # dropped between ids() and get()
                continue
        return {"sessions": rows}

    @r.get("/sessions/{sid}")
    async def session_detail(sid: str, full: int = 0):
        if not session.has(sid):
            raise HTTPException(404, "Unknown session")
        return _session_detail(sid, session.get(sid), bool(full))

    @r.get("/caches")
    async def list_caches():
        return {name: c.stats() for name, c in caches.items()}

    return r
```

- [ ] **Step 5: Include the router in `app/main.py`.** Change the import line `from app import basecache` to:

```python
from app import basecache, debug
```

Directly after the line `app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`, add:

```python
# Debug routes for the `tecopa` tool: read-only, and present only under
# TECOPA_DEBUG=1, which the macOS launcher sets. With the gate off this router is
# never included, so every /api/debug path falls through to the static mount's 404.
STARTED = time.time()
if debug.enabled():
    app.include_router(debug.build_router(
        queues={"render": QUEUE, "build": BUILD_QUEUE, "proof": PROOF_QUEUE},
        caches={"base": BASE_CACHE, "ink": INK_CACHE},
        started=STARTED))
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_debug.py -q`
Expected: 9 passed.

- [ ] **Step 7: Check the gate by hand, on and off.** Port 8011 is free of the launcher and of the dev default.

```bash
TECOPA_DEBUG=1 .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8011 &
sleep 6
curl -s http://127.0.0.1:8011/api/debug/engine | head -c 200; echo
curl -s http://127.0.0.1:8011/api/debug/jobs; echo
kill %1
```

Expected: a JSON object that starts `{"engine":"tecopa-plateworks"`, then `{"jobs":[]}`.

- [ ] **Step 8: Run the fast suite, then commit**

Run: `.venv/bin/python -m pytest -n auto -m "not slow" -q`
Expected: the same failure set as before this task.

```bash
git add app/debug.py app/main.py tests/conftest.py tests/test_debug.py
git commit -m "debug: read-only routes for jobs, sessions and caches behind TECOPA_DEBUG, so a fault is visible outside the browser"
```

---

### Task 4: The launcher sets the gate

**Goal:** The launcher starts the engine with `TECOPA_DEBUG=1`, and the installed app runs from the repo's current path.

**Files:**
- Modify: `scripts/macos/TecopaPlateworksLauncher.swift` (step 4 of `boot()`, after `p.currentDirectoryURL`)

**Acceptance Criteria:**
- [ ] `/Applications/Tecopa Plateworks.app/Contents/Info.plist` holds the repo's current path under `TecopaRepoPath`.
- [ ] With the launcher running, `curl -s http://127.0.0.1:8848/api/debug/engine` returns JSON whose `env` holds `"TECOPA_DEBUG":"1"`.
- [ ] After the quit, port 8848 no longer answers.

**Verify:** the three commands in Step 3 → the three expected outputs.

**Steps:**

- [ ] **Step 1: Set the variable.** In `boot()`, directly after `p.currentDirectoryURL = URL(fileURLWithPath: repo)`, add:

```swift
        // The `tecopa` tool reads /api/debug/*. Those routes exist only under this
        // gate, and only this launcher sets it: a hand-started engine has none.
        var engineEnv = ProcessInfo.processInfo.environment
        engineEnv["TECOPA_DEBUG"] = "1"
        p.environment = engineEnv
```

- [ ] **Step 2: Ask Dom, then rebuild and reinstall.** `build_app.sh --install` deletes `/Applications/Tecopa Plateworks.app` and copies the new build there. Say so and wait for his yes. Then:

Run: `scripts/macos/build_app.sh --install`
Expected: `Built: …/dist/Tecopa Plateworks.app` and `Installed: /Applications/Tecopa Plateworks.app`.

- [ ] **Step 3: Check the installed app**

```bash
/usr/libexec/PlistBuddy -c "Print :TecopaRepoPath" "/Applications/Tecopa Plateworks.app/Contents/Info.plist"
open -g "/Applications/Tecopa Plateworks.app"; sleep 12
curl -s http://127.0.0.1:8848/api/debug/engine | grep -o '"TECOPA_DEBUG":"1"'
osascript -e 'quit app "Tecopa Plateworks"'; sleep 6
curl -s -o /dev/null -w "%{http_code}\n" --max-time 1 http://127.0.0.1:8848/readyz
```

Expected: the repo's path from `git rev-parse --show-toplevel`, then `"TECOPA_DEBUG":"1"`, then `000`.

The first launch can show two macOS prompts: Documents access for the app, and Automation for the quit. Dom clicks Allow. If the launcher shows an alert, read `~/Library/Logs/TecopaPlateworks.log`.

- [ ] **Step 4: Commit**

```bash
git add scripts/macos/TecopaPlateworksLauncher.swift
git commit -m "launcher: start the engine with TECOPA_DEBUG=1, so the tecopa tool can read its jobs and sessions"
```

---

### Task 5: The package, the value types, and the build script

**Goal:** `tools/tecopa/` builds a `tecopa` binary that prints its version, with the JSON value type, the failure type and the repo locator tested.

**Files:**
- Create: `tools/tecopa/Package.swift`
- Create: `tools/tecopa/build.sh`
- Create: `tools/tecopa/Sources/TecopaKit/JSONValue.swift`
- Create: `tools/tecopa/Sources/TecopaKit/TecopaFailure.swift`
- Create: `tools/tecopa/Sources/TecopaKit/Baked.swift`
- Create: `tools/tecopa/Sources/TecopaKit/RepoLocator.swift`
- Create: `tools/tecopa/Sources/tecopa/Tecopa.swift`
- Create: `tools/tecopa/Tests/TecopaKitTests/ValueTests.swift`
- Modify: `.gitignore`

**Acceptance Criteria:**
- [ ] `swift test --package-path tools/tecopa` passes.
- [ ] `swift run --package-path tools/tecopa tecopa --version` prints `dev`.
- [ ] `tools/tecopa/build.sh` builds a release binary whose `--version` prints the `git describe` text.
- [ ] `git status` shows no `.build/` folder and no `Baked.generated.swift`.
- [ ] `tools/tecopa/Package.resolved` is committed.

**Verify:** `swift test --package-path tools/tecopa` → `Executed 9 tests, with 0 failures`.

**Steps:**

- [ ] **Step 1: Ignore the build output.** Append to `.gitignore`:

```
# the tecopa tool (tools/tecopa/build.sh): SwiftPM's build folder, and the file that
# bakes this machine's repo path into a release build
tools/tecopa/.build/
tools/tecopa/Sources/TecopaKit/Baked.generated.swift
```

- [ ] **Step 2: Write the manifest.** `tools/tecopa/Package.swift`:

```swift
// swift-tools-version: 6.0
import PackageDescription

// The `tecopa` tool: one binary that is a command line and an MCP server for the
// Tecopa Plateworks engine. Design: docs/superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md
let package = Package(
    name: "tecopa",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(url: "https://github.com/apple/swift-argument-parser.git", from: "1.8.2"),
        .package(url: "https://github.com/modelcontextprotocol/swift-sdk.git", from: "0.12.1"),
    ],
    targets: [
        // Foundation only. Every operation lives here, so the CLI and the MCP server
        // cannot differ.
        .target(name: "TecopaKit"),
        .executableTarget(
            name: "tecopa",
            dependencies: [
                "TecopaKit",
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
                .product(name: "MCP", package: "swift-sdk"),
            ]),
        .testTarget(name: "TecopaKitTests", dependencies: ["TecopaKit", "tecopa"]),
    ],
    swiftLanguageModes: [.v5]
)
```

- [ ] **Step 3: Write the failing tests.** `tools/tecopa/Tests/TecopaKitTests/ValueTests.swift`:

```swift
import XCTest
@testable import TecopaKit

final class ValueTests: XCTestCase {
    func testJSONRoundTripKeepsIntegersAndNesting() throws {
        let text = #"{"a":1,"b":1.5,"c":"x","d":[true,null],"e":{"f":2}}"#
        let value = try JSONValue.parse(Data(text.utf8))
        XCTAssertEqual(value["a"], .int(1))
        XCTAssertEqual(value["b"], .double(1.5))
        XCTAssertEqual(value["c"]?.stringValue, "x")
        XCTAssertEqual(value["d"], .array([.bool(true), .null]))
        XCTAssertEqual(value["e"]?["f"]?.intValue, 2)
        XCTAssertEqual(value.text(pretty: false), text)
    }

    func testFailureMapsEachKindToItsExitCode() {
        XCTAssertEqual(TecopaFailure(.refused, "x").exitCode, 1)
        XCTAssertEqual(TecopaFailure(.usage, "x").exitCode, 2)
        XCTAssertEqual(TecopaFailure(.engineUnreachable, "x").exitCode, 3)
        XCTAssertEqual(TecopaFailure(.environment, "x").exitCode, 4)
    }

    func testFailureEnvelopeCarriesTheEngineBody() {
        let f = TecopaFailure(.refused, "no", hint: "try", status: 422,
                              body: .object(["detail": .string("zoom cap")]))
        let e = f.json
        XCTAssertEqual(e["ok"], .bool(false))
        XCTAssertEqual(e["error"]?["kind"]?.stringValue, "refused")
        XCTAssertEqual(e["error"]?["hint"]?.stringValue, "try")
        XCTAssertEqual(e["error"]?["status"]?.intValue, 422)
        XCTAssertEqual(e["error"]?["body"]?["detail"]?.stringValue, "zoom cap")
    }

    func testSuccessEnvelope() {
        XCTAssertEqual(envelope(.int(3)), .object(["ok": .bool(true), "data": .int(3)]))
    }

    private let exists: (String) -> Bool = { $0.hasPrefix("/good/") }

    func testRepoFlagWinsOverVariableAndBakedPath() throws {
        let repo = try RepoLocator.resolve(flag: "/good/flag", env: ["TECOPA_REPO": "/good/env"],
                                           baked: "/good/baked", fileExists: exists)
        XCTAssertEqual(repo, "/good/flag")
    }

    func testRepoVariableWinsOverBakedPath() throws {
        let repo = try RepoLocator.resolve(flag: nil, env: ["TECOPA_REPO": "/good/env/"],
                                           baked: "/good/baked", fileExists: exists)
        XCTAssertEqual(repo, "/good/env")
    }

    func testRepoFallsBackToTheBakedPath() throws {
        let repo = try RepoLocator.resolve(flag: nil, env: [:], baked: "/good/baked", fileExists: exists)
        XCTAssertEqual(repo, "/good/baked")
    }

    func testAWrongFlagFailsAndDoesNotFallThrough() {
        // an explicit wrong path must be an error, never a silent use of another repo
        XCTAssertThrowsError(try RepoLocator.resolve(flag: "/bad/flag", env: [:],
                                                     baked: "/good/baked", fileExists: exists)) { error in
            let f = error as? TecopaFailure
            XCTAssertEqual(f?.kind, .environment)
            XCTAssertTrue(f?.message.contains("/bad/flag") ?? false)
            XCTAssertTrue(f?.message.contains("--repo") ?? false)
        }
    }

    func testNoPathAtAllIsAnEnvironmentFault() {
        XCTAssertThrowsError(try RepoLocator.resolve(flag: nil, env: [:], baked: nil, fileExists: exists)) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
    }
}
```

- [ ] **Step 4: Write `JSONValue.swift`**

```swift
import Foundation

/// Any JSON value. The engine's replies pass through the tool as this type, so the
/// tool never needs a model of a spec, a job or a session.
public enum JSONValue: Equatable, Sendable {
    case null
    case bool(Bool)
    case int(Int64)
    case double(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])
}

extension JSONValue: Codable {
    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() {
            self = .null
        } else if let v = try? c.decode(Bool.self) {
            self = .bool(v)
        } else if let v = try? c.decode(Int64.self) {
            self = .int(v)
        } else if let v = try? c.decode(Double.self) {
            self = .double(v)
        } else if let v = try? c.decode(String.self) {
            self = .string(v)
        } else if let v = try? c.decode([JSONValue].self) {
            self = .array(v)
        } else {
            self = .object(try c.decode([String: JSONValue].self))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .bool(let v): try c.encode(v)
        case .int(let v): try c.encode(v)
        case .double(let v): try c.encode(v)
        case .string(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        }
    }
}

extension JSONValue {
    public static func parse(_ data: Data) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: data)
    }

    /// Sorted keys, so the same value always prints the same text.
    public func text(pretty: Bool = true) -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = pretty
            ? [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
            : [.sortedKeys, .withoutEscapingSlashes]
        guard let data = try? encoder.encode(self) else { return "null" }
        return String(decoding: data, as: UTF8.self)
    }

    public subscript(key: String) -> JSONValue? {
        if case .object(let o) = self { return o[key] }
        return nil
    }

    public var stringValue: String? {
        if case .string(let s) = self { return s }
        return nil
    }

    public var intValue: Int? {
        switch self {
        case .int(let i): return Int(i)
        case .double(let d): return Int(d)
        default: return nil
        }
    }

    public var boolValue: Bool? {
        if case .bool(let b) = self { return b }
        return nil
    }

    public var arrayValue: [JSONValue]? {
        if case .array(let a) = self { return a }
        return nil
    }
}
```

- [ ] **Step 5: Write `TecopaFailure.swift`**

```swift
import Foundation

/// The one error the tool reports. It says what the engine or the machine said and
/// adds a hint. It never decides to retry.
public struct TecopaFailure: Error, Equatable, Sendable {
    public enum Kind: String, Sendable {
        case refused                              // the engine or a script said no
        case usage                                // the tool found a bad argument
        case engineUnreachable = "engine_unreachable"
        case environment                          // a missing repo, venv, script or launcher
    }

    public let kind: Kind
    public let message: String
    public let hint: String?
    public let status: Int?
    public let body: JSONValue?

    public init(_ kind: Kind, _ message: String, hint: String? = nil,
                status: Int? = nil, body: JSONValue? = nil) {
        self.kind = kind
        self.message = message
        self.hint = hint
        self.status = status
        self.body = body
    }

    public var exitCode: Int32 {
        switch kind {
        case .refused: return 1
        case .usage: return 2
        case .engineUnreachable: return 3
        case .environment: return 4
        }
    }

    /// The failure envelope. The engine's own body rides in it unchanged.
    public var json: JSONValue {
        var error: [String: JSONValue] = [
            "kind": .string(kind.rawValue), "message": .string(message)]
        if let hint { error["hint"] = .string(hint) }
        if let status { error["status"] = .int(Int64(status)) }
        if let body { error["body"] = body }
        return .object(["ok": .bool(false), "error": .object(error)])
    }
}

/// The success envelope.
public func envelope(_ data: JSONValue) -> JSONValue {
    .object(["ok": .bool(true), "data": data])
}
```

- [ ] **Step 6: Write `Baked.swift`**

```swift
// build.sh writes Baked.generated.swift (gitignored) and builds with -DTECOPA_BAKED.
// That file then supplies these two names. A plain `swift build` or `swift test`
// compiles the defaults below, so a test never depends on where this checkout is.
#if !TECOPA_BAKED
public let bakedRepoPath: String? = nil
public let bakedVersion: String = "dev"
#endif
```

- [ ] **Step 7: Write `RepoLocator.swift`**

```swift
import Foundation

/// Where the repo is. The first source that names a path wins, and a wrong path is
/// an error: the tool never searches, and never falls through to another repo.
public enum RepoLocator {
    /// The file that proves a folder is the repo.
    static let marker = "app/main.py"

    public static func resolve(flag: String?, env: [String: String], baked: String?,
                               fileExists: (String) -> Bool) throws -> String {
        let candidates: [(source: String, path: String?)] = [
            ("--repo", flag),
            ("TECOPA_REPO", env["TECOPA_REPO"]),
            ("the path baked at build time", baked),
        ]
        guard let chosen = candidates.first(where: { !($0.path ?? "").isEmpty }),
              let path = chosen.path else {
            throw TecopaFailure(
                .environment, "No repository path is known.",
                hint: "Pass --repo, set TECOPA_REPO, or build with tools/tecopa/build.sh --install.")
        }
        let clean = path.hasSuffix("/") ? String(path.dropLast()) : path
        guard fileExists(clean + "/" + marker) else {
            throw TecopaFailure(
                .environment, "The repository is not at \(clean) (from \(chosen.source)).",
                hint: "Rebuild with tools/tecopa/build.sh --install, or pass --repo.")
        }
        return clean
    }
}
```

- [ ] **Step 8: Write the root command.** `tools/tecopa/Sources/tecopa/Tecopa.swift`:

```swift
import ArgumentParser
import TecopaKit

@main
struct Tecopa: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "tecopa",
        abstract: "Control and diagnose the Tecopa Plateworks engine.",
        version: bakedVersion,
        subcommands: [])
}
```

- [ ] **Step 9: Run the tests and the binary**

Run: `swift test --package-path tools/tecopa`
Expected: `Executed 9 tests, with 0 failures`.
Run: `swift run --package-path tools/tecopa tecopa --version`
Expected: `dev`.

- [ ] **Step 10: Write `tools/tecopa/build.sh`**

```bash
#!/usr/bin/env bash
# Build (and optionally install) the tecopa tool.
# Usage: tools/tecopa/build.sh [--install]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
INSTALL=0
[[ "${1:-}" == "--install" ]] && INSTALL=1

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
```

Run: `chmod +x tools/tecopa/build.sh && tools/tecopa/build.sh && tools/tecopa/.build/release/tecopa --version`
Expected: `Built: …/tools/tecopa/.build/release/tecopa`, then the `git describe` text, for example `38ce397-dirty`.

- [ ] **Step 11: Commit**

Run: `git status --short`
Expected: no `.build/` line and no `Baked.generated.swift` line.

```bash
git add .gitignore tools/tecopa/Package.swift tools/tecopa/Package.resolved tools/tecopa/build.sh tools/tecopa/Sources tools/tecopa/Tests
git commit -m "tecopa: the Swift package, its value types and its build script, so later commands share one failure shape"
```

---

### Task 6: The seams and the engine client

**Goal:** `EngineClient` reads the engine over HTTP, reports an unreachable engine and a closed gate as clear failures, and is tested with no network.

**Files:**
- Create: `tools/tecopa/Sources/TecopaKit/Seams.swift`
- Create: `tools/tecopa/Sources/TecopaKit/Runtime.swift`
- Create: `tools/tecopa/Sources/TecopaKit/EngineClient.swift`
- Create: `tools/tecopa/Tests/TecopaKitTests/Fakes.swift`
- Create: `tools/tecopa/Tests/TecopaKitTests/EngineClientTests.swift`

**Acceptance Criteria:**
- [ ] No reply from the engine gives a failure of kind `engine_unreachable` with the hint "Run `tecopa doctor`."
- [ ] A 4xx or 5xx reply gives a failure of kind `refused` whose `status` and `body` are the engine's own.
- [ ] A 404 with detail `Not Found` on a debug path gives a failure that names `TECOPA_DEBUG`.
- [ ] A 404 with another detail on a debug path keeps the engine's body.
- [ ] `raw` returns a 503 reply as a reply, not as a failure.

**Verify:** `swift test --package-path tools/tecopa --filter EngineClientTests` → `Executed 5 tests, with 0 failures`.

**Steps:**

- [ ] **Step 1: Write the fakes.** `tools/tecopa/Tests/TecopaKitTests/Fakes.swift`:

```swift
import Foundation
@testable import TecopaKit

/// One fake machine for a test: an engine that answers some paths, and a process
/// runner that records each command. `onRun` lets a test change the engine when a
/// command runs, which is how "the launcher starts the engine" is modelled.
final class FakeWorld: HTTPFetching, ProcessRunning, @unchecked Sendable {
    private let lock = NSLock()
    private var routes: [String: (Int, String)] = [:]
    private var results: [String: ProcessResult] = [:]
    private(set) var commands: [[String]] = []
    var onRun: ((FakeWorld, [String]) -> Void)?

    /// `path` includes the query, for example "/api/debug/sessions/ab?full=1".
    func serve(_ path: String, _ status: Int, _ body: String) {
        lock.lock(); routes[path] = (status, body); lock.unlock()
    }

    func stopServing() {
        lock.lock(); routes.removeAll(); lock.unlock()
    }

    /// The result for any command whose executable ends with `name`.
    func result(for name: String, _ result: ProcessResult) {
        lock.lock(); results[name] = result; lock.unlock()
    }

    func get(_ url: URL, timeout: TimeInterval) async throws -> (status: Int, body: Data) {
        let key = url.path + (url.query.map { "?" + $0 } ?? "")
        lock.lock(); let route = routes[key]; lock.unlock()
        guard let route else { throw URLError(.cannotConnectToHost) }
        return (route.0, Data(route.1.utf8))
    }

    func run(_ executable: String, _ arguments: [String], cwd: String?) throws -> ProcessResult {
        let command = [executable] + arguments
        lock.lock()
        commands.append(command)
        let name = (executable as NSString).lastPathComponent
        let result = results[name] ?? ProcessResult(exitCode: 0, stdout: "", stderr: "")
        lock.unlock()
        onRun?(self, command)
        return result
    }

    static let readyBody = #"{"ready":true,"regions":[{"id":"lassen_ca","ready":true}]}"#

    func runtime(port: Int = 8848, repo: String? = "/repo", home: String = "/home") -> Runtime {
        Runtime(repoFlag: repo, port: port, environment: [:], home: home,
                http: self, runner: self,
                fileExists: { _ in true },
                sleep: { _ in })
    }
}
```

- [ ] **Step 2: Write the failing tests.** `tools/tecopa/Tests/TecopaKitTests/EngineClientTests.swift`:

```swift
import XCTest
@testable import TecopaKit

final class EngineClientTests: XCTestCase {
    func testNoReplyIsEngineUnreachableWithTheDoctorHint() async {
        let world = FakeWorld()
        do {
            _ = try await world.runtime().client.get("/api/regions")
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .engineUnreachable)
            XCTAssertEqual(f.hint, "Run `tecopa doctor`.")
            XCTAssertTrue(f.message.contains("8848"))
        } catch { XCTFail("\(error)") }
    }

    func testAnEngineRefusalKeepsTheEnginesOwnBody() async {
        let world = FakeWorld()
        world.serve("/api/regions", 503, #"{"detail":"DEM bounds drift: lassen_ca"}"#)
        do {
            _ = try await world.runtime().client.get("/api/regions")
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .refused)
            XCTAssertEqual(f.status, 503)
            XCTAssertEqual(f.body?["detail"]?.stringValue, "DEM bounds drift: lassen_ca")
        } catch { XCTFail("\(error)") }
    }

    func testRawReturnsA503AsAReply() async throws {
        // /readyz answers 503 when a plate cannot render: that is an answer, not an outage
        let world = FakeWorld()
        world.serve("/readyz", 503, #"{"ready":false,"regions":[]}"#)
        let reply = try await world.runtime().client.raw("/readyz")
        XCTAssertEqual(reply.status, 503)
        XCTAssertEqual(reply.json["ready"], .bool(false))
    }

    func testAClosedGateNamesTheVariable() async {
        let world = FakeWorld()
        world.serve("/api/debug/jobs", 404, #"{"detail":"Not Found"}"#)
        do {
            _ = try await world.runtime().client.debug("/jobs")
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .refused)
            XCTAssertTrue(f.message.contains("debug routes are off"))
            XCTAssertTrue(f.hint?.contains("TECOPA_DEBUG=1") ?? false)
        } catch { XCTFail("\(error)") }
    }

    func testAnUnknownSessionIsNotMistakenForAClosedGate() async {
        let world = FakeWorld()
        world.serve("/api/debug/sessions/ab", 404, #"{"detail":"Unknown session"}"#)
        do {
            _ = try await world.runtime().client.debug("/sessions/ab")
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.body?["detail"]?.stringValue, "Unknown session")
            XCTAssertFalse(f.message.contains("debug routes are off"))
        } catch { XCTFail("\(error)") }
    }
}
```

- [ ] **Step 3: Write `Seams.swift`**

```swift
import Foundation

/// The two places the tool touches the machine. A test replaces both.
public protocol HTTPFetching: Sendable {
    /// Any HTTP answer returns. No answer throws.
    func get(_ url: URL, timeout: TimeInterval) async throws -> (status: Int, body: Data)
}

public struct ProcessResult: Equatable, Sendable {
    public let exitCode: Int32
    public let stdout: String
    public let stderr: String

    public init(exitCode: Int32, stdout: String, stderr: String) {
        self.exitCode = exitCode
        self.stdout = stdout
        self.stderr = stderr
    }
}

public protocol ProcessRunning: Sendable {
    func run(_ executable: String, _ arguments: [String], cwd: String?) throws -> ProcessResult
}

public struct URLSessionFetcher: HTTPFetching {
    public init() {}

    public func get(_ url: URL, timeout: TimeInterval) async throws -> (status: Int, body: Data) {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = timeout
        config.timeoutIntervalForResource = timeout
        let session = URLSession(configuration: config)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(from: url)
        return ((response as? HTTPURLResponse)?.statusCode ?? 0, data)
    }
}

public struct SystemProcessRunner: ProcessRunning {
    public init() {}

    public func run(_ executable: String, _ arguments: [String], cwd: String?) throws -> ProcessResult {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        if let cwd { process.currentDirectoryURL = URL(fileURLWithPath: cwd) }
        let out = Pipe()
        let err = Pipe()
        process.standardOutput = out
        process.standardError = err
        // Never the tool's own stdin or stdout: under `tecopa mcp` those carry the
        // protocol, and a child that wrote to them would corrupt it.
        process.standardInput = FileHandle.nullDevice
        try process.run()

        // Drain both pipes while the child runs. A child that fills one pipe while
        // the tool waits on the other would block for ever.
        var errData = Data()
        let group = DispatchGroup()
        group.enter()
        DispatchQueue.global().async {
            errData = err.fileHandleForReading.readDataToEndOfFile()
            group.leave()
        }
        let outData = out.fileHandleForReading.readDataToEndOfFile()
        group.wait()
        process.waitUntilExit()
        return ProcessResult(exitCode: process.terminationStatus,
                             stdout: String(decoding: outData, as: UTF8.self),
                             stderr: String(decoding: errData, as: UTF8.self))
    }
}
```

- [ ] **Step 4: Write `Runtime.swift`**

```swift
import Foundation

/// What one call needs. The CLI and the MCP server each build one, and a test builds
/// one over a fake machine.
public struct Runtime: Sendable {
    public var repoFlag: String?
    public var port: Int
    public var environment: [String: String]
    public var home: String
    public var http: any HTTPFetching
    public var runner: any ProcessRunning
    public var fileExists: @Sendable (String) -> Bool
    public var sleep: @Sendable (Double) async -> Void

    public init(
        repoFlag: String? = nil,
        port: Int = 8848,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        home: String = NSHomeDirectory(),
        http: any HTTPFetching = URLSessionFetcher(),
        runner: any ProcessRunning = SystemProcessRunner(),
        fileExists: @escaping @Sendable (String) -> Bool = { FileManager.default.fileExists(atPath: $0) },
        sleep: @escaping @Sendable (Double) async -> Void = {
            try? await Task.sleep(nanoseconds: UInt64($0 * 1_000_000_000))
        }
    ) {
        self.repoFlag = repoFlag
        self.port = port
        self.environment = environment
        self.home = home
        self.http = http
        self.runner = runner
        self.fileExists = fileExists
        self.sleep = sleep
    }

    public var client: EngineClient { EngineClient(port: port, http: http) }

    public func repo() throws -> String {
        try RepoLocator.resolve(flag: repoFlag, env: environment, baked: bakedRepoPath,
                                fileExists: fileExists)
    }

    /// The launcher's log. The launcher and its engine both write here.
    public var logPath: String { home + "/Library/Logs/TecopaPlateworks.log" }

    /// Run one program. A program that cannot start is an environment fault.
    public func exec(_ executable: String, _ arguments: [String], cwd: String? = nil) throws -> ProcessResult {
        do {
            return try runner.run(executable, arguments, cwd: cwd)
        } catch let failure as TecopaFailure {
            throw failure
        } catch {
            throw TecopaFailure(.environment,
                                "Could not start \(executable): \(error.localizedDescription)")
        }
    }
}
```

- [ ] **Step 5: Write `EngineClient.swift`**

```swift
import Foundation

/// HTTP to the engine, on 127.0.0.1 only. It reports what the engine said. It never
/// retries, and it never sends a flag that the caller did not give.
public struct EngineClient: Sendable {
    public let port: Int
    public let http: any HTTPFetching

    public init(port: Int, http: any HTTPFetching) {
        self.port = port
        self.http = http
    }

    public struct Reply: Equatable, Sendable {
        public let status: Int
        public let json: JSONValue
    }

    /// Any HTTP answer is a Reply, a 503 included. No answer is `engine_unreachable`.
    public func raw(_ path: String, timeout: TimeInterval = 10) async throws -> Reply {
        guard let url = URL(string: "http://127.0.0.1:\(port)" + path) else {
            throw TecopaFailure(.usage, "Not a valid path: \(path)")
        }
        let fetched: (status: Int, body: Data)
        do {
            fetched = try await http.get(url, timeout: timeout)
        } catch {
            throw TecopaFailure(.engineUnreachable, "No engine answers on port \(port).",
                                hint: "Run `tecopa doctor`.")
        }
        let json = (try? JSONValue.parse(fetched.body))
            ?? .string(String(decoding: fetched.body, as: UTF8.self))
        return Reply(status: fetched.status, json: json)
    }

    /// A 2xx body. Any other status is `refused`, with the engine's own body.
    public func get(_ path: String) async throws -> JSONValue {
        let reply = try await raw(path)
        guard (200..<300).contains(reply.status) else {
            throw TecopaFailure(.refused, "The engine answered \(reply.status) for \(path).",
                                status: reply.status, body: reply.json)
        }
        return reply.json
    }

    /// A debug route. With the gate off the router does not exist, and the static
    /// mount answers 404 "Not Found". A debug route's own 404 has another detail.
    public func debug(_ path: String) async throws -> JSONValue {
        do {
            return try await get("/api/debug" + path)
        } catch let failure as TecopaFailure
            where failure.status == 404 && failure.body?["detail"]?.stringValue == "Not Found" {
            throw TecopaFailure(
                .refused, "The debug routes are off on port \(port).",
                hint: "Start the engine with TECOPA_DEBUG=1. The launcher sets it.",
                status: 404, body: failure.body)
        }
    }
}
```

- [ ] **Step 6: Run the tests**

Run: `swift test --package-path tools/tecopa --filter EngineClientTests`
Expected: `Executed 5 tests, with 0 failures`.

- [ ] **Step 7: Commit**

```bash
git add tools/tecopa/Sources/TecopaKit tools/tecopa/Tests
git commit -m "tecopa: the engine client reports the engine's own answer, and names the gate when the debug routes are off"
```

---

### Task 7: The catalog and the five read commands

**Goal:** `tecopa engine status`, `regions`, `jobs`, `sessions` and `caches` work from the command line, each as one catalog entry that the MCP server will reuse.

**Files:**
- Create: `tools/tecopa/Sources/TecopaKit/Catalog.swift`
- Create: `tools/tecopa/Sources/TecopaKit/EngineEntries.swift`
- Create: `tools/tecopa/Sources/tecopa/Shared.swift`
- Create: `tools/tecopa/Sources/tecopa/Commands.swift`
- Modify: `tools/tecopa/Sources/tecopa/Tecopa.swift`
- Create: `tools/tecopa/Tests/TecopaKitTests/EngineEntriesTests.swift`

**Acceptance Criteria:**
- [ ] `Catalog.call` never throws. It returns the success envelope, or the failure envelope and the failure.
- [ ] `engine_status` with no engine returns `{"running": false, "port": 8848}` as a success.
- [ ] `engine_status` with another program on the port fails with kind `environment`.
- [ ] `engine_status` reports `"debug": false` when the gate is off and still succeeds.
- [ ] `sessions` refuses a `sid` that is not hexadecimal.
- [ ] `tecopa jobs --json` against a stopped engine prints the failure envelope and exits 3.

**Verify:** `swift test --package-path tools/tecopa --filter EngineEntriesTests` → `Executed 7 tests, with 0 failures`.

**Steps:**

- [ ] **Step 1: Write the failing tests.** `tools/tecopa/Tests/TecopaKitTests/EngineEntriesTests.swift`:

```swift
import XCTest
@testable import TecopaKit

final class EngineEntriesTests: XCTestCase {
    func testCallWrapsSuccessInTheEnvelope() async {
        let world = FakeWorld()
        world.serve("/api/debug/caches", 200, #"{"base":{"entries":0}}"#)
        let (env, failure) = await Catalog.call("caches", world.runtime(), [:])
        XCTAssertNil(failure)
        XCTAssertEqual(env["ok"], .bool(true))
        XCTAssertEqual(env["data"]?["base"]?["entries"]?.intValue, 0)
    }

    func testCallReturnsTheFailureEnvelopeAndNeverThrows() async {
        let (env, failure) = await Catalog.call("jobs", FakeWorld().runtime(), [:])
        XCTAssertEqual(failure?.kind, .engineUnreachable)
        XCTAssertEqual(env["ok"], .bool(false))
        XCTAssertEqual(env["error"]?["kind"]?.stringValue, "engine_unreachable")
    }

    func testAnUnknownNameIsAUsageFailure() async {
        let (_, failure) = await Catalog.call("no_such", FakeWorld().runtime(), [:])
        XCTAssertEqual(failure?.kind, .usage)
    }

    func testEngineStatusWithNoEngineIsData() async {
        let (env, failure) = await Catalog.call("engine_status", FakeWorld().runtime(), [:])
        XCTAssertNil(failure)
        XCTAssertEqual(env["data"]?["running"], .bool(false))
        XCTAssertEqual(env["data"]?["port"]?.intValue, 8848)
    }

    func testEngineStatusRefusesAForeignProgramOnThePort() async {
        let world = FakeWorld()
        world.serve("/readyz", 200, "<html>hello</html>")
        let (_, failure) = await Catalog.call("engine_status", world.runtime(), [:])
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertTrue(failure?.message.contains("not Tecopa Plateworks") ?? false)
    }

    func testEngineStatusReportsTheGate() async {
        let world = FakeWorld()
        world.serve("/readyz", 200, FakeWorld.readyBody)
        world.serve("/api/debug/engine", 404, #"{"detail":"Not Found"}"#)
        var (env, _) = await Catalog.call("engine_status", world.runtime(), [:])
        XCTAssertEqual(env["data"]?["running"], .bool(true))
        XCTAssertEqual(env["data"]?["debug"], .bool(false))

        world.serve("/api/debug/engine", 200, #"{"engine":"tecopa-plateworks","pid":7}"#)
        (env, _) = await Catalog.call("engine_status", world.runtime(), [:])
        XCTAssertEqual(env["data"]?["debug"], .bool(true))
        XCTAssertEqual(env["data"]?["engine"]?["pid"]?.intValue, 7)
    }

    func testSessionsRefusesAnIdThatIsNotHexadecimal() async {
        // the id goes into a URL path; a session id is uuid4().hex and nothing else
        let (_, failure) = await Catalog.call("sessions", FakeWorld().runtime(),
                                              ["sid": .string("../engine")])
        XCTAssertEqual(failure?.kind, .usage)
    }
}
```

- [ ] **Step 2: Write `Catalog.swift`**

```swift
import Foundation

/// One argument of one entry. The CLI declares it as an option and the MCP server
/// puts it in the tool's input schema.
public struct EntryParameter: Sendable {
    public enum Kind: String, Sendable { case string, integer, boolean, stringArray }

    public let name: String
    public let kind: Kind
    public let summary: String

    public init(_ name: String, _ kind: Kind, _ summary: String) {
        self.name = name
        self.kind = kind
        self.summary = summary
    }
}

/// One operation. `name` is the MCP tool name, and the CLI command is the same words
/// with a space for each underscore.
public struct CatalogEntry: Sendable {
    public let name: String
    public let summary: String
    public let readOnly: Bool
    public let parameters: [EntryParameter]
    public let run: @Sendable (Runtime, [String: JSONValue]) async throws -> JSONValue
    /// How the CLI prints the data without --json. nil means pretty JSON.
    public let text: (@Sendable (JSONValue) -> String)?

    public init(name: String, summary: String, readOnly: Bool,
                parameters: [EntryParameter] = [],
                text: (@Sendable (JSONValue) -> String)? = nil,
                run: @escaping @Sendable (Runtime, [String: JSONValue]) async throws -> JSONValue) {
        self.name = name
        self.summary = summary
        self.readOnly = readOnly
        self.parameters = parameters
        self.text = text
        self.run = run
    }
}

/// Every operation the tool has. The CLI and the MCP server both call `call`, so a
/// command and its tool cannot differ.
public enum Catalog {
    public static let all: [CatalogEntry] = EngineEntries.all

    public static func named(_ name: String) -> CatalogEntry? {
        all.first { $0.name == name }
    }

    /// Run one entry. Never throws: a failure comes back as its envelope.
    public static func call(_ name: String, _ runtime: Runtime,
                            _ arguments: [String: JSONValue]) async -> (envelope: JSONValue, failure: TecopaFailure?) {
        guard let entry = named(name) else {
            let failure = TecopaFailure(.usage, "Unknown command: \(name)")
            return (failure.json, failure)
        }
        do {
            return (envelope(try await entry.run(runtime, arguments)), nil)
        } catch let failure as TecopaFailure {
            return (failure.json, failure)
        } catch {
            let failure = TecopaFailure(.environment, "\(error)")
            return (failure.json, failure)
        }
    }
}
```

- [ ] **Step 3: Write `EngineEntries.swift`**

```swift
import Foundation

/// The entries that only read the engine over HTTP.
enum EngineEntries {
    static let all: [CatalogEntry] = [engineStatus, regions, jobs, sessions, caches]

    static let engineStatus = CatalogEntry(
        name: "engine_status",
        summary: "Report if the engine answers, each plate's readiness, and the debug gate.",
        readOnly: true
    ) { runtime, _ in
        let ready: EngineClient.Reply
        do {
            ready = try await runtime.client.raw("/readyz", timeout: 3)
        } catch let failure as TecopaFailure where failure.kind == .engineUnreachable {
            // a stopped engine is a normal state, so it is data and not a failure
            return .object(["running": .bool(false), "port": .int(Int64(runtime.port))])
        }
        guard let isReady = ready.json["ready"], let plates = ready.json["regions"] else {
            throw TecopaFailure(
                .environment, "Port \(runtime.port) answers, but it is not Tecopa Plateworks.",
                hint: "Quit the other program on that port.")
        }
        var out: [String: JSONValue] = [
            "running": .bool(true), "port": .int(Int64(runtime.port)),
            "ready": isReady, "regions": plates,
        ]
        if let engine = try? await runtime.client.debug("/engine") {
            out["debug"] = .bool(true)
            out["engine"] = engine
        } else {
            out["debug"] = .bool(false)
        }
        return .object(out)
    }

    static let regions = CatalogEntry(
        name: "regions",
        summary: "List the plates the engine serves, with the readiness report for each.",
        readOnly: true
    ) { runtime, _ in
        let plates = try await runtime.client.get("/api/regions")
        let ready = try await runtime.client.raw("/readyz")
        return .object([
            "regions": plates,
            "ready": ready.json["ready"] ?? .null,
            "readiness": ready.json["regions"] ?? .null,
        ])
    }

    static let jobs = CatalogEntry(
        name: "jobs",
        summary: "List every job in the render, build and proof queues, newest first.",
        readOnly: true
    ) { runtime, _ in
        try await runtime.client.debug("/jobs")
    }

    static let sessions = CatalogEntry(
        name: "sessions",
        summary: "List the engine's sessions, or show one session's spec and tracks.",
        readOnly: true,
        parameters: [
            EntryParameter("sid", .string, "A session id. Without it, every session is listed."),
            EntryParameter("full", .boolean, "With sid: include the track geometry."),
        ]
    ) { runtime, arguments in
        guard let sid = arguments["sid"]?.stringValue, !sid.isEmpty else {
            return try await runtime.client.debug("/sessions")
        }
        // the id goes into the URL path, and a real id is uuid4().hex
        guard sid.allSatisfy({ $0.isHexDigit }) else {
            throw TecopaFailure(.usage, "A session id is hexadecimal: \(sid)")
        }
        let full = arguments["full"]?.boolValue ?? false
        return try await runtime.client.debug("/sessions/" + sid + (full ? "?full=1" : ""))
    }

    static let caches = CatalogEntry(
        name: "caches",
        summary: "Report the terrain cache and the route-ink cache: entries, bytes, hits, misses.",
        readOnly: true
    ) { runtime, _ in
        try await runtime.client.debug("/caches")
    }
}
```

- [ ] **Step 4: Run the kit tests**

Run: `swift test --package-path tools/tecopa --filter EngineEntriesTests`
Expected: `Executed 7 tests, with 0 failures`.

- [ ] **Step 5: Write `Shared.swift`**

```swift
import ArgumentParser
import Foundation
import TecopaKit

/// The three options every command takes.
struct GlobalOptions: ParsableArguments {
    @Flag(name: .long, help: "Print the result envelope as JSON.")
    var json = false

    @Option(name: .long, help: "The repository path. Default: TECOPA_REPO, then the baked path.")
    var repo: String?

    @Option(name: .long, help: "The engine port.")
    var port: Int = 8848
}

/// Run one catalog entry and print it. The one place the CLI prints and exits, so
/// every command has the same output and the same exit codes.
@discardableResult
func execute(_ name: String, _ global: GlobalOptions,
             _ arguments: [String: JSONValue] = [:]) async throws -> JSONValue {
    let runtime = Runtime(repoFlag: global.repo, port: global.port)
    let (result, failure) = await Catalog.call(name, runtime, arguments)
    let data = result["data"] ?? .null

    if global.json {
        print(result.text())
    } else if let failure {
        var lines = ["error: \(failure.message)"]
        if let hint = failure.hint { lines.append("hint: \(hint)") }
        if let body = failure.body { lines.append(body.text()) }
        FileHandle.standardError.write(Data((lines.joined(separator: "\n") + "\n").utf8))
    } else {
        print(Catalog.named(name)?.text?(data) ?? data.text())
    }

    if let failure { throw ExitCode(failure.exitCode) }
    return data
}
```

- [ ] **Step 6: Write `Commands.swift`**

```swift
import ArgumentParser
import TecopaKit

// One thin struct per command. Each one names its catalog entry and passes its
// arguments. No command holds logic of its own.

struct EngineCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "engine",
        abstract: "Read or control the launcher's engine.",
        subcommands: [Status.self])

    struct Status: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "status", abstract: "Report if the engine answers, and the debug gate.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("engine_status", global) }
    }
}

struct RegionsCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "regions",
        abstract: "List the plates, or check them against sources.json.",
        subcommands: [List.self],
        defaultSubcommand: List.self)

    struct List: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "list", abstract: "List the plates with the readiness report.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("regions", global) }
    }
}

struct JobsCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "jobs", abstract: "List every job in the three queues.")
    @OptionGroup var global: GlobalOptions
    func run() async throws { try await execute("jobs", global) }
}

struct SessionsCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "sessions", abstract: "List the sessions, or show one.")
    @OptionGroup var global: GlobalOptions
    @Argument(help: "A session id. Without it, every session is listed.")
    var sid: String?
    @Flag(name: .long, help: "With a session id: include the track geometry.")
    var full = false

    func run() async throws {
        var arguments: [String: JSONValue] = [:]
        if let sid { arguments["sid"] = .string(sid) }
        if full { arguments["full"] = .bool(true) }
        try await execute("sessions", global, arguments)
    }
}

struct CachesCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "caches", abstract: "Report the terrain and route-ink caches.")
    @OptionGroup var global: GlobalOptions
    func run() async throws { try await execute("caches", global) }
}
```

- [ ] **Step 7: List the commands in `Tecopa.swift`.** Replace the `subcommands: []` line:

```swift
        subcommands: [
            EngineCommand.self, RegionsCommand.self, JobsCommand.self,
            SessionsCommand.self, CachesCommand.self,
        ])
```

- [ ] **Step 8: Run the binary against a stopped engine**

Run: `swift run --package-path tools/tecopa tecopa jobs --json; echo "exit $?"`
Expected: an envelope with `"ok" : false` and `"kind" : "engine_unreachable"`, then `exit 3`.
Run: `swift run --package-path tools/tecopa tecopa engine status`
Expected: JSON with `"running" : false`.

- [ ] **Step 9: Run every Swift test, then commit**

Run: `swift test --package-path tools/tecopa`
Expected: `Executed 21 tests, with 0 failures`.

```bash
git add tools/tecopa/Sources tools/tecopa/Tests
git commit -m "tecopa: a catalog of read commands for status, plates, jobs, sessions and caches, the one path the CLI and MCP will share"
```

---

### Task 8: The log reader

**Goal:** `tecopa logs` returns the tail of the launcher log, filtered by a substring and by an age.

**Files:**
- Create: `tools/tecopa/Sources/TecopaKit/LogReader.swift`
- Modify: `tools/tecopa/Sources/TecopaKit/Catalog.swift` (the `all` line)
- Modify: `tools/tecopa/Sources/tecopa/Commands.swift`
- Modify: `tools/tecopa/Sources/tecopa/Tecopa.swift`
- Create: `tools/tecopa/Tests/TecopaKitTests/LogReaderTests.swift`

**Acceptance Criteria:**
- [ ] `--lines 2` returns the last 2 lines that pass the filters.
- [ ] `--grep` matches a substring in any letter case.
- [ ] `--since 30m` drops each line older than 30 minutes, and a line with no timestamp takes the timestamp of the stamped line above it.
- [ ] `--since 5x` is a usage failure.
- [ ] A missing log returns `"exists": false` and no failure.

**Verify:** `swift test --package-path tools/tecopa --filter LogReaderTests` → `Executed 6 tests, with 0 failures`.

**Steps:**

- [ ] **Step 1: Write the failing tests.** `tools/tecopa/Tests/TecopaKitTests/LogReaderTests.swift`:

```swift
import XCTest
@testable import TecopaKit

final class LogReaderTests: XCTestCase {
    // the launcher stamps in UTC with brackets; uvicorn's own lines have no stamp
    private let log = """
    [2026-10-22 10:00:00 +0000] starting engine
    INFO:     Started server process [100]
    [2026-10-22 11:00:00 +0000] engine ready
    INFO:     127.0.0.1:5000 - "GET /readyz HTTP/1.1" 200 OK
    Traceback (most recent call last):
      File "app/render.py", line 1, in rasterize
    ValueError: bad crop
    """

    private func date(_ text: String) -> Date {
        ISO8601DateFormatter().date(from: text)!
    }

    func testLinesKeepsTheTail() {
        let kept = LogReader.filter(log, lines: 2, grep: nil, since: nil)
        XCTAssertEqual(kept, ["  File \"app/render.py\", line 1, in rasterize", "ValueError: bad crop"])
    }

    func testGrepIsACaseInsensitiveSubstring() {
        let kept = LogReader.filter(log, lines: 50, grep: "valueerror", since: nil)
        XCTAssertEqual(kept, ["ValueError: bad crop"])
    }

    func testSinceDropsOlderLinesAndUnstampedLinesInheritTheStampAbove() {
        let kept = LogReader.filter(log, lines: 50, grep: nil, since: date("2026-10-22T10:30:00Z"))
        XCTAssertEqual(kept.first, "[2026-10-22 11:00:00 +0000] engine ready")
        XCTAssertEqual(kept.count, 5)
        XCTAssertFalse(kept.contains("INFO:     Started server process [100]"))
    }

    func testSinceParsesADuration() throws {
        let now = date("2026-10-22T12:00:00Z")
        XCTAssertEqual(try LogReader.parseSince("30m", now: now), date("2026-10-22T11:30:00Z"))
        XCTAssertEqual(try LogReader.parseSince("2h", now: now), date("2026-10-22T10:00:00Z"))
        XCTAssertEqual(try LogReader.parseSince("1d", now: now), date("2026-10-21T12:00:00Z"))
    }

    func testABadDurationIsAUsageFailure() {
        XCTAssertThrowsError(try LogReader.parseSince("5x", now: Date())) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .usage)
        }
    }

    func testAMissingLogIsDataAndNotAFailure() {
        let value = LogReader.read(path: "/no/such/file.log", lines: 10, grep: nil, since: nil)
        XCTAssertEqual(value["exists"], .bool(false))
        XCTAssertEqual(value["lines"], .array([]))
    }
}
```

- [ ] **Step 2: Write `LogReader.swift`**

```swift
import Foundation

/// The launcher log. The launcher and the engine it starts both append to one file,
/// so three line shapes are mixed in it:
///   [2026-09-02 19:56:17 +0000] launcher line      (UTC, in brackets)
///   2026-09-02T12:56:20 INFO tecopa.api message    (the engine's logger, local time)
///   INFO:     Started server process [13779]       (uvicorn, no timestamp)
public enum LogReader {
    /// Read at most this much from the end of the file.
    static let tailBytes: UInt64 = 2_000_000

    private static let launcherStamp: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd HH:mm:ss Z"
        return f
    }()

    private static let engineStamp: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f
    }()

    /// "90s", "30m", "2h", "1d" before `now`.
    public static func parseSince(_ text: String, now: Date) throws -> Date {
        let units: [Character: Double] = ["s": 1, "m": 60, "h": 3600, "d": 86400]
        guard let unit = text.last, let seconds = units[unit],
              let count = Double(text.dropLast()), count >= 0 else {
            throw TecopaFailure(.usage, "--since takes a number and a unit: 90s, 30m, 2h, 1d.")
        }
        return now.addingTimeInterval(-count * seconds)
    }

    static func stamp(of line: String) -> Date? {
        if line.hasPrefix("["), let end = line.firstIndex(of: "]") {
            return launcherStamp.date(from: String(line[line.index(after: line.startIndex)..<end]))
        }
        let head = Array(line.prefix(19))
        if head.count == 19, head[4] == "-", head[10] == "T" {
            return engineStamp.date(from: String(head))
        }
        return nil
    }

    /// The last `lines` lines that pass both filters. A line with no timestamp takes
    /// the timestamp of the nearest stamped line above it, so a traceback stays with
    /// the request that raised it.
    public static func filter(_ text: String, lines: Int, grep: String?, since: Date?) -> [String] {
        var kept: [String] = []
        var current: Date?
        for raw in text.split(separator: "\n", omittingEmptySubsequences: true) {
            let line = String(raw)
            if let found = stamp(of: line) { current = found }
            if let since {
                guard let current, current >= since else { continue }
            }
            if let grep, !grep.isEmpty, line.range(of: grep, options: .caseInsensitive) == nil {
                continue
            }
            kept.append(line)
        }
        return Array(kept.suffix(max(0, lines)))
    }

    public static func read(path: String, lines: Int, grep: String?, since: Date?) -> JSONValue {
        guard let handle = FileHandle(forReadingAtPath: path) else {
            return .object(["path": .string(path), "exists": .bool(false), "lines": .array([])])
        }
        defer { try? handle.close() }
        let size = (try? handle.seekToEnd()) ?? 0
        let start = size > tailBytes ? size - tailBytes : 0
        try? handle.seek(toOffset: start)
        let data = (try? handle.readToEnd()) ?? Data()
        var text = String(decoding: data, as: UTF8.self)
        // a read that starts inside the file starts inside a line: drop that part
        if start > 0, let newline = text.firstIndex(of: "\n") {
            text = String(text[text.index(after: newline)...])
        }
        let kept = filter(text, lines: lines, grep: grep, since: since)
        return .object([
            "path": .string(path), "exists": .bool(true),
            "lines": .array(kept.map { .string($0) }),
        ])
    }

    static let entry = CatalogEntry(
        name: "logs",
        summary: "Read the tail of the launcher log, which also holds the engine's output.",
        readOnly: true,
        parameters: [
            EntryParameter("lines", .integer, "How many lines to return. Default 50."),
            EntryParameter("grep", .string, "Keep only lines that contain this text, in any letter case."),
            EntryParameter("since", .string, "Keep only lines newer than this age: 90s, 30m, 2h, 1d."),
        ],
        text: { data in
            guard data["exists"]?.boolValue == true else {
                return "No log at \(data["path"]?.stringValue ?? "?")."
            }
            return (data["lines"]?.arrayValue ?? []).compactMap { $0.stringValue }.joined(separator: "\n")
        }
    ) { runtime, arguments in
        let since = try arguments["since"]?.stringValue.map { try parseSince($0, now: Date()) }
        return read(path: runtime.logPath,
                    lines: arguments["lines"]?.intValue ?? 50,
                    grep: arguments["grep"]?.stringValue,
                    since: since)
    }
}
```

- [ ] **Step 3: Add the entry to the catalog.** In `Catalog.swift`, replace the `all` line:

```swift
    public static let all: [CatalogEntry] = EngineEntries.all + [LogReader.entry]
```

- [ ] **Step 4: Add the command.** Append to `Commands.swift`:

```swift
struct LogsCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "logs", abstract: "Read the tail of the launcher log.")
    @OptionGroup var global: GlobalOptions
    @Option(name: .long, help: "How many lines to return.")
    var lines: Int = 50
    @Option(name: .long, help: "Keep only lines that contain this text.")
    var grep: String?
    @Option(name: .long, help: "Keep only lines newer than this age: 90s, 30m, 2h, 1d.")
    var since: String?

    func run() async throws {
        var arguments: [String: JSONValue] = ["lines": .int(Int64(lines))]
        if let grep { arguments["grep"] = .string(grep) }
        if let since { arguments["since"] = .string(since) }
        try await execute("logs", global, arguments)
    }
}
```

In `Tecopa.swift`, replace the `subcommands` list:

```swift
        subcommands: [
            EngineCommand.self, LogsCommand.self, RegionsCommand.self, JobsCommand.self,
            SessionsCommand.self, CachesCommand.self,
        ])
```

- [ ] **Step 5: Run the tests and the binary**

Run: `swift test --package-path tools/tecopa --filter LogReaderTests`
Expected: `Executed 6 tests, with 0 failures`.
Run: `swift run --package-path tools/tecopa tecopa logs --lines 5`
Expected: the last 5 lines of `~/Library/Logs/TecopaPlateworks.log`.

- [ ] **Step 6: Commit**

```bash
git add tools/tecopa/Sources tools/tecopa/Tests
git commit -m "tecopa: logs reads the launcher log by tail, text and age, so a traceback stays with its request"
```

---

### Task 9: Start, stop and restart through the launcher

**Goal:** `tecopa engine start`, `stop` and `restart` open and quit the launcher app, wait for the port to change state, and never start a second uvicorn.

**Files:**
- Create: `tools/tecopa/Sources/TecopaKit/Launcher.swift`
- Modify: `tools/tecopa/Sources/TecopaKit/Catalog.swift` (the `all` line)
- Modify: `tools/tecopa/Sources/tecopa/Commands.swift` (`EngineCommand`)
- Create: `tools/tecopa/Tests/TecopaKitTests/LauncherTests.swift`

**Acceptance Criteria:**
- [ ] `engine_start` with an engine that answers runs no command and returns `"started": false`.
- [ ] `engine_start` runs exactly `/usr/bin/open -g "/Applications/Tecopa Plateworks.app"` and returns `"started": true` when `/readyz` answers.
- [ ] `engine_start` fails with kind `environment` when the launcher is not installed, and when the engine never answers.
- [ ] `engine_stop` with the launcher not running and an engine that answers fails with kind `refused`.
- [ ] `engine_stop` reports a denied Automation permission with a hint that names System Settings.
- [ ] Each of the three refuses a port that is not 8848 with kind `usage`.
- [ ] No test and no code path runs `uvicorn`.

**Verify:** `swift test --package-path tools/tecopa --filter LauncherTests` → `Executed 8 tests, with 0 failures`.

**Steps:**

- [ ] **Step 1: Write the failing tests.** `tools/tecopa/Tests/TecopaKitTests/LauncherTests.swift`:

```swift
import XCTest
@testable import TecopaKit

final class LauncherTests: XCTestCase {
    private let open = ["/usr/bin/open", "-g", "/Applications/Tecopa Plateworks.app"]

    /// A machine where `open` starts the engine and `osascript` stops it.
    private func world(running: Bool) -> FakeWorld {
        let w = FakeWorld()
        if running { w.serve("/readyz", 200, FakeWorld.readyBody) }
        w.onRun = { world, command in
            if command.first == "/usr/bin/open" { world.serve("/readyz", 200, FakeWorld.readyBody) }
            if command.first == "/usr/bin/osascript" { world.stopServing() }
        }
        return w
    }

    func testStartOpensTheLauncherAndWaitsForTheEngine() async throws {
        let w = world(running: false)
        let out = try await Launcher.start(w.runtime())
        XCTAssertEqual(w.commands, [open])
        XCTAssertEqual(out["started"], .bool(true))
    }

    func testStartDoesNothingWhenAnEngineAnswers() async throws {
        let w = world(running: true)
        let out = try await Launcher.start(w.runtime())
        XCTAssertEqual(w.commands, [])
        XCTAssertEqual(out["started"], .bool(false))
        XCTAssertEqual(out["running"], .bool(true))
    }

    func testStartFailsWhenTheLauncherIsNotInstalled() async {
        let w = world(running: false)
        var runtime = w.runtime()
        runtime.fileExists = { $0 != Launcher.appPath }
        do {
            _ = try await Launcher.start(runtime)
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .environment)
            XCTAssertTrue(f.hint?.contains("build_app.sh --install") ?? false)
        } catch { XCTFail("\(error)") }
    }

    func testStartFailsWhenTheEngineNeverAnswers() async {
        let w = FakeWorld()          // open succeeds, and nothing ever serves
        do {
            _ = try await Launcher.start(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .environment)
            XCTAssertTrue(f.message.contains("75 seconds"))
        } catch { XCTFail("\(error)") }
    }

    func testStopQuitsTheLauncherAndWaitsForThePortToClose() async throws {
        let w = world(running: true)
        let out = try await Launcher.stop(w.runtime())
        XCTAssertEqual(w.commands.map { $0[0] }, ["/usr/bin/pgrep", "/usr/bin/osascript"])
        XCTAssertEqual(out["stopped"], .bool(true))
    }

    func testStopRefusesAnEngineTheLauncherDoesNotOwn() async {
        // a hand-started engine on 8848: the launcher is not running, so nothing the
        // tool may do can stop it
        let w = world(running: true)
        w.result(for: "pgrep", ProcessResult(exitCode: 1, stdout: "", stderr: ""))
        do {
            _ = try await Launcher.stop(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .refused)
            XCTAssertEqual(w.commands.map { $0[0] }, ["/usr/bin/pgrep"])
        } catch { XCTFail("\(error)") }
    }

    func testStopNamesTheAutomationPermissionWhenMacOSDeniesTheQuit() async {
        let w = FakeWorld()
        w.serve("/readyz", 200, FakeWorld.readyBody)
        w.result(for: "osascript", ProcessResult(
            exitCode: 1, stdout: "",
            stderr: "execution error: Not authorized to send Apple events to Tecopa Plateworks. (-1743)"))
        do {
            _ = try await Launcher.stop(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .environment)
            XCTAssertTrue(f.hint?.contains("Automation") ?? false)
        } catch { XCTFail("\(error)") }
    }

    func testControlRefusesAnyPortExcept8848() async {
        let w = world(running: false)
        for name in ["engine_start", "engine_stop", "engine_restart"] {
            let (_, failure) = await Catalog.call(name, w.runtime(port: 8000), [:])
            XCTAssertEqual(failure?.kind, .usage, name)
        }
        XCTAssertEqual(w.commands, [])
    }
}
```

- [ ] **Step 2: Write `Launcher.swift`**

```swift
import Foundation

/// Engine control. The launcher app owns uvicorn as a child process, so "start" opens
/// the app and "stop" quits it. The tool never starts an engine of its own: two
/// owners of one engine is the fault the launcher spec was written to prevent.
public enum Launcher {
    public static let appPath = "/Applications/Tecopa Plateworks.app"
    public static let port = 8848
    /// Matches the launcher's own process, by its path inside the app bundle.
    static let processPattern = "Tecopa Plateworks.app/Contents/MacOS/TecopaPlateworks"

    enum Serving { case tecopa, foreign, none }

    static func probe(_ runtime: Runtime) async -> Serving {
        guard let reply = try? await runtime.client.raw("/readyz", timeout: 2) else { return .none }
        return (reply.json["ready"] != nil && reply.json["regions"] != nil) ? .tecopa : .foreign
    }

    static func requireLauncherPort(_ runtime: Runtime) throws {
        guard runtime.port == port else {
            throw TecopaFailure(
                .usage, "Engine control applies only to the launcher's engine on port \(port).",
                hint: "Stop a development engine where it was started.")
        }
    }

    public static func start(_ runtime: Runtime) async throws -> JSONValue {
        try requireLauncherPort(runtime)
        switch await probe(runtime) {
        case .tecopa:
            return .object([
                "started": .bool(false), "running": .bool(true),
                "note": .string("An engine already answers on port \(port)."),
            ])
        case .foreign:
            throw TecopaFailure(
                .environment, "Port \(port) answers, but it is not Tecopa Plateworks.",
                hint: "Quit the other program on that port.")
        case .none:
            break
        }
        guard runtime.fileExists(appPath) else {
            throw TecopaFailure(.environment, "The launcher is not installed at \(appPath).",
                                hint: "Run scripts/macos/build_app.sh --install.")
        }
        // -g: the launcher stays in the background. It still opens the studio in the
        // browser when the engine is ready; that is the launcher's own behaviour.
        let opened = try runtime.exec("/usr/bin/open", ["-g", appPath])
        guard opened.exitCode == 0 else {
            throw TecopaFailure(.environment, "macOS could not open the launcher: \(opened.stderr)")
        }
        for _ in 0..<150 {              // 75 seconds: the launcher itself waits 60
            if await probe(runtime) == .tecopa {
                return .object(["started": .bool(true), "running": .bool(true)])
            }
            await runtime.sleep(0.5)
        }
        throw TecopaFailure(
            .environment, "The engine did not answer within 75 seconds.",
            hint: "Run `tecopa logs`. The launcher shows an alert when it cannot start the engine.")
    }

    public static func stop(_ runtime: Runtime) async throws -> JSONValue {
        try requireLauncherPort(runtime)
        let launcherRuns = try runtime.exec("/usr/bin/pgrep", ["-f", processPattern]).exitCode == 0
        guard launcherRuns else {
            if await probe(runtime) != .none {
                throw TecopaFailure(
                    .refused, "An engine answers on port \(port), but the launcher is not running.",
                    hint: "The launcher did not start this engine. Stop it where it was started.")
            }
            return .object([
                "stopped": .bool(false), "running": .bool(false),
                "note": .string("The launcher is not running."),
            ])
        }
        let quit = try runtime.exec("/usr/bin/osascript", ["-e", "quit app \"Tecopa Plateworks\""])
        if quit.exitCode != 0 {
            let text = quit.stderr.lowercased()
            let denied = text.contains("1743") || text.contains("not authoriz") || text.contains("not permitted")
            throw TecopaFailure(
                .environment,
                denied ? "macOS did not allow the quit." : "The quit failed: \(quit.stderr)",
                hint: denied
                    ? "Allow the calling app to control Tecopa Plateworks: System Settings > Privacy & Security > Automation."
                    : nil)
        }
        for _ in 0..<24 {               // 12 seconds: the launcher gives the engine 5, then SIGKILL
            if await probe(runtime) == .none {
                return .object(["stopped": .bool(true), "running": .bool(false)])
            }
            await runtime.sleep(0.5)
        }
        throw TecopaFailure(
            .refused, "The engine still answers on port \(port) after the launcher quit.",
            hint: "The launcher adopted an engine that it did not start. Stop that engine where it was started.")
    }

    public static func restart(_ runtime: Runtime) async throws -> JSONValue {
        let stopped = try await stop(runtime)
        let started = try await start(runtime)
        return .object(["stop": stopped, "start": started])
    }

    static let entries: [CatalogEntry] = [
        CatalogEntry(
            name: "engine_start",
            summary: "Open the launcher app, which starts the engine on port 8848, and wait for it to answer.",
            readOnly: false
        ) { runtime, _ in try await start(runtime) },
        CatalogEntry(
            name: "engine_stop",
            summary: "Quit the launcher app, which stops the engine it started, and wait for the port to close.",
            readOnly: false
        ) { runtime, _ in try await stop(runtime) },
        CatalogEntry(
            name: "engine_restart",
            summary: "Quit and reopen the launcher app. Use after a change to the engine's Python code.",
            readOnly: false
        ) { runtime, _ in try await restart(runtime) },
    ]
}
```

- [ ] **Step 3: Add the entries to the catalog.** In `Catalog.swift`, replace the `all` line:

```swift
    public static let all: [CatalogEntry] =
        EngineEntries.all + Launcher.entries + [LogReader.entry]
```

- [ ] **Step 4: Add the three commands.** In `Commands.swift`, replace the whole `EngineCommand` struct:

```swift
struct EngineCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "engine",
        abstract: "Read or control the launcher's engine.",
        subcommands: [Status.self, Start.self, Stop.self, Restart.self])

    struct Status: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "status", abstract: "Report if the engine answers, and the debug gate.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("engine_status", global) }
    }

    struct Start: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "start", abstract: "Open the launcher app and wait for the engine.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("engine_start", global) }
    }

    struct Stop: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "stop", abstract: "Quit the launcher app and wait for the port to close.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("engine_stop", global) }
    }

    struct Restart: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "restart", abstract: "Quit and reopen the launcher app.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("engine_restart", global) }
    }
}
```

- [ ] **Step 5: Run the tests**

Run: `swift test --package-path tools/tecopa --filter LauncherTests`
Expected: `Executed 8 tests, with 0 failures`.

- [ ] **Step 6: Run against the real launcher.** Task 4 must be done. Port 8848 must be free.

```bash
swift run --package-path tools/tecopa tecopa engine start
swift run --package-path tools/tecopa tecopa engine status | grep -E '"(running|debug)"'
swift run --package-path tools/tecopa tecopa engine stop
pgrep -f "uvicorn app.main:app" || echo "no engine process"
```

Expected: `"started" : true`, then `"debug" : true` and `"running" : true`, then `"stopped" : true`, then `no engine process`.

The first `engine stop` from a new calling app raises the macOS Automation prompt. Dom clicks Allow. This is check 4 of the spec.

- [ ] **Step 7: Commit**

```bash
git add tools/tecopa/Sources tools/tecopa/Tests
git commit -m "tecopa: engine start, stop and restart drive the launcher app, so the engine keeps one owner"
```

---

### Task 10: The script table and `regions verify`

**Goal:** `tecopa regions verify` runs `scripts/verify_regions.py` in `.venv` through a runner that refuses any script with no row in its table.

**Files:**
- Create: `tools/tecopa/Sources/TecopaKit/ScriptRunner.swift`
- Modify: `tools/tecopa/Sources/TecopaKit/Catalog.swift` (the `all` line)
- Modify: `tools/tecopa/Sources/tecopa/Commands.swift` (`RegionsCommand`)
- Create: `tools/tecopa/Tests/TecopaKitTests/ScriptRunnerTests.swift`

**Acceptance Criteria:**
- [ ] `ScriptRunner.run` for `scripts/verify_regions.py` runs `<repo>/.venv/bin/python scripts/verify_regions.py` with the repo as the working folder.
- [ ] A script with no row fails with kind `usage` and runs nothing.
- [ ] A missing interpreter fails with kind `environment`.
- [ ] `regions_verify` returns `"clean": true` for exit 0 and `"clean": false` for exit 1, both as success.
- [ ] `regions_verify` fails with kind `environment` for exit 2.
- [ ] A region id that holds a character outside letters, digits and `_` is a usage failure.

**Verify:** `swift test --package-path tools/tecopa --filter ScriptRunnerTests` → `Executed 6 tests, with 0 failures`.

**Steps:**

- [ ] **Step 1: Write the failing tests.** `tools/tecopa/Tests/TecopaKitTests/ScriptRunnerTests.swift`:

```swift
import XCTest
@testable import TecopaKit

final class ScriptRunnerTests: XCTestCase {
    func testAScriptRunsInItsTableVenvFromTheRepoRoot() throws {
        let w = FakeWorld()
        _ = try ScriptRunner.run("scripts/verify_regions.py", ["lassen_ca"], w.runtime(repo: "/repo"))
        XCTAssertEqual(w.commands, [["/repo/.venv/bin/python", "scripts/verify_regions.py", "lassen_ca"]])
    }

    func testAScriptWithNoRowDoesNotRun() {
        // invariant 13: region_prep.py in .venv would pull the prep stack's pins into
        // the app venv. A script gets a venv only by a row in the table.
        let w = FakeWorld()
        XCTAssertThrowsError(try ScriptRunner.run("region_prep.py", [], w.runtime())) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .usage)
        }
        XCTAssertEqual(w.commands, [])
    }

    func testAMissingInterpreterIsAnEnvironmentFault() {
        let w = FakeWorld()
        var runtime = w.runtime(repo: "/repo")
        runtime.fileExists = { !$0.hasSuffix("/.venv/bin/python") }
        XCTAssertThrowsError(try ScriptRunner.run("scripts/verify_regions.py", [], runtime)) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
        XCTAssertEqual(w.commands, [])
    }

    func testVerifyReportsDriftAsDataAndNotAsAFailure() async {
        // exit 1 means the script found drift. That is the answer, not a fault.
        let w = FakeWorld()
        w.result(for: "python", ProcessResult(exitCode: 1, stdout: "DRIFT  dem.tif", stderr: ""))
        let (env, failure) = await Catalog.call("regions_verify", w.runtime(), [:])
        XCTAssertNil(failure)
        XCTAssertEqual(env["data"]?["clean"], .bool(false))
        XCTAssertEqual(env["data"]?["output"]?.stringValue, "DRIFT  dem.tif")
    }

    func testVerifyFailsWhenTheScriptCannotRun() async {
        let w = FakeWorld()
        w.result(for: "python", ProcessResult(exitCode: 2, stdout: "", stderr: "no regions root"))
        let (_, failure) = await Catalog.call("regions_verify", w.runtime(), [:])
        XCTAssertEqual(failure?.kind, .environment)
    }

    func testVerifyRefusesARegionIdThatIsNotAnId() async {
        let w = FakeWorld()
        let (_, failure) = await Catalog.call(
            "regions_verify", w.runtime(), ["regions": .array([.string("--regions-root=/tmp")])])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertEqual(w.commands, [])
    }
}
```

- [ ] **Step 2: Write `ScriptRunner.swift`**

```swift
import Foundation

/// Runs the repo's Python scripts. The table is an allowlist and the one place that
/// decides a script's venv (CLAUDE.md, invariant 13: the region-prep stack never
/// enters .venv). A script with no row does not run, and no flag overrides the table.
public enum ScriptRunner {
    public enum Venv: String, Sendable {
        case app = ".venv"
        case prep = ".venv-prep"
    }

    /// Add a row in the same change as the command that needs it.
    public static let table: [String: Venv] = [
        "scripts/verify_regions.py": .app,
    ]

    public static func run(_ script: String, _ arguments: [String],
                           _ runtime: Runtime) throws -> ProcessResult {
        guard let venv = table[script] else {
            throw TecopaFailure(
                .usage, "\(script) has no row in the script table.",
                hint: "Add a row to ScriptRunner.table in the same change as the command.")
        }
        let repo = try runtime.repo()
        let python = repo + "/" + venv.rawValue + "/bin/python"
        guard runtime.fileExists(python) else {
            throw TecopaFailure(.environment, "No interpreter at \(python).",
                                hint: "Read docs/changing-things.md, Set up a machine.")
        }
        return try runtime.exec(python, [script] + arguments, cwd: repo)
    }

    static let verifyEntry = CatalogEntry(
        name: "regions_verify",
        summary: "Check each plate's assets against its sources.json, and its DEM geometry. Reads only.",
        readOnly: true,
        parameters: [
            EntryParameter("regions", .stringArray, "Region ids to check. Without it, every plate is checked."),
        ],
        text: { data in data["output"]?.stringValue ?? "" }
    ) { runtime, arguments in
        let ids = (arguments["regions"]?.arrayValue ?? []).compactMap { $0.stringValue }
        for id in ids {
            // an id is a folder name under regions/; anything else could be read as a flag
            guard !id.isEmpty, id.allSatisfy({ $0.isLetter || $0.isNumber || $0 == "_" }) else {
                throw TecopaFailure(.usage, "Not a region id: \(id)")
            }
        }
        let result = try run("scripts/verify_regions.py", ids, runtime)
        // 0: every asset matches. 1: the script found drift, which is the answer.
        // Anything else: the script could not do its work.
        guard result.exitCode == 0 || result.exitCode == 1 else {
            throw TecopaFailure(
                .environment, "verify_regions.py exited \(result.exitCode): \(result.stderr)")
        }
        return .object([
            "clean": .bool(result.exitCode == 0),
            "exit_code": .int(Int64(result.exitCode)),
            "output": .string(result.stdout.trimmingCharacters(in: .whitespacesAndNewlines)),
        ])
    }
}
```

- [ ] **Step 3: Add the entry to the catalog.** In `Catalog.swift`, replace the `all` line:

```swift
    public static let all: [CatalogEntry] =
        EngineEntries.all + Launcher.entries + [LogReader.entry, ScriptRunner.verifyEntry]
```

- [ ] **Step 4: Add the command.** In `Commands.swift`, replace the whole `RegionsCommand` struct:

```swift
struct RegionsCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "regions",
        abstract: "List the plates, or check them against sources.json.",
        subcommands: [List.self, Verify.self],
        defaultSubcommand: List.self)

    struct List: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "list", abstract: "List the plates with the readiness report.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("regions", global) }
    }

    struct Verify: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "verify", abstract: "Run scripts/verify_regions.py.")
        @OptionGroup var global: GlobalOptions
        @Argument(help: "Region ids to check. Without one, every plate is checked.")
        var regions: [String] = []

        func run() async throws {
            let ids = regions.map { JSONValue.string($0) }
            try await execute("regions_verify", global, ids.isEmpty ? [:] : ["regions": .array(ids)])
        }
    }
}
```

- [ ] **Step 5: Run the tests and the real script**

Run: `swift test --package-path tools/tecopa --filter ScriptRunnerTests`
Expected: `Executed 6 tests, with 0 failures`.
Run: `swift run --package-path tools/tecopa tecopa --repo "$(git rev-parse --show-toplevel)" regions verify lassen_ca`
Expected: the same text as `.venv/bin/python scripts/verify_regions.py lassen_ca`, and exit 0.

- [ ] **Step 6: Commit**

```bash
git add tools/tecopa/Sources tools/tecopa/Tests
git commit -m "tecopa: regions verify runs through a script table, so no command can run a prep script in the app venv"
```

---

### Task 11: `doctor`

**Goal:** `tecopa doctor` checks the repo, both venvs, the launcher's baked path, the port, the gate and the log with no engine, and names the cause of a fault.

**Files:**
- Create: `tools/tecopa/Sources/TecopaKit/Doctor.swift`
- Modify: `tools/tecopa/Sources/TecopaKit/Catalog.swift` (the `all` line)
- Modify: `tools/tecopa/Sources/tecopa/Commands.swift`
- Modify: `tools/tecopa/Sources/tecopa/Tecopa.swift`
- Create: `tools/tecopa/Tests/TecopaKitTests/DoctorTests.swift`

**Acceptance Criteria:**
- [ ] With no engine, the `engine` check is `warn` and `fail_count` is 0.
- [ ] A launcher built for another path gives a `launcher` check of `fail` that names both paths.
- [ ] A missing `.venv` interpreter gives a `venv` check of `fail`.
- [ ] An engine that answers with `"ready": false` gives an `engine` check of `fail` that names the plate.
- [ ] `doctor` never throws: a missing repo is a `fail` row, and the later checks still run.
- [ ] `tecopa doctor` exits 4 when `fail_count` is above 0, and 0 when it is 0.

**Verify:** `swift test --package-path tools/tecopa --filter DoctorTests` → `Executed 6 tests, with 0 failures`.

**Steps:**

- [ ] **Step 1: Write the failing tests.** `tools/tecopa/Tests/TecopaKitTests/DoctorTests.swift`:

```swift
import XCTest
@testable import TecopaKit

final class DoctorTests: XCTestCase {
    private func check(_ report: JSONValue, _ name: String) -> JSONValue? {
        (report["checks"]?.arrayValue ?? []).first { $0["name"]?.stringValue == name }
    }

    /// A healthy machine with a stopped engine: PlistBuddy reports the repo path and
    /// python reports its version.
    private func healthy() -> FakeWorld {
        let w = FakeWorld()
        w.result(for: "PlistBuddy", ProcessResult(exitCode: 0, stdout: "/repo\n", stderr: ""))
        w.result(for: "python", ProcessResult(exitCode: 0, stdout: "Python 3.14.2\n", stderr: ""))
        return w
    }

    func testAStoppedEngineIsAWarningAndNotAFailure() async {
        let report = await Doctor.run(healthy().runtime(repo: "/repo"))
        XCTAssertEqual(check(report, "engine")?["status"]?.stringValue, "warn")
        XCTAssertEqual(check(report, "repo")?["status"]?.stringValue, "ok")
        XCTAssertEqual(check(report, "venv")?["status"]?.stringValue, "ok")
        XCTAssertEqual(check(report, "launcher")?["status"]?.stringValue, "ok")
        XCTAssertEqual(report["fail_count"]?.intValue, 0)
    }

    func testALauncherBuiltForAnotherPathFailsAndNamesBothPaths() async {
        // the real fault this plan found: the app in /Applications was built before
        // the repo moved, so it can only show an alert
        let w = healthy()
        w.result(for: "PlistBuddy", ProcessResult(exitCode: 0, stdout: "/old/place\n", stderr: ""))
        let report = await Doctor.run(w.runtime(repo: "/repo"))
        let row = check(report, "launcher")
        XCTAssertEqual(row?["status"]?.stringValue, "fail")
        XCTAssertTrue(row?["detail"]?.stringValue?.contains("/old/place") ?? false)
        XCTAssertTrue(row?["detail"]?.stringValue?.contains("/repo") ?? false)
        XCTAssertTrue(row?["hint"]?.stringValue?.contains("build_app.sh --install") ?? false)
        XCTAssertEqual(report["fail_count"]?.intValue, 1)
    }

    func testAMissingVenvFails() async {
        var runtime = healthy().runtime(repo: "/repo")
        runtime.fileExists = { !$0.hasSuffix("/.venv/bin/python") }
        let report = await Doctor.run(runtime)
        XCTAssertEqual(check(report, "venv")?["status"]?.stringValue, "fail")
    }

    func testAnEngineThatIsNotReadyFailsAndNamesThePlate() async {
        let w = healthy()
        w.serve("/readyz", 503, #"{"ready":false,"regions":[{"id":"lassen_ca","ready":false},{"id":"rifle_aspen","ready":true}]}"#)
        w.serve("/api/debug/engine", 200, #"{"engine":"tecopa-plateworks"}"#)
        let report = await Doctor.run(w.runtime(repo: "/repo"))
        let row = check(report, "engine")
        XCTAssertEqual(row?["status"]?.stringValue, "fail")
        XCTAssertTrue(row?["detail"]?.stringValue?.contains("lassen_ca") ?? false)
        XCTAssertFalse(row?["detail"]?.stringValue?.contains("rifle_aspen") ?? true)
        XCTAssertEqual(check(report, "debug_gate")?["status"]?.stringValue, "ok")
    }

    func testAClosedGateIsAWarning() async {
        let w = healthy()
        w.serve("/readyz", 200, FakeWorld.readyBody)
        w.serve("/api/debug/engine", 404, #"{"detail":"Not Found"}"#)
        let report = await Doctor.run(w.runtime(repo: "/repo"))
        XCTAssertEqual(check(report, "engine")?["status"]?.stringValue, "ok")
        XCTAssertEqual(check(report, "debug_gate")?["status"]?.stringValue, "warn")
    }

    func testAMissingRepoIsARowAndTheLaterChecksStillRun() async {
        var runtime = healthy().runtime(repo: nil)
        runtime.fileExists = { $0 == Launcher.appPath }
        let report = await Doctor.run(runtime)
        XCTAssertEqual(check(report, "repo")?["status"]?.stringValue, "fail")
        XCTAssertNotNil(check(report, "engine"))
        XCTAssertNotNil(check(report, "log"))
    }
}
```

- [ ] **Step 2: Write `Doctor.swift`**

```swift
import Foundation

/// The checks that need no engine. `doctor` is the command for the worst case: the
/// engine does not start and nothing else can say why. It never throws, and one
/// failed check never stops the others.
public enum Doctor {
    static func row(_ name: String, _ status: String, _ detail: String,
                    hint: String? = nil, extra: [String: JSONValue] = [:]) -> JSONValue {
        var out: [String: JSONValue] = [
            "name": .string(name), "status": .string(status), "detail": .string(detail)]
        if let hint { out["hint"] = .string(hint) }
        for (key, value) in extra { out[key] = value }
        return .object(out)
    }

    static func trimmed(_ text: String) -> String {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func venvRows(_ runtime: Runtime, repo: String) -> [JSONValue] {
        var rows: [JSONValue] = []
        let python = repo + "/.venv/bin/python"
        if !runtime.fileExists(python) {
            rows.append(row("venv", "fail", "No interpreter at \(python).",
                            hint: "Read docs/changing-things.md, Set up a machine."))
        } else if let version = try? runtime.exec(python, ["--version"], cwd: repo), version.exitCode == 0 {
            let found = trimmed(version.stdout)             // "Python 3.14.2"
            let wanted = trimmed((try? String(contentsOfFile: repo + "/.python-version", encoding: .utf8)) ?? "")
            if !wanted.isEmpty, !found.contains(" " + wanted) {
                rows.append(row("venv", "warn", "\(found), and .python-version asks for \(wanted)."))
            } else {
                rows.append(row("venv", "ok", found))
            }
        } else {
            rows.append(row("venv", "fail", "The interpreter at \(python) does not run.",
                            hint: "Read docs/changing-things.md, Set up a machine."))
        }

        let prep = repo + "/.venv-prep/bin/python"
        rows.append(runtime.fileExists(prep)
            ? row("venv_prep", "ok", prep)
            : row("venv_prep", "warn", "No interpreter at \(prep). Plate builds are not available.",
                  hint: "Read docs/changing-things.md, Set up a machine."))
        return rows
    }

    static func launcherRow(_ runtime: Runtime, repo: String?) -> JSONValue {
        guard runtime.fileExists(Launcher.appPath) else {
            return row("launcher", "warn", "The launcher is not installed at \(Launcher.appPath).",
                       hint: "Run scripts/macos/build_app.sh --install.")
        }
        let plist = Launcher.appPath + "/Contents/Info.plist"
        let read = try? runtime.exec("/usr/libexec/PlistBuddy", ["-c", "Print :TecopaRepoPath", plist])
        let built = trimmed(read?.stdout ?? "")
        guard read?.exitCode == 0, !built.isEmpty else {
            return row("launcher", "fail", "The launcher holds no repository path.",
                       hint: "Run scripts/macos/build_app.sh --install.")
        }
        if let repo, built != repo {
            return row("launcher", "fail",
                       "The launcher was built for \(built). The repository is at \(repo).",
                       hint: "Run scripts/macos/build_app.sh --install.")
        }
        return row("launcher", "ok", "Built for \(built).")
    }

    static func engineRows(_ runtime: Runtime) async -> [JSONValue] {
        guard let reply = try? await runtime.client.raw("/readyz", timeout: 3) else {
            return [row("engine", "warn", "No engine answers on port \(runtime.port).",
                        hint: "Run `tecopa engine start`.")]
        }
        guard let ready = reply.json["ready"]?.boolValue,
              let plates = reply.json["regions"]?.arrayValue else {
            return [row("engine", "fail", "Port \(runtime.port) answers, but it is not Tecopa Plateworks.",
                        hint: "Quit the other program on that port.")]
        }
        var rows: [JSONValue] = []
        if ready {
            rows.append(row("engine", "ok", "Ready on port \(runtime.port), \(plates.count) plates."))
        } else {
            let bad = plates.filter { $0["ready"]?.boolValue != true }
                .compactMap { $0["id"]?.stringValue }
            rows.append(row(
                "engine", "fail",
                "The engine answers, and these plates cannot render: \(bad.joined(separator: ", ")).",
                hint: "Run `tecopa regions verify`. Then read docs/changing-things.md, Repair an orphaned DEM."))
        }
        if (try? await runtime.client.debug("/engine")) != nil {
            rows.append(row("debug_gate", "ok", "The debug routes are on."))
        } else {
            rows.append(row("debug_gate", "warn", "The debug routes are off.",
                            hint: "Start the engine with TECOPA_DEBUG=1. The launcher sets it."))
        }
        return rows
    }

    static func logRow(_ runtime: Runtime) -> JSONValue {
        let tail = LogReader.read(path: runtime.logPath, lines: 15, grep: nil, since: nil)
        guard tail["exists"]?.boolValue == true else {
            return row("log", "warn", "No log at \(runtime.logPath). The launcher has not run on this Mac.")
        }
        return row("log", "ok", runtime.logPath, extra: ["lines": tail["lines"] ?? .array([])])
    }

    public static func run(_ runtime: Runtime) async -> JSONValue {
        var rows: [JSONValue] = []
        var repo: String?
        do {
            let found = try runtime.repo()
            repo = found
            rows.append(row("repo", "ok", found))
        } catch let failure as TecopaFailure {
            rows.append(row("repo", "fail", failure.message, hint: failure.hint))
        } catch {
            rows.append(row("repo", "fail", "\(error)"))
        }
        if let repo { rows += venvRows(runtime, repo: repo) }
        rows.append(launcherRow(runtime, repo: repo))
        rows += await engineRows(runtime)
        rows.append(logRow(runtime))

        func count(_ status: String) -> JSONValue {
            .int(Int64(rows.filter { $0["status"]?.stringValue == status }.count))
        }
        return .object([
            "checks": .array(rows),
            "ok_count": count("ok"), "warn_count": count("warn"), "fail_count": count("fail"),
        ])
    }

    static func render(_ report: JSONValue) -> String {
        var lines: [String] = []
        for check in report["checks"]?.arrayValue ?? [] {
            let status = (check["status"]?.stringValue ?? "?").padding(toLength: 5, withPad: " ", startingAt: 0)
            let name = (check["name"]?.stringValue ?? "?").padding(toLength: 11, withPad: " ", startingAt: 0)
            lines.append("\(status) \(name) \(check["detail"]?.stringValue ?? "")")
            if let hint = check["hint"]?.stringValue { lines.append("      hint: \(hint)") }
            if check["name"]?.stringValue == "log" {
                for line in check["lines"]?.arrayValue ?? [] {
                    lines.append("      | \(line.stringValue ?? "")")
                }
            }
        }
        return lines.joined(separator: "\n")
    }

    static let entry = CatalogEntry(
        name: "doctor",
        summary: "Check the repo, both venvs, the launcher, the port, the debug gate and the log. Works with no engine.",
        readOnly: true,
        text: { render($0) }
    ) { runtime, _ in await run(runtime) }
}
```

- [ ] **Step 3: Add the entry to the catalog.** In `Catalog.swift`, replace the `all` line:

```swift
    public static let all: [CatalogEntry] =
        [Doctor.entry] + EngineEntries.all + Launcher.entries
        + [LogReader.entry, ScriptRunner.verifyEntry]
```

- [ ] **Step 4: Add the command.** Append to `Commands.swift`:

```swift
struct DoctorCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "doctor",
        abstract: "Check the repo, the venvs, the launcher, the port and the log. Works with no engine.")
    @OptionGroup var global: GlobalOptions

    func run() async throws {
        let report = try await execute("doctor", global)
        // a failed check is an environment fault; warnings alone exit 0
        if (report["fail_count"]?.intValue ?? 0) > 0 { throw ExitCode(4) }
    }
}
```

In `Tecopa.swift`, replace the `subcommands` list:

```swift
        subcommands: [
            DoctorCommand.self, EngineCommand.self, LogsCommand.self, RegionsCommand.self,
            JobsCommand.self, SessionsCommand.self, CachesCommand.self,
        ])
```

- [ ] **Step 5: Run the tests and the binary**

Run: `swift test --package-path tools/tecopa --filter DoctorTests`
Expected: `Executed 6 tests, with 0 failures`.
Run: `swift run --package-path tools/tecopa tecopa --repo "$(git rev-parse --show-toplevel)" doctor; echo "exit $?"`
Expected, with the engine stopped and Task 4 done: `ok` rows for repo, venv, venv_prep and launcher, a `warn` row for engine, an `ok` row for log, then `exit 0`.

- [ ] **Step 6: Commit**

```bash
git add tools/tecopa/Sources tools/tecopa/Tests
git commit -m "tecopa: doctor names the cause when the engine cannot start, with no engine needed"
```

---

### Task 12: The MCP server

**Goal:** `tecopa mcp` serves every catalog entry as an MCP tool over stdio, with the read-only annotation and the same envelope as `--json`.

**Files:**
- Create: `tools/tecopa/Sources/tecopa/MCPServer.swift`
- Modify: `tools/tecopa/Sources/tecopa/Tecopa.swift`
- Create: `tools/tecopa/Tests/TecopaKitTests/MCPServerTests.swift`

**Acceptance Criteria:**
- [ ] `tools/list` returns exactly these 11 names: `doctor`, `engine_status`, `engine_start`, `engine_stop`, `engine_restart`, `logs`, `regions`, `regions_verify`, `jobs`, `sessions`, `caches`.
- [ ] `engine_start`, `engine_stop` and `engine_restart` have `readOnlyHint` false. The other 8 have it true.
- [ ] Each tool name maps to a CLI command that answers `--help` with exit 0.
- [ ] A `tools/call` of `jobs` against a stopped engine returns the failure envelope with `isError` true.
- [ ] Nothing except protocol lines reaches stdout.

**Verify:** `swift test --package-path tools/tecopa --filter MCPServerTests` → `Executed 3 tests, with 0 failures`.

**Steps:**

- [ ] **Step 1: Use the names Task 1 recorded.** Read "Task 1 result" at the end of this plan. If Task 1 recorded a different SDK name for `annotations:`, `readOnlyHint`, `waitUntilCompleted` or `params.arguments`, use the recorded name in Step 3.

- [ ] **Step 2: Write the failing tests.** `tools/tecopa/Tests/TecopaKitTests/MCPServerTests.swift`:

```swift
import XCTest
@testable import TecopaKit

/// These tests start the built binary and speak the protocol as raw lines, so they
/// test what a real client sees and depend on no client library.
final class MCPServerTests: XCTestCase {
    private let readOnly: Set<String> = [
        "doctor", "engine_status", "logs", "regions", "regions_verify", "jobs", "sessions", "caches"]
    private let control: Set<String> = ["engine_start", "engine_stop", "engine_restart"]

    private var binary: URL {
        // the test bundle sits beside the products of the same build
        Bundle(for: MCPServerTests.self).bundleURL
            .deletingLastPathComponent().appendingPathComponent("tecopa")
    }

    private func converse(_ requests: [String], arguments: [String] = ["mcp"]) throws -> [JSONValue] {
        let process = Process()
        process.executableURL = binary
        process.arguments = arguments
        let input = Pipe()
        let output = Pipe()
        process.standardInput = input
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        try process.run()
        let lines = [
            #"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}"#,
            #"{"jsonrpc":"2.0","method":"notifications/initialized"}"#,
        ] + requests
        input.fileHandleForWriting.write(Data((lines.joined(separator: "\n") + "\n").utf8))
        Thread.sleep(forTimeInterval: 4)          // jobs waits on a refused connection
        try input.fileHandleForWriting.close()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        return String(decoding: data, as: UTF8.self)
            .split(separator: "\n")
            .compactMap { try? JSONValue.parse(Data($0.utf8)) }
    }

    private func reply(_ replies: [JSONValue], id: Int) -> JSONValue? {
        replies.first { $0["id"]?.intValue == id }
    }

    func testToolsListIsTheCatalogWithTheCorrectAnnotation() throws {
        let replies = try converse([#"{"jsonrpc":"2.0","id":2,"method":"tools/list"}"#])
        let tools = reply(replies, id: 2)?["result"]?["tools"]?.arrayValue ?? []
        let names = Set(tools.compactMap { $0["name"]?.stringValue })
        XCTAssertEqual(names, readOnly.union(control))
        XCTAssertEqual(names, Set(Catalog.all.map { $0.name }))
        for tool in tools {
            let name = tool["name"]?.stringValue ?? ""
            XCTAssertEqual(tool["annotations"]?["readOnlyHint"]?.boolValue, readOnly.contains(name), name)
            XCTAssertEqual(tool["inputSchema"]?["type"]?.stringValue, "object", name)
        }
    }

    func testEveryToolHasACommandOfTheSameWords() throws {
        for entry in Catalog.all {
            let process = Process()
            process.executableURL = binary
            process.arguments = entry.name.split(separator: "_").map(String.init) + ["--help"]
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            try process.run()
            process.waitUntilExit()
            XCTAssertEqual(process.terminationStatus, 0, "tecopa \(entry.name) --help")
        }
    }

    func testAFailedCallReturnsTheEnvelopeWithTheErrorFlag() throws {
        // port 9 answers nothing, so the engine is unreachable whatever runs on 8848
        let call = #"{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"jobs","arguments":{"port":9}}}"#
        let replies = try converse([call])
        let result = reply(replies, id: 3)?["result"]
        XCTAssertEqual(result?["isError"], .bool(true))
        let text = result?["content"]?.arrayValue?.first?["text"]?.stringValue ?? ""
        let envelope = try JSONValue.parse(Data(text.utf8))
        XCTAssertEqual(envelope["ok"], .bool(false))
        XCTAssertEqual(envelope["error"]?["kind"]?.stringValue, "engine_unreachable")
    }
}
```

`regions_verify` maps to the CLI words `regions verify`, and `engine_status` to `engine status`, so the split on `_` is the whole mapping.

- [ ] **Step 3: Write `MCPServer.swift`**

```swift
import ArgumentParser
import Foundation
import MCP
import TecopaKit

/// The catalog over stdio. This file holds no operation: it turns a CatalogEntry into
/// a Tool and a tool call into Catalog.call, the same call the CLI makes.
enum MCPBridge {
    static func schema(for entry: CatalogEntry) -> Value {
        var properties: [String: Value] = [
            // every tool can address a development engine
            "port": .object([
                "type": .string("integer"),
                "description": .string("The engine port. Default 8848, the launcher's engine."),
            ])
        ]
        for parameter in entry.parameters {
            var property: [String: Value] = ["description": .string(parameter.summary)]
            switch parameter.kind {
            case .string: property["type"] = .string("string")
            case .integer: property["type"] = .string("integer")
            case .boolean: property["type"] = .string("boolean")
            case .stringArray:
                property["type"] = .string("array")
                property["items"] = .object(["type": .string("string")])
            }
            properties[parameter.name] = .object(property)
        }
        return .object(["type": .string("object"), "properties": .object(properties)])
    }

    /// An MCP Value as the tool's own JSON type, through its Codable form.
    static func convert(_ value: Value) -> JSONValue {
        guard let data = try? JSONEncoder().encode(value),
              let json = try? JSONValue.parse(data) else { return .null }
        return json
    }

    static func serve() async throws {
        let server = Server(
            name: "tecopa", version: bakedVersion,
            capabilities: .init(tools: .init(listChanged: false)))

        await server.withMethodHandler(ListTools.self) { _ in
            .init(tools: Catalog.all.map { entry in
                Tool(name: entry.name, description: entry.summary,
                     inputSchema: schema(for: entry),
                     annotations: .init(readOnlyHint: entry.readOnly))
            })
        }

        await server.withMethodHandler(CallTool.self) { params in
            var arguments: [String: JSONValue] = [:]
            for (key, value) in params.arguments ?? [:] { arguments[key] = convert(value) }
            let port = arguments.removeValue(forKey: "port")?.intValue ?? 8848
            let (result, failure) = await Catalog.call(params.name, Runtime(port: port), arguments)
            return .init(content: [.text(result.text(pretty: false))], isError: failure != nil)
        }

        try await server.start(transport: StdioTransport())
        await server.waitUntilCompleted()
    }
}

struct MCPCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "mcp",
        abstract: "Serve every command as an MCP tool on stdio.")

    func run() async throws { try await MCPBridge.serve() }
}
```

- [ ] **Step 4: List the command.** In `Tecopa.swift`, replace the `subcommands` list:

```swift
        subcommands: [
            DoctorCommand.self, EngineCommand.self, LogsCommand.self, RegionsCommand.self,
            JobsCommand.self, SessionsCommand.self, CachesCommand.self, MCPCommand.self,
        ])
```

- [ ] **Step 5: Run the tests**

Run: `swift test --package-path tools/tecopa --filter MCPServerTests`
Expected: `Executed 3 tests, with 0 failures`.

If `testEveryToolHasACommandOfTheSameWords` fails for `regions`, the default subcommand took `--help`. That is correct behaviour and exits 0, so a failure there means the command list is wrong, not the test.

- [ ] **Step 6: Run every Swift test, then commit**

Run: `swift test --package-path tools/tecopa`
Expected: `Executed 50 tests, with 0 failures`.

```bash
git add tools/tecopa/Sources tools/tecopa/Tests
git commit -m "tecopa: mcp serves the catalog over stdio, so Claude gets each command as a tool with no shell"
```

---

### Task 13: Install, the smoke test, registration, and the phase proof

**Goal:** The installed binary passes an end-to-end run against the real launcher, and Claude Code has the `tecopa` MCP server at user scope.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Create: `tools/tecopa/smoke_test.sh`

**Acceptance Criteria:**
- [ ] `~/.local/bin/tecopa --version` prints the `git describe` text of the build.
- [ ] `tools/tecopa/smoke_test.sh` prints `PASS: phase 1 proof` and exits 0.
- [ ] With the engine stopped, `tecopa doctor` reports the `engine` check as `warn` with the text `No engine answers on port 8848`.
- [ ] With the engine running, a raw `tools/call` of `jobs` through `tecopa mcp` returns an envelope with `"ok":true`.
- [ ] `claude mcp list` shows a `tecopa` row.
- [ ] After the smoke test, port 8848 does not answer.

**Verify:** `tools/tecopa/smoke_test.sh` → `PASS: phase 1 proof`.

**Steps:**

- [ ] **Step 1: Write `tools/tecopa/smoke_test.sh`**

```bash
#!/usr/bin/env bash
# The phase 1 proof: build, install, then drive the real launcher end to end.
# With the engine stopped, doctor names the state. With it running, the jobs tool
# answers through MCP. Requires port 8848 to be free, and a human for the one-time
# macOS Automation prompt on the first quit.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TECOPA="$HOME/.local/bin/tecopa"
READY="http://127.0.0.1:8848/readyz"

fail() { echo "FAIL: $*" >&2; exit 1; }
serving() { curl -s -o /dev/null --max-time 1 "$READY"; }

# 0. The port must be free: the test must own the engine that it stops.
if serving; then fail "port 8848 already answers. Quit that engine first."; fi

# 1. Build and install
"$SCRIPT_DIR/build.sh" --install
[[ -x "$TECOPA" ]] || fail "build did not install $TECOPA"
echo "  build + install: OK ($("$TECOPA" --version))"

# 2. Stopped engine: doctor names the state, and the check is a warning
DOCTOR="$("$TECOPA" doctor --json || true)"
echo "$DOCTOR" | grep -q "No engine answers on port 8848" \
  || fail "doctor did not report the stopped engine"
echo "$DOCTOR" | grep -q '"fail_count" : 0' \
  || fail "doctor reports a failed check. Run: tecopa doctor"
echo "  doctor with the engine stopped: OK"

# 3. Start through the launcher
"$TECOPA" engine start --json | grep -q '"started" : true' || fail "engine start did not start the engine"
"$TECOPA" engine status --json | grep -q '"debug" : true' \
  || fail "the debug gate is off. Rebuild the launcher: scripts/macos/build_app.sh --install"
echo "  engine start + debug gate: OK"

# 4. The CLI reads the debug routes
"$TECOPA" jobs --json | grep -q '"ok" : true' || fail "tecopa jobs failed"
"$TECOPA" sessions --json | grep -q '"ok" : true' || fail "tecopa sessions failed"
"$TECOPA" caches --json | grep -q '"ok" : true' || fail "tecopa caches failed"
"$TECOPA" regions --json | grep -q '"ok" : true' || fail "tecopa regions failed"
echo "  jobs, sessions, caches, regions: OK"

# 5. The same jobs call through MCP, as a client sends it
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
NOTE='{"jsonrpc":"2.0","method":"notifications/initialized"}'
CALL='{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"jobs","arguments":{}}}'
REPLY="$( ( printf '%s\n' "$INIT" "$NOTE" "$CALL"; sleep 3 ) | "$TECOPA" mcp )"
echo "$REPLY" | grep '"id":2' | grep -q '\\"ok\\":true' || fail "the MCP jobs tool did not answer ok"
echo "  MCP jobs tool: OK"

# 6. Stop through the launcher, and the port closes
"$TECOPA" engine stop --json | grep -q '"stopped" : true' || fail "engine stop did not stop the engine"
if serving; then fail "port 8848 still answers after engine stop"; fi
echo "  engine stop: OK"

echo "PASS: phase 1 proof"
```

- [ ] **Step 2: Run it**

Run: `chmod +x tools/tecopa/smoke_test.sh && tools/tecopa/smoke_test.sh`
Expected: six `OK` lines, then `PASS: phase 1 proof`.

The first quit from a new calling app raises the Automation prompt. Dom clicks Allow, then the run repeats.

- [ ] **Step 3: Commit the script**

```bash
git add tools/tecopa/smoke_test.sh
git commit -m "tecopa: a smoke test that is the phase 1 proof, from a stopped engine to an MCP jobs call"
```

- [ ] **Step 4: Ask Dom, then register the server in Claude Code.** This changes his Claude configuration for every session on this Mac. State the command and wait for his yes.

Run: `claude mcp add --scope user tecopa -- "$HOME/.local/bin/tecopa" mcp`
Run: `claude mcp list`
Expected: a row that starts `tecopa:` and names `/Users/dom/.local/bin/tecopa mcp`.

- [ ] **Step 5: Give Dom the two checks that need a new session.** Write them in the end-of-session report:

1. In a new Claude Code session, ask Claude to list the Tecopa jobs. Claude must call the `jobs` tool, not Bash.
2. The Claude desktop app is not registered yet. Its file grant for `~/Documents` is not tested (spec check 2). Register it there only after one manual run of `tecopa doctor` from that app's tool succeeds.

---

### Task 14: Documents, the full suite, and the push

**Goal:** The repo's documents describe the tool and the debug routes, the docs test passes, the full suite matches `main`, and `main` is pushed.

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/changing-things.md`
- Modify: `docs/decisions.md`
- Modify: `docs/README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md`

**Acceptance Criteria:**
- [ ] `docs/architecture.md` has module map rows for `app/debug.py` and the Swift package, and environment rows for `TECOPA_DEBUG` and `TECOPA_REPO`.
- [ ] `docs/changing-things.md` has the sections "Build the tecopa tool" and "Add a tecopa command".
- [ ] `CLAUDE.md` routes a change to the tool to the spec, and stays under 2,000 tokens.
- [ ] The `docs/README.md` row for this plan says phase 1 is built.
- [ ] The spec's status line says phase 1 is built, and its exit-code table has the row for 64.
- [ ] `.venv/bin/python -m pytest tests/test_docs.py -q` passes.
- [ ] The full suite has the same failure set as `main` before Task 2.

**Verify:** `.venv/bin/python -m pytest tests/test_docs.py -q` → `1 passed`. Then `.venv/bin/python -m pytest -n auto -q` → the same failure set as the baseline.

**Steps:**

- [ ] **Step 1: `docs/architecture.md`, the module map.** Add this row directly after the `app/logconfig.py` row:

```markdown
| `app/debug.py` | The read-only debug routes under `/api/debug/`: engine, jobs, sessions, caches. `enabled()` is the `TECOPA_DEBUG` gate. `build_router` takes the queues and caches as arguments, so it never imports `app/main.py`. | `tests/test_debug.py` |
```

Add this row directly after the `scripts/macos/build_app.sh` row:

```markdown
| `tools/tecopa/` | The `tecopa` tool: one Swift binary that is a command line and an MCP server. `tools/tecopa/Sources/TecopaKit/Catalog.swift` lists every operation once, and the CLI and `tecopa mcp` both call it. `ScriptRunner.swift` holds the script table that decides a script's venv. | `swift test --package-path tools/tecopa`, Mac only. `tools/tecopa/smoke_test.sh` is the manual end-to-end check. |
```

- [ ] **Step 2: `docs/architecture.md`, the rest.** In "Runtime behavior worth knowing", add this bullet after the "Auto-docs are off" bullet:

```markdown
- **The debug routes are gated.** `/api/debug/*` exists only under `TECOPA_DEBUG=1`, which the macOS launcher sets. With the gate off `app/main.py` never includes the router, so each path is a plain 404. Every debug route reads and none changes a session, a job, a cache or a plate.
```

In the Environment table, add these two rows after the `TECOPA_LOG_LEVEL` row:

```markdown
| `TECOPA_DEBUG` | `app/debug.py`, `app/main.py` | `1` includes the read-only debug routes. Any other value, and unset, leaves them out. The launcher sets it. `tests/conftest.py` removes it. |
| `TECOPA_REPO` | `tools/tecopa/Sources/TecopaKit/RepoLocator.swift` | The repo path for the `tecopa` tool, after `--repo` and before the path baked at build time. |
```

In the Delivery table, add this row after "The studio":

```markdown
| The `tecopa` tool | `tools/tecopa/build.sh --install` builds the release binary and copies it to `~/.local/bin/tecopa`, with this repo's path baked in. Registered in Claude Code at user scope as the MCP server `tecopa`. Rebuild after the repo moves or the Swift code changes. |
```

In "The verification harness", add this bullet after the `scripts/macos/smoke_test.sh` bullet:

```markdown
- `swift test --package-path tools/tecopa` runs the tool's tests with no engine and no network. `tools/tecopa/smoke_test.sh` drives the real launcher and needs port 8848 free. Neither runs in CI.
```

- [ ] **Step 3: `docs/changing-things.md`.** Add these two sections directly after "Rebuild the macOS launcher":

```markdown
## Build the tecopa tool

Only when the repo moves or the Swift code under `tools/tecopa/` changes.

1. `swift test --package-path tools/tecopa` must pass. It needs no engine.
2. `tools/tecopa/build.sh --install` builds the release binary and copies it to
   `~/.local/bin/tecopa`. It bakes this repo's path into the binary.
3. `tools/tecopa/smoke_test.sh` is the end-to-end check. Port 8848 must be free. The
   first quit from a new calling app raises a macOS Automation prompt.
4. `tecopa doctor` checks the repo, both venvs, the launcher, the port and the log.
   Run it first when the engine does not start.

The debug commands (`jobs`, `sessions`, `caches`) need `TECOPA_DEBUG=1` on the engine.
The launcher sets it. For a development engine, set it by hand.

Design: `superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md`.

## Add a tecopa command

A command is one `CatalogEntry`. The CLI and the MCP server both read the catalog.

1. Write the operation in `tools/tecopa/Sources/TecopaKit/` as a `CatalogEntry`, and
   add it to `Catalog.all`. Set `readOnly` to false if it writes or controls anything.
2. Add a thin struct in `tools/tecopa/Sources/tecopa/Commands.swift` that calls
   `execute` with the entry's name. The command's words are the name with a space
   for each underscore.
3. A command that runs a Python script adds a row to `ScriptRunner.table` in the same
   change. The row names the script's venv. A script with no row does not run.
4. Add the name to the two sets in `tools/tecopa/Tests/TecopaKitTests/MCPServerTests.swift`.
5. The tool holds no render logic, no coordinate math and no spec rule. It sends
   values to the engine unchanged and reports the engine's answer unchanged.
```

In the first table of `docs/README.md`, the `changing-things.md` row lists the sections. Add `the tecopa tool` after `the launcher` in that list.

- [ ] **Step 4: `docs/decisions.md`.** Read the file's last dated section for its format. Add one dated section at the end of the dated sections, before the "Rejected and deferred" table, with these facts:

```markdown
## 2026-10-09: the tecopa tool

- Claude gets one tool for the engine: a Swift binary, `tecopa`, that is a command
  line and an MCP server. Swift, not Python, because a diagnosis tool in `.venv`
  fails together with the venv it must diagnose.
- The engine gains read-only debug routes behind `TECOPA_DEBUG=1`. The default is off,
  so a host that did not ask for them has none.
- The launcher stays the one owner of the engine on port 8848. The tool opens and
  quits the launcher and never starts a second uvicorn.
- The script table in `ScriptRunner.swift` is an allowlist. It is the one place that
  decides a script's venv, so invariant 13 is enforced in code.
- Spec: `superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md`. Phase 1 plan:
  `superpowers/plans/2026-10-09-tecopa-tool-phase-1-diagnose.md`.
```

Add these rows to the "Rejected and deferred" table:

```markdown
| 2026-10-09 | A Python `tecopa` in `.venv`. The MCP server inside the launcher app. A CLI with no MCP server. | It fails with the venv. Control only while the app runs. No access from a client with no shell. | `superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md`, Rejected |
| 2026-10-09 | Debug routes always on. Studio reports written to a file. | Any host would list sessions and tracks. A report file is the start of a database. | the same spec |
```

- [ ] **Step 5: `CLAUDE.md`.** Add this row to the "Read this before changing that" table, directly after the macOS launcher row:

```markdown
| The `tecopa` tool, `app/debug.py` | `docs/superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md`, then Build the tecopa tool |
```

- [ ] **Step 6: `docs/README.md`.** The Plans table already has a row for this plan that says it is not built. Replace that row with:

```markdown
| `superpowers/plans/2026-10-09-tecopa-tool-phase-1-diagnose.md` | Changing `tools/tecopa/` or `app/debug.py`. The build record of phase 1 of the `tecopa` tool: the catalog, the engine client, the launcher control, `doctor`, the MCP server. |
```

In the Specifications table, replace the last two sentences of the `2026-10-09-tecopa-cli-and-mcp-design.md` row ("Approved in sections on 2026-10-09 and not built. The build waits for the 2026-10-21 review.") with: `Phase 1 is built. Phases 2, 3 and 4 are not.`

- [ ] **Step 7: The spec.** In `docs/superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md`:

Replace the `**Status:**` line with:

```markdown
**Status:** Approved by Dom (brainstorming session, 2026-10-09). Phase 1 is built: see `../plans/2026-10-09-tecopa-tool-phase-1-diagnose.md`, whose "Decisions made while planning" refine this spec. Phases 2, 3 and 4 are not built.
```

In the exit-code table, add this row after the row for 4:

```markdown
| 64 | A usage error that the argument parser finds, the parser's standard code |
```

In "Venv rule", replace the two sentences that start "`region_prep.py` and `scripts/bake_playa.py` run" and "Every other script runs" with:

```markdown
The table is an allowlist. A script with no row does not run. `region_prep.py`,
`scripts/bake_playa.py` and `scripts/dem_coverage.py` belong to `.venv-prep`.
```

- [ ] **Step 8: Run the docs test**

Run: `.venv/bin/python -m pytest tests/test_docs.py -q`
Expected: `1 passed`. A `dead-path` finding names a quoted path that does not exist: correct the path. A `budget` finding means `CLAUDE.md` passed 2,000 tokens: shorten the new row.

- [ ] **Step 9: Commit the documents**

```bash
git add CLAUDE.md docs/architecture.md docs/changing-things.md docs/decisions.md docs/README.md docs/superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md docs/superpowers/plans/2026-10-09-tecopa-tool-phase-1-diagnose.md
git commit -m "docs: the tecopa tool and the debug routes, so the next session finds the tool, its gate and its build"
```

- [ ] **Step 10: The full suite, then ask Dom before the push**

Run: `.venv/bin/python -m pytest -n auto -q`
Expected: the same failure set as `main` before Task 2. On Dom's Mac the known baseline is `tests/test_output_fitness.py::test_mp4_twin_is_tagged_bt709`, or no failure.
Run: `swift test --package-path tools/tecopa`
Expected: `Executed 50 tests, with 0 failures`.

Report both outputs to Dom. On his yes: `git push origin main`.

- [ ] **Step 11: Log the session.** Write the Session Log entry in `plateworks-session-log` by its CONVENTION.md. Include the two checks from Task 13, Step 5 as open threads.

---

## What changed while it ran

Built on 2026-10-09 on the branch `claude/tecopa-tool-phase-1`. Dom opened the build before the 2026-10-21 review. The task text above is the plan as written. These points differ from it.

- **Counts.** The package has 127 tests, not 50. Three review rounds added the rest.
- **Global options go after the subcommand.** `tecopa doctor --repo <path>`, not `tecopa --repo <path> doctor`. Steps that show the other order are wrong.
- **The MCP result uses `.text(text:annotations:_meta:)`.** The short form `.text("…")` is deprecated in the SDK. Task 1 found this.
- **Review of Task 3.** `?full` takes a boolean. An unknown session is a 404 from one read, with no check-then-read pair.
- **Review of Task 5.** `JSONValue.intValue` uses `Int(exactly:)`, so a number past Int64 cannot trap. An empty `--repo` fails and does not fall through. `build.sh` refuses an unknown argument.
- **Review of Tasks 6 and 7.** The HTTP client refuses redirects and uses no proxy. `EngineClient.probe` tells a timeout from a stopped engine, so a busy engine is never reported as not running. `SystemProcessRunner` has a 300-second deadline. `Catalog.call` refuses an undeclared argument and a wrong argument kind. `engine_status` reports a debug-route error that is not the gate as `debug: null` with `debug_error`.
- **Review of Tasks 8 to 11.** `logs` limits `--lines` to 1 to 2000 and states the `--since` inheritance rule in its help. `engine start` waits 160 seconds. The pgrep pattern is anchored to the launcher's path. `engine stop` waits for the launcher process to exit. `regions verify` treats a Python traceback as a failure, not as drift, and takes only region ids that match `[a-z0-9_]{1,64}`. `RepoLocator` returns a standardized absolute path. `doctor` fails a launcher whose baked path holds no engine, compares versions by component, and reads `.python-version` through a seam.
- **The MCP server drops replies in flight when stdin closes.** A real client keeps stdin open. A script must wait after its last request, as `smoke_test.sh` does.
- **Final review.** The debug routes refuse a Host header that is not local (403), against DNS rebinding. `engine stop` and `engine restart` refuse while a job is running or queued unless forced, and report the jobs and sessions they ended. A 404 from a program that is not Tecopa is no longer reported as a closed gate. Decision 2 (underscore tool names) and the MCP `port` argument are recorded in Decisions and in Task 12.
- **Found, not changed.** `tecopa regions verify elko_bonneville` reports `DRIFT dem.tif`. By invariant 12 this is the record of a rebuilt DEM, and the sidecar stays as it is.
- **Not done here.** The registration in the Claude desktop app, and its file-grant check (spec check 2). The registration in Claude Code waits for Dom's yes.

## Task 1 result

2026-10-09. PASS. Both packages build with Swift 6.4, XCTest runs, the plan's SDK names compile with one deprecation fix, and a binary started from Claude Code reads `README.md` under `~/Documents`.

| Check | Result | Output |
|---|---|---|
| `swift build` of the probe | PASS | `Build complete!`, exit 0, no warnings or errors (after the `.text` fix below) |
| `swift test` of the probe | PASS | `Executed 1 test, with 0 failures (0 unexpected)` |
| `tools/list` holds `ping` and `readOnlyHint` | PASS | `{"id":2,...,"result":{"tools":[{"annotations":{"readOnlyHint":true},"description":"Returns pong and the start of README.md","inputSchema":{"properties":{"word":{"type":"string"}},"type":"object"},"name":"ping"}]}}` |
| `tools/call` reads `README.md` from Claude Code | PASS | `{"id":3,...,"result":{"content":[{"text":"pong hello # Tecopa P","type":"text"}],"isError":false}}` |
| SDK names that differ from this plan | 1 differs | `.text("...")` is deprecated; use `.text(text:annotations:_meta:)`. See below. |

Resolved versions (from `Package.resolved`): swift-argument-parser 1.8.2, swift-sdk (MCP) 0.12.1. Transitive: eventsource 1.5.1, swift-atomics 1.3.1, swift-collections 1.7.2, swift-log 1.16.1, swift-nio 2.104.0, swift-system 1.8.1.

### SDK names for Task 12

1. **`Tool` construction: as the plan assumes.** `Tool(name:description:inputSchema:annotations:)` with `inputSchema: .object(["type": .string("object"), "properties": .object([...])])` and `annotations: .init(readOnlyHint: true)`. The wire reply carries `"annotations":{"readOnlyHint":true}`. `title:` and `outputSchema:` are optional extras. `description:` is `String?` but has no default, so pass it.
2. **`params.arguments`: as the plan assumes.** It is `[String: Value]?`. `params.arguments?["word"]?.stringValue` returns `String?`.
3. **`Value` is `Codable`: as the plan assumes.** `try JSONEncoder().encode(Value.object(["a": .int(1)]))` compiles and prints `{"a":1}`. `Value` also has `init<T: Codable>(_ value: T) throws`, which builds a `Value` from any Codable.
4. **Keep the server alive: as the plan assumes.** `try await server.start(transport: StdioTransport())` then `await server.waitUntilCompleted()`. The process exited 0 after stdin closed.
5. **`CallTool.Result` initializer: differs in the content case only.** `.init(content:structuredContent:isError:_meta:)` exists, and `isError: Bool?`. The plan's `.text("...")` still compiles but warns as deprecated. Use:

```swift
return .init(content: [.text(text: text, annotations: nil, _meta: nil)], isError: false)
```

6. **`swiftLanguageModes: [.v5]`: as the plan assumes.** The manifest is accepted and no concurrency diagnostic appears. A trial build with `[.v6]` also compiled clean (the handlers capture only a local `let`), so Task 12 can use either mode.

Handler registration `await server.withMethodHandler(ListTools.self) { _ in ... }` and `await server.withMethodHandler(CallTool.self) { params in ... }` compiled as written. The server's `initialize` reply echoes `protocolVersion` `2025-03-26`.
