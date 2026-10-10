import XCTest
@testable import TecopaKit

/// A machine where no program can start.
private struct BrokenRunner: ProcessRunning {
    func run(_ executable: String, _ arguments: [String], cwd: String?) throws -> ProcessResult {
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

    /// A healthy machine with a stopped engine: PlistBuddy reports the repo path,
    /// python reports its version, and the repo's marker file can be read.
    private func healthy(readable: Bool = true) -> FakeWorld {
        let w = FakeWorld()
        if readable { w.file("/repo/app/main.py", "app = FastAPI()\n") }
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
        XCTAssertEqual(check(report, "launcher")?["status"]?.stringValue, "ok")
        XCTAssertEqual(report["fail_count"]?.intValue, 1)
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

    func testEveryRowIsStillThereWhenNoProgramCanStart() async {
        // doctor is the command for the worst case, so one fault never stops the rest
        let w = FakeWorld()
        w.file("/repo/app/main.py", "app = FastAPI()\n")
        var runtime = w.runtime(repo: "/repo")
        runtime.runner = BrokenRunner()
        let report = await Doctor.run(runtime)
        XCTAssertEqual(names(report), ["repo", "venv", "venv_prep", "launcher", "engine", "log"])
        XCTAssertEqual(check(report, "repo")?["status"]?.stringValue, "ok")
        XCTAssertEqual(check(report, "venv")?["status"]?.stringValue, "fail")
        XCTAssertEqual(check(report, "launcher")?["status"]?.stringValue, "fail")
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
        XCTAssertEqual(names(report), ["repo", "venv", "venv_prep", "launcher", "engine", "log"])
        // the foreign program is asked for /readyz and for nothing else
        XCTAssertEqual(w.requests.map(\.path), ["/readyz"])
    }

    func testALauncherWhoseBakedPathHasNoEngineFails() async {
        // the folder was moved or deleted after the app was built: the launcher can
        // only show an alert, whatever --repo says
        let w = healthy()
        w.result(for: "PlistBuddy", ProcessResult(exitCode: 0, stdout: "/old/place\n", stderr: ""))
        var runtime = w.runtime(repo: "/repo")
        runtime.fileExists = { !$0.hasPrefix("/old/place/") }
        let report = await Doctor.run(runtime)
        let row = check(report, "launcher")
        XCTAssertEqual(row?["status"]?.stringValue, "fail")
        XCTAssertEqual(row?["detail"]?.stringValue,
                       "The launcher was built for /old/place, and no engine is there.")
        XCTAssertEqual(row?["hint"]?.stringValue, "Run scripts/macos/build_app.sh --install.")

        // the same check with no repo known: the baked path is all there is to test
        runtime = w.runtime(repo: nil)
        runtime.fileExists = { $0 == Launcher.appPath }
        let alone = await Doctor.run(runtime)
        XCTAssertEqual(check(alone, "launcher")?["detail"]?.stringValue,
                       "The launcher was built for /old/place, and no engine is there.")
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
