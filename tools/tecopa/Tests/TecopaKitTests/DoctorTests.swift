import XCTest
@testable import TecopaKit

/// A machine where no program can start.
private struct BrokenRunner: ProcessRunning {
    func run(_ executable: String, _ arguments: [String], cwd: String?,
             environment: [String: String]?) throws -> ProcessResult {
        throw CocoaError(.fileNoSuchFile)
    }

    func startDetached(_ executable: String, _ arguments: [String], cwd: String?,
                       environment: [String: String]) throws -> Int32 {
        throw CocoaError(.fileNoSuchFile)
    }

    func signalGroup(_ group: Int32, _ signal: Int32) throws {
        throw CocoaError(.fileNoSuchFile)
    }
}

final class DoctorTests: XCTestCase {
    private func check(_ report: JSONValue, _ name: String) -> JSONValue? {
        (report["checks"]?.arrayValue ?? []).first { $0["name"]?.stringValue == name }
    }

    private func names(_ report: JSONValue) -> [String] {
        (report["checks"]?.arrayValue ?? []).compactMap { $0["name"]?.stringValue }
    }

    private static let app = "/Applications/Tecopa Plateworks.app"
    private static let enginePython = app + "/Contents/Resources/python-engine/bin/python3.14"
    private static let prepPython = app + "/Contents/Resources/python-prep/bin/python3.14"

    /// The app's Info.plist, with the keys given.
    private static func plist(_ keys: [String: String]) -> Data {
        // swiftlint:disable:next force_try
        try! PropertyListSerialization.data(fromPropertyList: keys, format: .xml, options: 0)
    }

    /// A healthy machine with a stopped engine: the app's Info.plist names the new
    /// id and an engine version, every python reports its version, and the repo's
    /// marker file can be read.
    private func healthy(readable: Bool = true) -> FakeWorld {
        let w = FakeWorld()
        if readable { w.file("/repo/app/main.py", "app = FastAPI()\n") }
        w.binary(Self.app + "/Contents/Info.plist", Self.plist(
            ["CFBundleIdentifier": "org.plateworks.tecopa", "TecopaEngineVersion": "74cbc38"]))
        w.result(for: "python", ProcessResult(exitCode: 0, stdout: "Python 3.14.2\n", stderr: ""))
        w.result(for: "python3.14", ProcessResult(exitCode: 0, stdout: "Python 3.14.2\n", stderr: ""))
        return w
    }

    func testAHealthyAppRowNamesTheIdAndTheEngineVersion() async {
        let w = healthy()
        let report = await Doctor.run(w.runtime(repo: "/repo"))
        let row = check(report, "app")
        XCTAssertEqual(row?["status"]?.stringValue, "ok")
        XCTAssertEqual(row?["detail"]?.stringValue,
                       "org.plateworks.tecopa, engine 74cbc38, both interpreters run.")
        XCTAssertTrue(w.commands.contains([Self.enginePython, "--version"]))
        XCTAssertTrue(w.commands.contains([Self.prepPython, "--version"]))
    }

    func testTheOldLauncherAtTheAppPathFails() async {
        let w = healthy()
        w.binary(Self.app + "/Contents/Info.plist", Self.plist(
            ["CFBundleIdentifier": "guide.badwater.tecopa", "TecopaRepoPath": "/repo"]))
        let report = await Doctor.run(w.runtime(repo: "/repo"))
        let row = check(report, "app")
        XCTAssertEqual(row?["status"]?.stringValue, "fail")
        XCTAssertEqual(row?["detail"]?.stringValue,
                       "The app at \(Self.app) is guide.badwater.tecopa, not org.plateworks.tecopa.")
        XCTAssertEqual(report["fail_count"]?.intValue, 1)
    }

