import XCTest
@testable import TecopaKit

final class ScriptRunnerTests: XCTestCase {
    func testAScriptRunsInItsTableVenvFromTheRepoRoot() throws {
        let w = FakeWorld()
        _ = try ScriptRunner.run("scripts/verify_regions.py", ["lassen_ca"], w.runtime(repo: "/repo"))
        XCTAssertEqual(w.commands, [["/repo/.venv/bin/python", "scripts/verify_regions.py", "lassen_ca"]])
    }

    func testAScriptWithNoRowDoesNotRun() {
        // invariant 13: a prep script in .venv would pull the prep stack's pins into
        // the app venv. A script gets a venv only by a row in the table, and
        // dem_coverage.py has none (plan decision 17).
        let w = FakeWorld()
        for name in ["scripts/dem_coverage.py", "scripts/region_prep.py", "./region_prep.py", "app.main",
                     "-m", "-c"] {
            XCTAssertThrowsError(try ScriptRunner.run(name, [], w.runtime()), name) { error in
                XCTAssertEqual((error as? TecopaFailure)?.kind, .usage, name)
            }
        }
        XCTAssertEqual(w.commands, [])
    }

    func testTheTableIsTheWholeAllowlist() {
        // A new row is a new program that the tool can run: this test names each one.
        XCTAssertEqual(ScriptRunner.table, [
            "scripts/verify_regions.py": .script(.app),
            "region_prep.py": .script(.prep),
            "scripts/build_labels.py": .script(.app),
            "scripts/bake_playa.py": .script(.prep),
            "scripts/pack_region.py": .script(.app),
            "app.plates": .module(.app),
            "scripts/order.py": .script(.app),
        ])
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

    func testVerifyRunsFromTheRepoRootAndPassesTheIdsInOrder() async {
        let w = FakeWorld()
        let (env, failure) = await Catalog.call(
            "regions_verify", w.runtime(repo: "/repo"),
            ["regions": .array([.string("rifle_aspen"), .string("lassen_ca")])])
        XCTAssertNil(failure)
        XCTAssertEqual(w.commands,
                       [["/repo/.venv/bin/python", "scripts/verify_regions.py", "rifle_aspen", "lassen_ca"]])
        XCTAssertEqual(w.workingDirectories, ["/repo"])
        XCTAssertEqual(env["data"]?["clean"], .bool(true))
        XCTAssertEqual(env["data"]?["exit_code"]?.intValue, 0)
    }

    func testACrashedScriptIsNotReportedAsDrift() async {
        // Python exits 1 for an uncaught exception, and the script exits 1 for drift
        let trace = """
            Traceback (most recent call last):
              File "scripts/verify_regions.py", line 170, in <module>
                raise SystemExit(main())
              File "scripts/verify_regions.py", line 140, in main
                rows = verify_region(os.path.join(root, rid))
            KeyError: 'assets'

            """
        let w = FakeWorld()
        w.result(for: "python", ProcessResult(exitCode: 1, stdout: "\nlassen_ca  --  0/0 ok", stderr: trace))
        let (env, failure) = await Catalog.call("regions_verify", w.runtime(), [:])
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertEqual(failure?.message, "verify_regions.py crashed: KeyError: 'assets'")
        XCTAssertTrue(failure?.body?["stderr"]?.stringValue?.hasPrefix("Traceback (most recent call last):") ?? false)
        XCTAssertTrue(failure?.body?["stderr"]?.stringValue?.hasSuffix("KeyError: 'assets'") ?? false)
        XCTAssertEqual(env["ok"], .bool(false))
        XCTAssertNil(env["data"])
    }

    func testDriftWithTextOnStderrIsStillData() async {
        let w = FakeWorld()
        w.result(for: "python", ProcessResult(
            exitCode: 1, stdout: "  DRIFT  dem.tif  sha256 differs\n",
            stderr: "DeprecationWarning: something old\n"))
        let (env, failure) = await Catalog.call("regions_verify", w.runtime(), [:])
        XCTAssertNil(failure)
        XCTAssertEqual(env["data"]?["clean"], .bool(false))
        XCTAssertEqual(env["data"]?["exit_code"]?.intValue, 1)
        XCTAssertEqual(env["data"]?["output"]?.stringValue, "DRIFT  dem.tif  sha256 differs")
        XCTAssertEqual(env["data"]?["stderr"]?.stringValue, "DeprecationWarning: something old")
    }

    func testTheStderrFieldIsAlwaysPresent() async {
        let w = FakeWorld()
        let (env, _) = await Catalog.call("regions_verify", w.runtime(), [:])
        XCTAssertEqual(env["data"]?["clean"], .bool(true))
        XCTAssertEqual(env["data"]?["stderr"], .string(""))
    }

    func testVerifyTakesOnlyTheEnginesOwnIdAlphabet() async {
        // the engine's rule is ^[a-z0-9_]{1,64}$. Character.isLetter is true for "é"
        // and for capitals, and a folder name is not a place for either.
        let w = FakeWorld()
        let refused = [
            "LASSEN", "é", "a-b", String(repeating: "a", count: 65), "", "a b", "a/b", "..",
            "lassen_ca\n", "e\u{301}", "ａ", "٣",
        ]
        for id in refused {
            let (_, failure) = await Catalog.call(
                "regions_verify", w.runtime(), ["regions": .array([.string("lassen_ca"), .string(id)])])
            XCTAssertEqual(failure?.kind, .usage, id)
        }
        XCTAssertEqual(w.commands, [])

        let longest = String(repeating: "a", count: 64)
        let (_, failure) = await Catalog.call(
            "regions_verify", w.runtime(), ["regions": .array([.string(longest), .string("rifle_aspen_2")])])
        XCTAssertNil(failure)
        XCTAssertEqual(w.commands.count, 1)
    }

    func testVerifyRefusesARegionIdThatIsNotAnId() async {
        let w = FakeWorld()
        let (_, failure) = await Catalog.call(
            "regions_verify", w.runtime(), ["regions": .array([.string("--regions-root=/tmp")])])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertEqual(w.commands, [])
    }
}
