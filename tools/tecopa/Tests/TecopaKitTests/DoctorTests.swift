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