    func testAnAppWhoseInterpreterDoesNotRunFails() async {
        let w = healthy()
        w.result(for: "python3.14", ProcessResult(exitCode: 1, stdout: "", stderr: "dyld: Library not loaded"))
        let row = check(await Doctor.run(w.runtime(repo: "/repo")), "app")
        XCTAssertEqual(row?["status"]?.stringValue, "fail")
        XCTAssertEqual(row?["detail"]?.stringValue, "The bundled interpreter \(Self.enginePython) does not run.")
    }

    func testAMissingAppIsAWarning() async {
        let w = healthy()
        var runtime = w.runtime(repo: "/repo")
        runtime.fileExists = { $0 != Self.app }
        let report = await Doctor.run(runtime)
        let row = check(report, "app")
        XCTAssertEqual(row?["status"]?.stringValue, "warn")
        XCTAssertEqual(row?["detail"]?.stringValue, "Tecopa Plateworks is not installed at \(Self.app).")
        XCTAssertEqual(report["fail_count"]?.intValue, 0)

        // TECOPA_APP moves the check to a dist/ build
        runtime.environment["TECOPA_APP"] = "/dist/Tecopa Plateworks.app"
        let moved = check(await Doctor.run(runtime), "app")
        XCTAssertEqual(moved?["status"]?.stringValue, "fail")       // no plist served there
        XCTAssertTrue(moved?["detail"]?.stringValue?.contains("/dist/Tecopa Plateworks.app") ?? false)
    }

    func testAnAppWithNoEngineVersionFails() async {
        let w = healthy()
        w.binary(Self.app + "/Contents/Info.plist", Self.plist(["CFBundleIdentifier": "org.plateworks.tecopa"]))
        let row = check(await Doctor.run(w.runtime(repo: "/repo")), "app")
        XCTAssertEqual(row?["status"]?.stringValue, "fail")
        XCTAssertEqual(row?["detail"]?.stringValue, "The app at \(Self.app) has no TecopaEngineVersion.")
    }

    func testTheVenvRowsReadTheRepoLayout() {
        let w = healthy()
        let rows = Doctor.venvRows(w.runtime(repo: "/my repo"), layout: .repo("/my repo"))
        XCTAssertEqual(rows.compactMap { $0["name"]?.stringValue }, ["venv", "venv_prep"])
        XCTAssertEqual(rows.first?["detail"]?.stringValue, "Python 3.14.2")
        XCTAssertEqual(w.commands, [["/my repo/.venv/bin/python", "--version"]])
        XCTAssertEqual(w.workingDirectories, ["/my repo"])
        XCTAssertEqual(rows.last?["detail"]?.stringValue, "/my repo/.venv-prep/bin/python")
    }

    func testAStoppedEngineIsAWarningAndNotAFailure() async {
        let report = await Doctor.run(healthy().runtime(repo: "/repo"))
        XCTAssertEqual(check(report, "engine")?["status"]?.stringValue, "warn")
        XCTAssertEqual(check(report, "repo")?["status"]?.stringValue, "ok")
        XCTAssertEqual(check(report, "venv")?["status"]?.stringValue, "ok")
        XCTAssertEqual(check(report, "app")?["status"]?.stringValue, "ok")
        XCTAssertEqual(report["fail_count"]?.intValue, 0)
    }

    func testARepoWhoseFilesCannotBeReadFailsAndTheLaterChecksStillRun() async {
        // macOS guards the contents of ~/Documents and not the names: the marker is
        // there, and the read is refused. Only a read can prove the access.
        let report = await Doctor.run(healthy(readable: false).runtime(repo: "/repo"))
        let row = check(report, "repo")
        XCTAssertEqual(row?["status"]?.stringValue, "fail")
        XCTAssertEqual(row?["detail"]?.stringValue,
                       "The repo is at /repo, and app/main.py there cannot be read.")
        XCTAssertTrue(row?["hint"]?.stringValue?.contains("Files and Folders") == true)
        XCTAssertEqual(check(report, "venv")?["status"]?.stringValue, "ok")
        XCTAssertEqual(check(report, "app")?["status"]?.stringValue, "ok")
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
        runtime.fileExists = { $0 == "/Applications/Tecopa Plateworks.app" }
        let report = await Doctor.run(runtime)
        XCTAssertEqual(check(report, "repo")?["status"]?.stringValue, "fail")
        XCTAssertNotNil(check(report, "engine"))
        XCTAssertNotNil(check(report, "log"))
    }

