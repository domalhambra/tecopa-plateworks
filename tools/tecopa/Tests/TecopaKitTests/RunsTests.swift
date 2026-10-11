import XCTest
@testable import TecopaKit

/// The paths that a test's runtime was asked to read, in order.
private final class PathLog: @unchecked Sendable {
    private let lock = NSLock()
    private var paths: [String] = []

    func add(_ path: String) { lock.withLock { paths.append(path) } }
    var all: [String] { lock.withLock { paths } }
}

/// Tracked runs on the fake machine: the start, the record, each state, and the
/// three entries. The real machine is in `TrackedRunTests` below.
final class RunsTests: XCTestCase {
    private let folder = "/home/Library/Application Support/TecopaPlateworks/runs"
    /// The id of a start at the fake's default clock and digits.
    private let id = "20261010-185515-a1b2c3"

    private func call(_ name: String, _ world: FakeWorld,
                      _ arguments: [String: JSONValue] = [:]) async -> (data: JSONValue?, failure: TecopaFailure?) {
        let (envelope, failure) = await Catalog.call(name, world.runtime(), arguments)
        return (envelope["data"], failure)
    }

    /// Put one record in the fake's runs folder, as an earlier call wrote it.
    private func record(_ world: FakeWorld, _ id: String, pid: Int = 4001, command: String = "plate_build",
                        failureText: String? = nil) {
        let value: JSONValue = .object([
            "id": .string(id), "command": .string(command),
            "argv": .array([.string("/repo/.venv-prep/bin/python"), .string("region_prep.py")]),
            "cwd": .string("/repo"), "pid": .int(Int64(pid)), "started": .string("2026-10-10T18:55:15Z"),
            "log": .string("\(folder)/\(id).log"), "exit_file": .string("\(folder)/\(id).exit"),
            "failure_text": failureText.map { .string($0) } ?? .null,
        ])
        world.file("\(folder)/\(id).json", value.text())
    }

    /// The command line of a run's shell, as `ps` prints it.
    private func shell(_ id: String) -> String {
        "/bin/sh -c \(Runs.wrapper) tecopa-run-\(id) \(folder)/\(id).log \(folder)/\(id).exit python region_prep.py"
    }

    private func ps(_ pid: Int) -> [String] { ["/bin/ps", "-o", "command=", "-p", String(pid)] }

    // MARK: The start

