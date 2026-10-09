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