    func testEveryRowIsStillThereWhenNoProgramCanStart() async {
        // doctor is the command for the worst case, so one fault never stops the rest
        let w = FakeWorld()
        w.file("/repo/app/main.py", "app = FastAPI()\n")
        var runtime = w.runtime(repo: "/repo")
        runtime.runner = BrokenRunner()
        let report = await Doctor.run(runtime)
        XCTAssertEqual(names(report), ["repo", "venv", "venv_prep", "app", "engine", "log"])
        XCTAssertEqual(check(report, "repo")?["status"]?.stringValue, "ok")
        XCTAssertEqual(check(report, "venv")?["status"]?.stringValue, "fail")
        XCTAssertEqual(check(report, "app")?["status"]?.stringValue, "fail")
        XCTAssertEqual(check(report, "engine")?["status"]?.stringValue, "warn")
        XCTAssertEqual(report["fail_count"]?.intValue, 2)
    }

    func testAForeignProgramOnThePortFailsAndHasNoGateRow() async {
        let w = healthy()
        w.serve("/readyz", 200, "<html>hello</html>")
        w.serve("/api/debug/engine", 200, #"{"engine":"something else"}"#)
        let report = await Doctor.run(w.runtime(repo: "/repo"))
        let row = check(report, "engine")
        XCTAssertEqual(row?["status"]?.stringValue, "fail")
        XCTAssertEqual(row?["detail"]?.stringValue, "Port 8848 answers, but it is not Tecopa Plateworks.")
        XCTAssertNil(check(report, "debug_gate"))
        XCTAssertEqual(names(report), ["repo", "venv", "venv_prep", "app", "engine", "log"])
        // the foreign program is asked for /readyz and for nothing else
        XCTAssertEqual(w.requests.map(\.path), ["/readyz"])
    }

    /// The venv row for one interpreter version and one .python-version file.
    private func venvRow(found: String, wanted: String?) async -> JSONValue? {
        let w = healthy()
        w.result(for: "python", ProcessResult(exitCode: 0, stdout: found + "\n", stderr: ""))
        if let wanted { w.file("/repo/.python-version", wanted) }
        return check(await Doctor.run(w.runtime(repo: "/repo")), "venv")
    }

    func testThePythonVersionIsComparedByComponent() async {
        var row = await venvRow(found: "Python 3.14.2", wanted: "3.14\n")
        XCTAssertEqual(row?["status"]?.stringValue, "ok")
        XCTAssertEqual(row?["detail"]?.stringValue, "Python 3.14.2")

        row = await venvRow(found: "Python 3.14.2", wanted: "3.14.2")
        XCTAssertEqual(row?["status"]?.stringValue, "ok")

        // "3.1" is a prefix of the text "3.14.2" and is not the same version
        row = await venvRow(found: "Python 3.14.2", wanted: "3.1\n")
        XCTAssertEqual(row?["status"]?.stringValue, "warn")
        XCTAssertEqual(row?["detail"]?.stringValue, "Python 3.14.2, and .python-version asks for 3.1.")

        row = await venvRow(found: "Python 3.14.10", wanted: "3.14.1")
        XCTAssertEqual(row?["status"]?.stringValue, "warn")

        row = await venvRow(found: "Python 3.13.9", wanted: "3.14")
        XCTAssertEqual(row?["status"]?.stringValue, "warn")

        // more components than the interpreter has
        row = await venvRow(found: "Python 3.14", wanted: "3.14.2")
        XCTAssertEqual(row?["status"]?.stringValue, "warn")
    }

    func testAWantedVersionThatIsNotNumbersIsNotCompared() async {
        for wanted in ["cpython-3.14", "3.14t", "3..14", "system"] {
            let row = await venvRow(found: "Python 3.14.2", wanted: wanted)
            XCTAssertEqual(row?["status"]?.stringValue, "ok", wanted)
            XCTAssertEqual(row?["detail"]?.stringValue, "Python 3.14.2", wanted)
        }
        // no file, and an empty file
        var row = await venvRow(found: "Python 3.14.2", wanted: nil)
        XCTAssertEqual(row?["status"]?.stringValue, "ok")
        row = await venvRow(found: "Python 3.14.2", wanted: "\n")
        XCTAssertEqual(row?["status"]?.stringValue, "ok")
    }

    func testADebugRouteThatFailsIsNotReportedAsAClosedGate() async {
        let w = healthy()
        w.serve("/readyz", 200, FakeWorld.readyBody)
        w.serve("/api/debug/engine", 500, "Internal Server Error")
        let report = await Doctor.run(w.runtime(repo: "/repo"))
        let row = check(report, "debug_gate")
        XCTAssertEqual(row?["status"]?.stringValue, "warn")
        XCTAssertEqual(row?["detail"]?.stringValue,
                       "The debug routes did not answer: The engine answered 500 for /api/debug/engine.")
        XCTAssertNil(row?["hint"])
    }

    func testAClosedGateKeepsItsHint() async {
        let w = healthy()
        w.serve("/readyz", 200, FakeWorld.readyBody)
        w.serve("/api/debug/engine", 404, #"{"detail":"Not Found"}"#)
        let row = check(await Doctor.run(w.runtime(repo: "/repo")), "debug_gate")
        XCTAssertEqual(row?["detail"]?.stringValue, "The debug routes are off.")
        XCTAssertTrue(row?["hint"]?.stringValue?.contains("TECOPA_DEBUG=1") ?? false)
    }

    func testAPortThatDoesNotAnswerInTimeIsAWarningAndNotAStoppedEngine() async {
        let w = healthy()
        w.timeOut("/readyz")
        let report = await Doctor.run(w.runtime(repo: "/repo"))
        let row = check(report, "engine")
        XCTAssertEqual(row?["status"]?.stringValue, "warn")
        XCTAssertEqual(row?["detail"]?.stringValue,
                       "Port 8848 accepts connections but did not answer within 3 seconds.")
        XCTAssertEqual(row?["hint"]?.stringValue, "An engine may be busy with a render. Run `tecopa logs`.")
        XCTAssertNil(check(report, "debug_gate"))
    }

    func testTheHintForAStoppedEngineFitsThePort() async {
        // `engine start` controls only the launcher's engine on 8848
        var row = check(await Doctor.run(healthy().runtime(port: 8000, repo: "/repo")), "engine")
        XCTAssertEqual(row?["status"]?.stringValue, "warn")
        XCTAssertEqual(row?["detail"]?.stringValue, "No engine answers on port 8000.")
        XCTAssertEqual(row?["hint"]?.stringValue, "Start the development engine on that port.")

        row = check(await Doctor.run(healthy().runtime(repo: "/repo")), "engine")
        XCTAssertEqual(row?["detail"]?.stringValue, "No engine answers on port 8848.")
        XCTAssertEqual(row?["hint"]?.stringValue, "Run `tecopa engine start`.")
    }

    func testAnEngineThatIsNotReadyAndNamesNoPlateSaysSo() async {
        let w = healthy()
        w.serve("/readyz", 503, #"{"ready":false,"regions":[]}"#)
        w.serve("/api/debug/engine", 200, #"{"engine":"tecopa-plateworks"}"#)
        let report = await Doctor.run(w.runtime(repo: "/repo"))
        let row = check(report, "engine")
        XCTAssertEqual(row?["status"]?.stringValue, "fail")
        XCTAssertEqual(row?["detail"]?.stringValue,
                       "The engine answers and reports that it is not ready, with no plate named.")
        XCTAssertEqual(check(report, "debug_gate")?["status"]?.stringValue, "ok")
    }
}