    func testTheWrapperTakesEachArgumentAsAPositionalParameter() {
        // No argument is in the text, so none goes through the shell's parsing. The
        // exit code is written to another name and moved, so a reader never finds a
        // file with no number in it.
        XCTAssertEqual(
            Runs.wrapper,
            #"log=$1; code=$2; shift 2; "$@" >>"$log" 2>&1; echo $? >"$code.tmp" && /bin/mv "$code.tmp" "$code""#)
    }

    func testAStartRunsTheWrapperDetachedAndWritesTheRecord() throws {
        let world = FakeWorld()
        var runtime = world.runtime()
        runtime.environment = ["PATH": "/usr/bin:/bin", "PYTHONUNBUFFERED": "0"]
        let result = try Runs.start(
            program: "/repo/.venv/bin/python", arguments: ["scripts/order.py", "prepare", "/orders/a b"],
            cwd: "/repo", command: "order_prepare", failureText: nil, runtime)

        XCTAssertEqual(world.madeFolders, [folder])
        XCTAssertEqual(world.detached, [.init(
            executable: "/bin/sh",
            arguments: ["-c", Runs.wrapper, "tecopa-run-\(id)", "\(folder)/\(id).log", "\(folder)/\(id).exit",
                        "/repo/.venv/bin/python", "scripts/order.py", "prepare", "/orders/a b"],
            cwd: "/repo",
            // the tool's own environment, and the log is current
            environment: ["PATH": "/usr/bin:/bin", "PYTHONUNBUFFERED": "1"],
            pid: 4001)])
        // a detached start is not a command that the tool waits for
        XCTAssertEqual(world.commands, [])

        XCTAssertEqual(world.written.map(\.path), ["\(folder)/\(id).json"])
        let written = try JSONValue.parse(try XCTUnwrap(world.written.first).data)
        XCTAssertEqual(written, .object([
            "id": .string(id), "command": .string("order_prepare"),
            "argv": .array([.string("/repo/.venv/bin/python"), .string("scripts/order.py"),
                            .string("prepare"), .string("/orders/a b")]),
            "cwd": .string("/repo"), "pid": .int(4001), "started": .string("2026-10-10T18:55:15Z"),
            "log": .string("\(folder)/\(id).log"), "exit_file": .string("\(folder)/\(id).exit"),
            "failure_text": .null,
        ]))
        XCTAssertEqual(result, .object([
            "run": .string(id), "pid": .int(4001), "log": .string("\(folder)/\(id).log"),
            "hint": .string("Run `tecopa runs show \(id)`."),
        ]))
    }

    func testTheRunIdIsTheUTCTimeAndSixRandomHexDigits() throws {
        let world = FakeWorld()
        world.now = FakeWorld.date("2026-01-02T03:04:05Z")
        world.hex = "00ff9e77"
        let result = try Runs.start(program: "/bin/true", arguments: [], cwd: "/", command: "test",
                                    failureText: "FAILED", world.runtime())
        XCTAssertEqual(result["run"]?.stringValue, "20260102-030405-00ff9e")
        let written = try JSONValue.parse(try XCTUnwrap(world.written.first).data)
        XCTAssertEqual(written["started"]?.stringValue, "2026-01-02T03:04:05Z")
        XCTAssertEqual(written["failure_text"]?.stringValue, "FAILED")
        XCTAssertEqual(world.detached.first?.arguments[2], "tecopa-run-20260102-030405-00ff9e")
    }

    func testARunIdHasOneExactForm() {
        XCTAssertTrue(Runs.isRunID("20261010-185515-a1b2c3"))
        XCTAssertTrue(Runs.isRunID("00000000-000000-000000"))
        let refused = [
            "", "20261010-185515-a1b2c", "20261010-185515-a1b2c3d", "20261010-185515-A1B2C3",
            "20261010-185515-g1b2c3", "2026101-0185515-a1b2c3", "20261010_185515_a1b2c3",
            "20261010-185515-a1b2c3\n", " 20261010-185515-a1b2c3", "../../etc/passwd",
            "20261010-185515-a1b2c3/..", "２０２６１０１０-185515-a1b2c3", "20261010-185515-a1b2c٣",
            "20261010-185515-a1b2c3.json",
        ]
        for text in refused { XCTAssertFalse(Runs.isRunID(text), text.debugDescription) }
    }

    func testAStartThatCannotStartWritesNoRecord() {
        let world = FakeWorld()
        world.startFailure = TecopaFailure(.environment, "Could not start /bin/sh: no more processes")
        XCTAssertThrowsError(try Runs.start(program: "/bin/true", arguments: [], cwd: "/", command: "test",
                                            failureText: nil, world.runtime())) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
        XCTAssertEqual(world.detached, [])
        XCTAssertEqual(world.written, [])
    }

    func testAnIdThatIsTakenStartsNothing() throws {
        // the same second and the same six digits: the first run's files are not written over
        let world = FakeWorld()
        _ = try Runs.start(program: "/bin/true", arguments: [], cwd: "/", command: "test",
                           failureText: nil, world.runtime())
        XCTAssertThrowsError(try Runs.start(program: "/bin/true", arguments: [], cwd: "/", command: "test",
                                            failureText: nil, world.runtime())) { error in
            let failure = error as? TecopaFailure
            XCTAssertEqual(failure?.kind, .environment)
            XCTAssertTrue(failure?.message.contains(id) ?? false, failure?.message ?? "")
        }
        XCTAssertEqual(world.detached.count, 1)
        XCTAssertEqual(world.written.count, 1)

        // a log or an exit file with the id is the same refusal
        for name in ["log", "exit"] {
            let other = FakeWorld()
            other.existingFile("\(folder)/\(id).\(name)")
            XCTAssertThrowsError(try Runs.start(program: "/bin/true", arguments: [], cwd: "/", command: "test",
                                                failureText: nil, other.runtime()), name)
            XCTAssertEqual(other.detached, [], name)
        }
    }

    func testARunWhoseRecordCannotBeWrittenIsStopped() {
        // a run with no record cannot be read or stopped later, so it does not stay
        let world = FakeWorld()
        var runtime = world.runtime()
        runtime.writeNew = { _, _ in throw TecopaFailure(.environment, "Could not write: the disk is full") }
        XCTAssertThrowsError(try Runs.start(program: "/bin/sleep", arguments: ["30"], cwd: "/", command: "test",
                                            failureText: nil, runtime)) { error in
            let failure = error as? TecopaFailure
            XCTAssertEqual(failure?.kind, .environment)
            XCTAssertTrue(failure?.message.contains("the disk is full") ?? false, failure?.message ?? "")
            XCTAssertTrue(failure?.message.contains("4001") ?? false, failure?.message ?? "")
        }
        XCTAssertEqual(world.detached.count, 1)
        XCTAssertEqual(world.signals, [.init(group: 4001, signal: SIGTERM)])
    }

    func testAnArgumentWithANulByteIsRefused() {
        // a C string ends at the first NUL, so the program would get another argument
        let world = FakeWorld()
        XCTAssertThrowsError(try Runs.start(program: "/bin/echo", arguments: ["a\u{0}b"], cwd: "/",
                                            command: "test", failureText: nil, world.runtime())) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .usage)
        }
        XCTAssertEqual(world.detached, [])
        XCTAssertEqual(world.madeFolders, [])
    }

    // MARK: ScriptRunner.start

    func testScriptRunnerStartChecksTheTableAndTheInterpreterThenStarts() throws {
        let world = FakeWorld()
        let result = try ScriptRunner.start("scripts/verify_regions.py", ["lassen_ca"],
                                            command: "regions_verify", failureText: "DRIFT",
                                            world.runtime(repo: "/repo"))
        XCTAssertEqual(world.detached.count, 1)
        let start = try XCTUnwrap(world.detached.first)
        XCTAssertEqual(start.executable, "/bin/sh")
        XCTAssertEqual(Array(start.arguments.dropFirst(5)),
                       ["/repo/.venv/bin/python", "scripts/verify_regions.py", "lassen_ca"])
        XCTAssertEqual(start.cwd, "/repo")
        let written = try JSONValue.parse(try XCTUnwrap(world.written.first).data)
        XCTAssertEqual(written["command"]?.stringValue, "regions_verify")
        XCTAssertEqual(written["cwd"]?.stringValue, "/repo")
        XCTAssertEqual(written["failure_text"]?.stringValue, "DRIFT")
        XCTAssertEqual(written["argv"], .array([
            .string("/repo/.venv/bin/python"), .string("scripts/verify_regions.py"), .string("lassen_ca")]))
        XCTAssertEqual(result["run"]?.stringValue, id)
        XCTAssertEqual(result["pid"]?.intValue, 4001)
        XCTAssertEqual(result["hint"]?.stringValue, "Run `tecopa runs show \(id)`.")
    }

    func testScriptRunnerStartWithNoRowStartsNothing() {
        // invariant 13: a script gets a venv only by a row in the table
        let world = FakeWorld()
        XCTAssertThrowsError(try ScriptRunner.start("region_prep.py", [], command: "plate_build",
                                                    world.runtime())) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .usage)
        }
        XCTAssertEqual(world.detached, [])
        XCTAssertEqual(world.madeFolders, [])
        XCTAssertEqual(world.written, [])
    }

    func testScriptRunnerStartWithNoInterpreterStartsNothing() {
        let world = FakeWorld()
        var runtime = world.runtime(repo: "/repo")
        runtime.fileExists = { !$0.hasSuffix("/.venv/bin/python") }
        XCTAssertThrowsError(try ScriptRunner.start("scripts/verify_regions.py", [], command: "regions_verify",
                                                    runtime)) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
        XCTAssertEqual(world.detached, [])
        XCTAssertEqual(world.written, [])
    }

    func testATableRowIsAScriptOrAModuleAndTheTableAloneNamesTheVenv() throws {
        // plan decision 14: `python -m app.plates` is not a script path
        let table: [String: ScriptRunner.Row] = [
            "app.plates": .module(.app), "region_prep.py": .script(.prep),
        ]
        let world = FakeWorld()
        _ = try ScriptRunner.run("app.plates", ["verify", "/p/a.png"], world.runtime(repo: "/repo"), table: table)
        _ = try ScriptRunner.run("region_prep.py", ["--id", "x"], world.runtime(repo: "/repo"), table: table)
        XCTAssertEqual(world.commands, [
            ["/repo/.venv/bin/python", "-m", "app.plates", "verify", "/p/a.png"],
            ["/repo/.venv-prep/bin/python", "region_prep.py", "--id", "x"],
        ])
        XCTAssertEqual(world.workingDirectories, ["/repo", "/repo"])

        _ = try ScriptRunner.start("app.plates", ["install", "/p/a.trailplate.zip"], command: "plate_install",
                                   world.runtime(repo: "/repo"), table: table)
        world.hex = "000001"
        _ = try ScriptRunner.start("region_prep.py", ["--id", "x"], command: "plate_build",
                                   world.runtime(repo: "/repo"), table: table)
        XCTAssertEqual(world.detached.map { Array($0.arguments.dropFirst(5)) }, [
            ["/repo/.venv/bin/python", "-m", "app.plates", "install", "/p/a.trailplate.zip"],
            ["/repo/.venv-prep/bin/python", "region_prep.py", "--id", "x"],
        ])

        // the table of the tool itself still has its one script row, in the app venv
        XCTAssertEqual(ScriptRunner.table["scripts/verify_regions.py"], .script(.app))
        // a name that is not in the given table does not run, whatever its form
        XCTAssertThrowsError(try ScriptRunner.run("-m", ["app.plates"], world.runtime(), table: table))
        XCTAssertThrowsError(try ScriptRunner.start("scripts/verify_regions.py", [], command: "x",
                                                    world.runtime(), table: table))
    }

    // MARK: The states

    func testARunWithNoExitFileAndItsProcessIsRunning() async {
        let world = FakeWorld()
        record(world, id)
        world.process(4001, shell(id))
        let (data, failure) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertNil(failure)
        XCTAssertEqual(data?["state"]?.stringValue, "running")
        XCTAssertEqual(data?["exit_code"], .null)
        XCTAssertEqual(world.commands, [ps(4001)])
    }

    func testAnExitCodeOfZeroIsDoneAndAnyOtherIsFailed() async {
        let world = FakeWorld()
        record(world, id)
        world.file("\(folder)/\(id).exit", "0\n")
        var (data, failure) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertNil(failure)
        XCTAssertEqual(data?["state"]?.stringValue, "done")
        XCTAssertEqual(data?["exit_code"]?.intValue, 0)

        for code in [1, 3, 127, 143] {
            world.file("\(folder)/\(id).exit", "\(code)\n")
            (data, failure) = await call("runs_show", world, ["run": .string(id)])
            XCTAssertNil(failure)
            XCTAssertEqual(data?["state"]?.stringValue, "failed", "\(code)")
            XCTAssertEqual(data?["exit_code"]?.intValue, code)
        }
        // the exit file is the answer: no process is looked for
        XCTAssertEqual(world.commands, [])
    }

    func testAnExitFileIsReadBeforeTheProcessTable() async {
        // the pid of a run that ended can belong to a new run of the same id only
        // in theory, but the order is the rule: the exit file wins
        let world = FakeWorld()
        record(world, id)
        world.process(4001, shell(id))
        world.file("\(folder)/\(id).exit", "0\n")
        let (data, _) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertEqual(data?["state"]?.stringValue, "done")
        XCTAssertEqual(world.commands, [])
    }

    func testAnExitFileWithNoNumberIsFailedWithNoExitCode() async {
        let world = FakeWorld()
        record(world, id)
        world.file("\(folder)/\(id).exit", "")
        let (data, failure) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertNil(failure)
        XCTAssertEqual(data?["state"]?.stringValue, "failed")
        XCTAssertEqual(data?["exit_code"], .null)
    }

    func testTheFailureTextInTheLogMakesAnExitCodeOfZeroFailed() async {
        // scripts/bake_playa.py exits 0 when a plate fails, and prints FAILED
        let world = FakeWorld()
        record(world, id, command: "plate_playa", failureText: "FAILED")
        world.file("\(folder)/\(id).exit", "0\n")
        world.file("\(folder)/\(id).log", "lassen_ca: ok\nrifle_aspen: FAILED no lakebed\n2 plates\n")
        var (data, failure) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertNil(failure)
        XCTAssertEqual(data?["state"]?.stringValue, "failed")
        XCTAssertEqual(data?["exit_code"]?.intValue, 0)
        XCTAssertEqual(data?["failure_text"]?.stringValue, "FAILED")
        let (list, _) = await call("runs", world)
        XCTAssertEqual(list?["runs"]?.arrayValue?.first?["state"]?.stringValue, "failed")

        // without the text in the log, the same run is done
        world.file("\(folder)/\(id).log", "lassen_ca: ok\nrifle_aspen: ok\n2 plates\n")
        (data, failure) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertEqual(data?["state"]?.stringValue, "done")

        // a record with no failure text never reads the log for one
        let plain = FakeWorld()
        record(plain, id)
        plain.file("\(folder)/\(id).exit", "0\n")
        plain.file("\(folder)/\(id).log", "FAILED\n")
        (data, failure) = await call("runs_show", plain, ["run": .string(id)])
        XCTAssertEqual(data?["state"]?.stringValue, "done")
    }

    func testARunWithNoExitFileAndNoProcessIsLost() async {
        let world = FakeWorld()
        record(world, id)
        var (data, failure) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertNil(failure)
        XCTAssertEqual(data?["state"]?.stringValue, "lost")
        XCTAssertEqual(data?["exit_code"], .null)

        // macOS gave the pid to another program: its command line has no run name
        world.process(4001, "/usr/bin/python3 /Users/dom/other.py")
        (data, failure) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertEqual(data?["state"]?.stringValue, "lost")
        // and not the name of another run
        world.process(4001, shell("20261010-185515-ffffff"))
        (data, failure) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertEqual(data?["state"]?.stringValue, "lost")
    }

    func testARunThatEndsBetweenTheTwoLooksIsNotLost() async {
        // the script ends after the tool found no exit file and before `ps` runs
        let world = FakeWorld()
        record(world, id)
        let exit = "\(folder)/\(id).exit"
        world.onRun = { world, command in
            if command.first == "/bin/ps" { world.file(exit, "0\n") }
        }
        let (data, failure) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertNil(failure)
        XCTAssertEqual(data?["state"]?.stringValue, "done")
        XCTAssertEqual(data?["exit_code"]?.intValue, 0)
    }

    func testPsThatCannotRunIsAnEnvironmentFailureAndNotLost() async {
        let world = FakeWorld()
        record(world, id)
        world.result(for: "ps", ProcessResult(exitCode: 2, stdout: "", stderr: "ps: illegal option"))
        let (data, failure) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .environment)
    }

    // MARK: runs

    func testRunsListsEveryRecordNewestFirstWithItsState() async {
        let world = FakeWorld()
        let old = "20261009-070000-000001"
        let mid = "20261010-185515-a1b2c3"
        let new = "20261010-185516-000002"
        record(world, mid, pid: 4002, command: "plate_labels")
        record(world, new, pid: 4003, command: "order_prepare")
        record(world, old, pid: 4001)
        world.file("\(folder)/\(old).exit", "0\n")
        world.file("\(folder)/\(old).log", "done\n")
        world.file("\(folder)/\(mid).exit", "2\n")
        world.process(4003, shell(new))
        // a file that is not a record is not a run
        world.file("\(folder)/\(new).exit.tmp", "")
        world.file("\(folder)/.DS_Store", "x")

        let (data, failure) = await call("runs", world)
        XCTAssertNil(failure)
        let runs = data?["runs"]?.arrayValue ?? []
        XCTAssertEqual(runs.map { $0["id"]?.stringValue }, [new, mid, old])
        XCTAssertEqual(runs.map { $0["state"]?.stringValue }, ["running", "failed", "done"])
        XCTAssertEqual(runs.map { $0["exit_code"] }, [.null, .int(2), .int(0)])
        XCTAssertEqual(runs.map { $0["command"]?.stringValue }, ["order_prepare", "plate_labels", "plate_build"])
        XCTAssertEqual(runs.first?["pid"]?.intValue, 4003)
        XCTAssertEqual(runs.first?["log"]?.stringValue, "\(folder)/\(new).log")
        XCTAssertEqual(data?["folder"]?.stringValue, folder)
        // the list has no log text
        XCTAssertNil(runs.last?["lines"])
        // only the run with no exit file needs a look at the process table
        XCTAssertEqual(world.commands, [ps(4003)])
    }

    func testAMissingRunsFolderIsAnEmptyList() async {
        let world = FakeWorld()
        let (data, failure) = await call("runs", world)
        XCTAssertNil(failure)
        XCTAssertEqual(data?["runs"], .array([]))
        // a read makes no folder
        XCTAssertEqual(world.madeFolders, [])
        XCTAssertEqual(world.written, [])
    }

    func testARecordThatCannotBeReadIsListedAsUnreadable() async {
        let world = FakeWorld()
        let good = "20261010-185515-a1b2c3"
        let cut = "20261010-185516-000002"
        let other = "20261010-185517-000003"
        let first = "20261010-185518-000004"
        let zero = "20261010-185519-000005"
        record(world, good)
        world.file("\(folder)/\(good).exit", "0\n")
        world.file("\(folder)/\(cut).json", #"{"id": "20261010-185516-000002", "comm"#)
        // a record that names another run, and a file whose name is not a run id
        record(world, other)
        world.file("\(folder)/\(other).json", world.runtime().readFile("\(folder)/\(good).json") ?? "")
        world.file("\(folder)/notes.json", "{}")
        // pid 1 and pid 0 are never a run: a signal to group 1 or 0 is not one process
        record(world, first, pid: 1)
        record(world, zero, pid: 0)

        let (data, failure) = await call("runs", world)
        XCTAssertNil(failure)
        let runs = data?["runs"]?.arrayValue ?? []
        XCTAssertEqual(runs, [
            .object(["file": .string("notes.json"), "state": .string("unreadable")]),
            .object(["file": .string("\(zero).json"), "state": .string("unreadable")]),
            .object(["file": .string("\(first).json"), "state": .string("unreadable")]),
            .object(["file": .string("\(other).json"), "state": .string("unreadable")]),
            .object(["file": .string("\(cut).json"), "state": .string("unreadable")]),
            runs.last ?? .null,
        ])
        XCTAssertEqual(runs.last?["id"]?.stringValue, good)
        XCTAssertEqual(runs.last?["state"]?.stringValue, "done")

        // by its id, a record that cannot be read is a failure that names the file
        for id in [cut, first] {
            for name in ["runs_show", "runs_cancel"] {
                let (_, failure) = await call(name, world, ["run": .string(id)])
                XCTAssertEqual(failure?.kind, .environment, "\(name) \(id)")
                XCTAssertTrue(failure?.message.contains("\(folder)/\(id).json") ?? false, failure?.message ?? "")
            }
        }
        XCTAssertEqual(world.signals, [])
    }

    // MARK: runs show

    func testRunsShowReturnsTheRecordTheStateAndTheLastLinesOfTheLog() async {
        let world = FakeWorld()
        record(world, id)
        world.file("\(folder)/\(id).exit", "3\n")
        world.file("\(folder)/\(id).log", (1...100).map { "line \($0)" }.joined(separator: "\n") + "\n")

        var (data, failure) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertNil(failure)
        // the default is 40
        XCTAssertEqual(data?["lines"]?.arrayValue?.count, 40)
        XCTAssertEqual(data?["lines"]?.arrayValue?.first?.stringValue, "line 61")
        XCTAssertEqual(data?["lines"]?.arrayValue?.last?.stringValue, "line 100")
        XCTAssertEqual(data?["id"]?.stringValue, id)
        XCTAssertEqual(data?["command"]?.stringValue, "plate_build")
        XCTAssertEqual(data?["pid"]?.intValue, 4001)
        XCTAssertEqual(data?["cwd"]?.stringValue, "/repo")
        XCTAssertEqual(data?["started"]?.stringValue, "2026-10-10T18:55:15Z")
        XCTAssertEqual(data?["log"]?.stringValue, "\(folder)/\(id).log")
        XCTAssertEqual(data?["exit_file"]?.stringValue, "\(folder)/\(id).exit")
        XCTAssertEqual(data?["argv"], .array([.string("/repo/.venv-prep/bin/python"), .string("region_prep.py")]))
        XCTAssertEqual(data?["failure_text"], .null)
        XCTAssertEqual(data?["state"]?.stringValue, "failed")
        XCTAssertEqual(data?["exit_code"]?.intValue, 3)

        (data, failure) = await call("runs_show", world, ["run": .string(id), "lines": .int(2)])
        XCTAssertEqual(data?["lines"], .array([.string("line 99"), .string("line 100")]))
        (data, failure) = await call("runs_show", world, ["run": .string(id), "lines": .int(100)])
        XCTAssertEqual(data?["lines"]?.arrayValue?.count, 100)
    }

    func testTheLinesOfRunsShowAreFrom1To2000() async {
        let world = FakeWorld()
        record(world, id)
        world.file("\(folder)/\(id).exit", "0\n")
        world.file("\(folder)/\(id).log", (1...2100).map { "line \($0)" }.joined(separator: "\n") + "\n")
        for (asked, count) in [(0, 1), (-5, 1), (1, 1), (2000, 2000), (2001, 2000), (5000, 2000)] {
            let (data, failure) = await call("runs_show", world, ["run": .string(id), "lines": .int(Int64(asked))])
            XCTAssertNil(failure)
            XCTAssertEqual(data?["lines"]?.arrayValue?.count, count, "\(asked)")
            XCTAssertEqual(data?["lines"]?.arrayValue?.last?.stringValue, "line 2100")
        }
        let (_, failure) = await call("runs_show", world, ["run": .string(id), "lines": .string("ten")])
        XCTAssertEqual(failure?.message, "lines must be an integer.")
    }

    func testALogLineEndsAtALineFeedACarriageReturnOrBoth() async {
        // a progress bar writes each step after a carriage return
        let world = FakeWorld()
        record(world, id)
        world.process(4001, shell(id))
        world.file("\(folder)/\(id).log", "start\r\n 10%\r 50%\r100%\n\nend")
        let (data, _) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertEqual(data?["lines"], .array([
            .string("start"), .string(" 10%"), .string(" 50%"), .string("100%"), .string("end")]))
    }

    func testARunWithNoLogYetHasNoLines() async {
        let world = FakeWorld()
        record(world, id)
        world.process(4001, shell(id))
        let (data, failure) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertNil(failure)
        XCTAssertEqual(data?["lines"], .array([]))
        XCTAssertEqual(data?["state"]?.stringValue, "running")
    }

    func testARunIdIsCheckedBeforeItGoesIntoAPath() async {
        let world = FakeWorld()
        // a file that a path made from the bad id would reach
        world.file("\(folder)/../../../../etc/passwd.json", "{}")
        world.file("/etc/passwd.json", "{}")
        let reads = PathLog()
        var runtime = world.runtime()
        let readData = runtime.readData
        let readFile = runtime.readFile
        runtime.readData = { path in reads.add(path); return readData(path) }
        runtime.readFile = { path in reads.add(path); return readFile(path) }
        let bad = ["../../../../etc/passwd", "/etc/passwd", "20261010-185515-A1B2C3", "20261010-185515-a1b2c3.json",
                   "", "20261010-185515-a1b2c3/../x", "*"]
        for name in ["runs_show", "runs_cancel"] {
            for text in bad {
                let (_, failure) = await Catalog.call(name, runtime, ["run": .string(text)])
                XCTAssertEqual(failure?.kind, .usage, "\(name) \(text.debugDescription)")
            }
            let (_, failure) = await Catalog.call(name, runtime, [:])
            XCTAssertEqual(failure?.kind, .usage, name)
            XCTAssertTrue(failure?.message.hasPrefix("run is required") ?? false, failure?.message ?? "")
        }
        XCTAssertEqual(reads.all, [])
        XCTAssertEqual(world.commands, [])
        XCTAssertEqual(world.signals, [])
    }

    func testAnIdWithNoRecordIsAUsageFailure() async {
        let world = FakeWorld()
        record(world, "20261010-185515-000001")
        for name in ["runs_show", "runs_cancel"] {
            let (data, failure) = await call(name, world, ["run": .string(id)])
            XCTAssertNil(data)
            XCTAssertEqual(failure, TecopaFailure(.usage, "No run has the id \(id).", hint: "Run `tecopa runs`."))
        }
        XCTAssertEqual(world.signals, [])
    }

    // MARK: runs cancel

    func testRunsCancelSendsSIGTERMToTheGroupOfARunningRun() async {
        let world = FakeWorld()
        record(world, id)
        world.process(4001, shell(id))
        let (data, failure) = await call("runs_cancel", world, ["run": .string(id)])
        XCTAssertNil(failure)
        XCTAssertEqual(data, .object(["run": .string(id), "signalled": .bool(true)]))
        XCTAssertEqual(world.signals, [.init(group: 4001, signal: SIGTERM)])
        // it does not wait: no sleep, and one look at the process table before the signal
        XCTAssertEqual(world.slept, [])
        XCTAssertEqual(world.commands, [ps(4001)])

        // the shell is gone and wrote no exit file, so the run now reads as lost
        let (after, _) = await call("runs_show", world, ["run": .string(id)])
        XCTAssertEqual(after?["state"]?.stringValue, "lost")
        // and a second cancel is refused
        let (_, again) = await call("runs_cancel", world, ["run": .string(id)])
        XCTAssertEqual(again?.kind, .refused)
        XCTAssertEqual(world.signals.count, 1)
    }

    func testRunsCancelOnARunThatIsNotRunningIsRefusedAndSendsNoSignal() async {
        // done
        let world = FakeWorld()
        record(world, id)
        world.file("\(folder)/\(id).exit", "0\n")
        var (data, failure) = await call("runs_cancel", world, ["run": .string(id)])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(failure?.message, "Run \(id) is not running: its state is done.")

        // done, while the pid belongs to a process again: the exit file is the answer
        world.process(4001, shell(id))
        (data, failure) = await call("runs_cancel", world, ["run": .string(id)])
        XCTAssertEqual(failure?.message, "Run \(id) is not running: its state is done.")

        // failed
        world.file("\(folder)/\(id).exit", "1\n")
        (data, failure) = await call("runs_cancel", world, ["run": .string(id)])
        XCTAssertEqual(failure?.message, "Run \(id) is not running: its state is failed.")

        // lost, and the pid is another program's: this is the signal that must not go
        let other = FakeWorld()
        record(other, id)
        other.process(4001, "/Applications/Safari.app/Contents/MacOS/Safari")
        (data, failure) = await call("runs_cancel", other, ["run": .string(id)])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(failure?.message, "Run \(id) is not running: its state is lost.")

        XCTAssertEqual(world.signals, [])
        XCTAssertEqual(other.signals, [])
    }

    // MARK: The catalog

    func testOnlyRunsCancelIsNotReadOnly() {
        XCTAssertEqual(Catalog.named("runs")?.readOnly, true)
        XCTAssertEqual(Catalog.named("runs_show")?.readOnly, true)
        XCTAssertEqual(Catalog.named("runs_cancel")?.readOnly, false)
        func parameters(_ name: String) -> [String] {
            (Catalog.named(name)?.parameters ?? []).map { "\($0.name):\($0.kind.rawValue)" }
        }
        XCTAssertEqual(parameters("runs"), [])
        XCTAssertEqual(parameters("runs_show"), ["run:string", "lines:integer"])
        XCTAssertEqual(parameters("runs_cancel"), ["run:string"])
    }

    func testNoEntryDeletesARecordALogOrAnExitFile() async throws {
        // the three entries write nothing: the one write of a run is its record, at the start
        let world = FakeWorld()
        _ = try Runs.start(program: "/bin/sleep", arguments: ["30"], cwd: "/", command: "test",
                           failureText: nil, world.runtime())
        XCTAssertEqual(world.written.count, 1)
        _ = await call("runs", world)
        _ = await call("runs_show", world, ["run": .string(id)])
        _ = await call("runs_cancel", world, ["run": .string(id)])
        _ = await call("runs_show", world, ["run": .string(id)])
        XCTAssertEqual(world.written.count, 1)
        XCTAssertEqual(world.madeFolders, [folder])
        // the record is still there, and no program ran but `ps`
        let (data, _) = await call("runs", world)
        XCTAssertEqual(data?["runs"]?.arrayValue?.count, 1)
        XCTAssertTrue(world.commands.allSatisfy { $0.first == "/bin/ps" })
    }

    // MARK: The text

    func testTheTextOfRunsIsOneLineForEachRun() {
        let data: JSONValue = .object(["folder": .string(folder), "runs": .array([
            .object(["id": .string("20261010-185516-000002"), "state": .string("running"),
                     "command": .string("order_prepare"), "started": .string("2026-10-10T18:55:16Z"),
                     "exit_code": .null]),
            .object(["file": .string("notes.json"), "state": .string("unreadable")]),
            .object(["id": .string("20261009-070000-000001"), "state": .string("done"),
                     "command": .string("plate_build"), "started": .string("2026-10-09T07:00:00Z"),
                     "exit_code": .int(0)]),
        ])])
        XCTAssertEqual(Catalog.named("runs")?.text?(data), """
            20261010-185516-000002  running  order_prepare  2026-10-10T18:55:16Z
            notes.json  unreadable
            20261009-070000-000001  done  plate_build  2026-10-09T07:00:00Z
            """)
        XCTAssertEqual(Catalog.named("runs")?.text?(.object(["runs": .array([])])), "No runs.")
    }

    func testTheTextOfRunsShowIsTheHeaderThenTheLog() {
        let data: JSONValue = .object([
            "id": .string(id), "state": .string("failed"), "exit_code": .int(3),
            "command": .string("plate_build"), "pid": .int(4001), "started": .string("2026-10-10T18:55:15Z"),
            "cwd": .string("/repo"),
            "argv": .array([.string("/repo/.venv-prep/bin/python"), .string("region_prep.py"), .string("--id"),
                            .string("x")]),
            "log": .string("\(folder)/\(id).log"), "exit_file": .string("\(folder)/\(id).exit"),
            "failure_text": .null, "lines": .array([.string("fetching"), .string("no DEM")]),
        ])
        XCTAssertEqual(Catalog.named("runs_show")?.text?(data), """
            run: \(id)
            state: failed
            exit_code: 3
            command: plate_build
            pid: 4001
            started: 2026-10-10T18:55:15Z
            cwd: /repo
            argv: /repo/.venv-prep/bin/python region_prep.py --id x
            log: \(folder)/\(id).log

            fetching
            no DEM
            """)
        // a run with no exit code and no log line yet has neither line
        let running: JSONValue = .object([
            "id": .string(id), "state": .string("running"), "exit_code": .null,
            "command": .string("plate_build"), "pid": .int(4001), "started": .string("2026-10-10T18:55:15Z"),
            "cwd": .string("/repo"), "argv": .array([.string("python")]),
            "log": .string("/l.log"), "lines": .array([]),
        ])
        XCTAssertEqual(Catalog.named("runs_show")?.text?(running), """
            run: \(id)
            state: running
            command: plate_build
            pid: 4001
            started: 2026-10-10T18:55:15Z
            cwd: /repo
            argv: python
            log: /l.log
            """)
        XCTAssertEqual(Catalog.named("runs_cancel")?.text?(.object(["run": .string(id), "signalled": .bool(true)])),
                       "SIGTERM sent to run \(id). Run `tecopa runs show \(id)`.")
    }

    // MARK: The fake machine

    func testTheFakeListsAFolderAndModelsTheProcessTable() throws {
        let world = FakeWorld()
        let runtime = world.runtime()
        XCTAssertNil(runtime.listFolder("/none"))
        world.folder("/empty")
        XCTAssertEqual(runtime.listFolder("/empty"), [])
        world.file("/f/b.json", "{}")
        world.binary("/f/a.log", Data([1]))
        world.file("/f/deep/c.json", "{}")
        XCTAssertEqual(runtime.listFolder("/f"), ["a.log", "b.json"])
        try runtime.writeNew("/f/c.json", Data("{}".utf8))
        XCTAssertEqual(runtime.listFolder("/f"), ["a.log", "b.json", "c.json"])
        // a file that was written reads back
        XCTAssertEqual(runtime.readFile("/f/c.json"), "{}")
        XCTAssertEqual(runtime.readData("/f/c.json"), Data("{}".utf8))

        try runtime.makeFolder("/made")
        XCTAssertEqual(world.madeFolders, ["/made"])
        XCTAssertEqual(runtime.pathKind("/made"), .folder)

        XCTAssertEqual(runtime.now(), FakeWorld.date("2026-10-10T18:55:15Z"))
        XCTAssertEqual(runtime.randomHex(6), "a1b2c3")

        XCTAssertEqual(try runtime.exec("/bin/ps", ["-o", "command=", "-p", "77"]).exitCode, 1)
        world.process(77, "sleep 30")
        XCTAssertEqual(try runtime.exec("/bin/ps", ["-o", "command=", "-p", "77"]),
                       ProcessResult(exitCode: 0, stdout: "sleep 30\n", stderr: ""))
        world.endProcess(77)
        XCTAssertEqual(try runtime.exec("/bin/ps", ["-o", "command=", "-p", "77"]).exitCode, 1)

        let pid = try world.startDetached("/bin/sleep", ["30"], cwd: "/w", environment: ["A": "1"])
        XCTAssertEqual(pid, 4001)
        XCTAssertEqual(try runtime.exec("/bin/ps", ["-o", "command=", "-p", "4001"]).stdout, "/bin/sleep 30\n")
        try world.signalGroup(4001, SIGTERM)
        XCTAssertEqual(world.signals, [.init(group: 4001, signal: SIGTERM)])
        XCTAssertEqual(try runtime.exec("/bin/ps", ["-o", "command=", "-p", "4001"]).exitCode, 1)
    }
}

/// Tracked runs on the real machine: `SystemProcessRunner`, a temporary folder as
/// the home, and programs that every Mac has. Each wait has a deadline, and each
/// test ends every process group it started.
final class TrackedRunTests: XCTestCase {
    /// A new home folder for one test, removed at its end.
    private func temporaryHome() throws -> String {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("tecopa-runs-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url.path
    }

    /// The real machine, with `home` as its home folder.
    private func machine(_ home: String) -> Runtime {
        Runtime(repoFlag: nil, home: home, runner: SystemProcessRunner())
    }

    /// End a process and its group at the end of the test, whatever the test
    /// found. The process too: with a fault in the start, it leads no group.
    private func endAtTeardown(_ pid: Int32) {
        addTeardownBlock {
            guard pid > 1 else { return }
            kill(-pid, SIGKILL)
            kill(pid, SIGKILL)
        }
    }

    /// Start one program as a run and return its id and its pid.
    private func start(_ runtime: Runtime, _ program: String, _ arguments: [String], cwd: String = "/",
                       failureText: String? = nil) throws -> (id: String, pid: Int32) {
        let result = try Runs.start(program: program, arguments: arguments, cwd: cwd, command: "test",
                                    failureText: failureText, runtime)
        let id = try XCTUnwrap(result["run"]?.stringValue)
        let pid = Int32(try XCTUnwrap(result["pid"]?.intValue))
        endAtTeardown(pid)
        return (id, pid)
    }

    /// Look every 50 ms until `found` is true. False when the deadline comes first.
    private func wait(seconds: Double, until found: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(seconds)
        while Date() < deadline {
            if found() { return true }
            usleep(50_000)
        }
        return found()
    }

    private func show(_ runtime: Runtime, _ id: String) async -> JSONValue? {
        await Catalog.call("runs_show", runtime, ["run": .string(id)]).envelope["data"]
    }

    private func runsFolder(_ home: String) -> String {
        home + "/Library/Application Support/TecopaPlateworks/runs"
    }

    func testARealRunThatExits3IsFailedWithItsLog() async throws {
        let home = try temporaryHome()
        let runtime = machine(home)
        let run = try start(runtime, "/bin/sh", ["-c", "echo hi; echo oops >&2; exit 3"])
        let folder = runsFolder(home)
        let exit = "\(folder)/\(run.id).exit"
        XCTAssertTrue(wait(seconds: 10) { FileManager.default.fileExists(atPath: exit) }, "no exit file")

        let data = await show(runtime, run.id)
        XCTAssertEqual(data?["state"]?.stringValue, "failed")
        XCTAssertEqual(data?["exit_code"]?.intValue, 3)
        // stdout and stderr are in the one log
        XCTAssertEqual(data?["lines"], .array([.string("hi"), .string("oops")]))
        XCTAssertEqual(data?["pid"]?.intValue, Int(run.pid))
        XCTAssertEqual(data?["command"]?.stringValue, "test")
        XCTAssertEqual(data?["log"]?.stringValue, "\(folder)/\(run.id).log")
        XCTAssertTrue(Runs.isRunID(run.id), run.id)

        // the exit file holds the number and no other file is left
        XCTAssertEqual(try String(contentsOfFile: exit, encoding: .utf8), "3\n")
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: folder).sorted(),
                       ["\(run.id).exit", "\(run.id).json", "\(run.id).log"])
        // the folder is the user's own
        let mode = try XCTUnwrap(try FileManager.default.attributesOfItem(atPath: folder)[.posixPermissions]
            as? NSNumber)
        XCTAssertEqual(mode.intValue & 0o777, 0o700)

        let list = await Catalog.call("runs", runtime, [:]).envelope["data"]
        XCTAssertEqual(list?["runs"]?.arrayValue?.count, 1)
        XCTAssertEqual(list?["runs"]?.arrayValue?.first?["state"]?.stringValue, "failed")
        XCTAssertEqual(list?["runs"]?.arrayValue?.first?["exit_code"]?.intValue, 3)

        // a run that ended cannot be cancelled
        let (_, failure) = await Catalog.call("runs_cancel", runtime, ["run": .string(run.id)])
        XCTAssertEqual(failure?.kind, .refused)
    }

    func testARealRunThatExits0IsDoneAndAFailureTextMakesItFailed() async throws {
        let home = try temporaryHome()
        let runtime = machine(home)
        let plain = try start(runtime, "/bin/echo", ["one plate FAILED"])
        let marked = try start(runtime, "/bin/echo", ["one plate FAILED"], failureText: "FAILED")
        let folder = runsFolder(home)
        for run in [plain, marked] {
            XCTAssertTrue(wait(seconds: 10) {
                FileManager.default.fileExists(atPath: "\(folder)/\(run.id).exit")
            }, "no exit file")
        }
        let first = await show(runtime, plain.id)
        XCTAssertEqual(first?["state"]?.stringValue, "done")
        XCTAssertEqual(first?["exit_code"]?.intValue, 0)
        let second = await show(runtime, marked.id)
        XCTAssertEqual(second?["state"]?.stringValue, "failed")
        XCTAssertEqual(second?["exit_code"]?.intValue, 0)
    }

    func testARealRunIsCancelledWithin5Seconds() async throws {
        let home = try temporaryHome()
        let runtime = machine(home)
        let run = try start(runtime, "/bin/sleep", ["30"])

        let before = await show(runtime, run.id)
        XCTAssertEqual(before?["state"]?.stringValue, "running")
        XCTAssertEqual(before?["exit_code"], .null)

        let (envelope, failure) = await Catalog.call("runs_cancel", runtime, ["run": .string(run.id)])
        XCTAssertNil(failure)
        XCTAssertEqual(envelope["data"], .object(["run": .string(run.id), "signalled": .bool(true)]))

        // the shell and the sleep under it are both gone: no process has the pid,
        // and no process is in the group
        let gone = wait(seconds: 5) {
            kill(run.pid, 0) == -1 && errno == ESRCH && kill(-run.pid, 0) == -1 && errno == ESRCH
        }
        XCTAssertTrue(gone, "the run's processes are still there 5 seconds after the cancel")

        // the shell wrote no exit code, so the run is lost, and a second cancel is refused
        let after = await show(runtime, run.id)
        XCTAssertEqual(after?["state"]?.stringValue, "lost")
        let (_, again) = await Catalog.call("runs_cancel", runtime, ["run": .string(run.id)])
        XCTAssertEqual(again?.kind, .refused)
        XCTAssertEqual(again?.message, "Run \(run.id) is not running: its state is lost.")
        // nothing was deleted
        XCTAssertTrue(FileManager.default.fileExists(atPath: "\(runsFolder(home))/\(run.id).json"))
    }

    func testADetachedChildIsInItsOwnSession() throws {
        // its own session, so a closed terminal sends it no hang-up, and its own
        // group, so one signal reaches the script and every process under it
        let pid = try SystemProcessRunner().startDetached("/bin/sleep", ["30"], cwd: nil, environment: [:])
        endAtTeardown(pid)
        XCTAssertGreaterThan(pid, 1)
        XCTAssertEqual(getpgid(pid), pid)
        XCTAssertEqual(getsid(pid), pid)
        XCTAssertNotEqual(getpgid(pid), getpgrp())
        XCTAssertNotEqual(getsid(pid), getsid(0))

        try SystemProcessRunner().signalGroup(pid, SIGTERM)
        XCTAssertTrue(wait(seconds: 5) { kill(pid, 0) == -1 && errno == ESRCH }, "the child was not reaped")
    }

    func testAnArgumentArrivesAsOneLiteralArgument() async throws {
        let home = try temporaryHome()
        let runtime = machine(home)
        let canary = home + "/canary"
        let tricky = "a b  \"q\" 'r' $(touch \(canary)) `touch \(canary)` $HOME; touch \(canary) | \\ * ~ é\ttab"
        let out = home + "/out file.txt"
        let run = try start(runtime, "/bin/sh", ["-c", #"printf '%s\n' "$1" > "$2""#, "x", tricky, out])
        let exit = "\(runsFolder(home))/\(run.id).exit"
        XCTAssertTrue(wait(seconds: 10) { FileManager.default.fileExists(atPath: exit) }, "no exit file")
        XCTAssertEqual(try String(contentsOfFile: out, encoding: .utf8), tricky + "\n")
        XCTAssertFalse(FileManager.default.fileExists(atPath: canary), "the shell ran text from an argument")
        let data = await show(runtime, run.id)
        XCTAssertEqual(data?["state"]?.stringValue, "done")
        // the record keeps each argument as it was given
        XCTAssertEqual(data?["argv"]?.arrayValue?.map(\.stringValue),
                       ["/bin/sh", "-c", #"printf '%s\n' "$1" > "$2""#, "x", tricky, out])
    }

    func testARealRunHasTheWorkingDirectoryTheEnvironmentAndNoInput() async throws {
        let home = try temporaryHome()
        var runtime = machine(home)
        runtime.environment = ["TECOPA_TEST_VALUE": "from the tool", "PATH": "/usr/bin:/bin"]
        // `cat` ends at once: its input is the null device
        let run = try start(runtime, "/bin/sh",
                            ["-c", #"/bin/pwd -P; echo "$TECOPA_TEST_VALUE"; echo "$PYTHONUNBUFFERED"; /bin/cat"#],
                            cwd: home)
        let exit = "\(runsFolder(home))/\(run.id).exit"
        XCTAssertTrue(wait(seconds: 10) { FileManager.default.fileExists(atPath: exit) }, "no exit file")
        let real = try XCTUnwrap(realpath(home, nil))
        defer { free(real) }
        let data = await show(runtime, run.id)
        XCTAssertEqual(data?["lines"], .array([
            .string(String(cString: real)), .string("from the tool"), .string("1")]))
        XCTAssertEqual(data?["state"]?.stringValue, "done")
    }

    func testADetachedChildGetsNoDescriptorOfTheTool() async throws {
        // Under `tecopa mcp` the tool's descriptors carry the protocol. This one
        // has no close-on-exec flag, so only the start itself keeps it from the child.
        let home = try temporaryHome()
        let held = open(home, O_RDONLY)
        XCTAssertGreaterThan(held, 2)
        defer { close(held) }
        XCTAssertEqual(fcntl(held, F_GETFD) & FD_CLOEXEC, 0)

        let runtime = machine(home)
        let run = try start(runtime, "/bin/bash",
                            ["-c", "if ( : <&\(held) ) 2>/dev/null; then echo open; else echo closed; fi"])
        let exit = "\(runsFolder(home))/\(run.id).exit"
        XCTAssertTrue(wait(seconds: 10) { FileManager.default.fileExists(atPath: exit) }, "no exit file")
        let data = await show(runtime, run.id)
        XCTAssertEqual(data?["lines"], .array([.string("closed")]))
    }

    func testAProgramThatDoesNotExistIsAFailedRunWithExitCode127() async throws {
        let home = try temporaryHome()
        let runtime = machine(home)
        let run = try start(runtime, "/no/such/program", ["x"])
        let exit = "\(runsFolder(home))/\(run.id).exit"
        XCTAssertTrue(wait(seconds: 10) { FileManager.default.fileExists(atPath: exit) }, "no exit file")
        let data = await show(runtime, run.id)
        XCTAssertEqual(data?["state"]?.stringValue, "failed")
        XCTAssertEqual(data?["exit_code"]?.intValue, 127)
        XCTAssertTrue(data?["lines"]?.arrayValue?.first?.stringValue?.contains("/no/such/program") ?? false)
    }

    func testADetachedStartOfAMissingExecutableIsAnEnvironmentFailure() {
        XCTAssertThrowsError(try SystemProcessRunner().startDetached(
            "/no/such/shell", [], cwd: nil, environment: [:])) { error in
            let failure = error as? TecopaFailure
            XCTAssertEqual(failure?.kind, .environment)
            XCTAssertTrue(failure?.message.contains("/no/such/shell") ?? false, failure?.message ?? "")
        }
        // a working directory that is not there starts nothing
        XCTAssertThrowsError(try SystemProcessRunner().startDetached(
            "/usr/bin/true", [], cwd: "/no/such/folder", environment: [:])) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
        XCTAssertThrowsError(try SystemProcessRunner().startDetached(
            "/usr/bin/true", ["a\u{0}b"], cwd: nil, environment: [:])) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .usage)
        }
    }

    func testASignalIsNeverSentToGroup0Or1() {
        // kill(-1) is every process of the user, and kill(0) is the tool's own group
        for group: Int32 in [1, 0, -1, -4001] {
            XCTAssertThrowsError(try SystemProcessRunner().signalGroup(group, 0), "\(group)") { error in
                XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
            }
        }
    }

    func testTheRealFolderSeamsMakeAPrivateFolderAndListIt() throws {
        let home = try temporaryHome()
        let folder = home + "/a/b/runs"
        XCTAssertNil(Runtime().listFolder(folder))
        try Runtime().makeFolder(folder)
        try Runtime().makeFolder(folder)          // a folder that exists is not an error
        XCTAssertEqual(Runtime().listFolder(folder), [])
        let mode = try XCTUnwrap(try FileManager.default.attributesOfItem(atPath: folder)[.posixPermissions]
            as? NSNumber)
        XCTAssertEqual(mode.intValue & 0o777, 0o700)
        try Runtime().writeNew(folder + "/b.json", Data("{}".utf8))
        try Runtime().writeNew(folder + "/a.log", Data())
        XCTAssertEqual(Runtime().listFolder(folder)?.sorted(), ["a.log", "b.json"])
        // a file is not a folder
        XCTAssertNil(Runtime().listFolder(folder + "/a.log"))
        XCTAssertThrowsError(try Runtime().makeFolder(folder + "/a.log/under")) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
    }

    func testTheRealClockAndTheRealDigits() {
        let before = Date()
        let now = Runtime().now()
        XCTAssertLessThan(abs(now.timeIntervalSince(before)), 5)
        let digits = Runtime().randomHex(6)
        XCTAssertEqual(digits.count, 6)
        XCTAssertTrue(digits.allSatisfy { "0123456789abcdef".contains($0) }, digits)
        XCTAssertEqual(Runtime().randomHex(0), "")
        // two draws of 32 digits are not the same
        XCTAssertNotEqual(Runtime().randomHex(32), Runtime().randomHex(32))
    }
}
