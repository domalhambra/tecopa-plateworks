import XCTest
@testable import TecopaKit

/// The script table in the Mac app (phase 2 spec, decision 4): the layout's two
/// interpreters, the data root as the working directory, and the engine's own
/// environment. The table's venv column still decides the interpreter.
final class ScriptRunnerBundleTests: XCTestCase {
    private let app = URL(fileURLWithPath: "/Volumes/Work Disk/Tecopa Plateworks.app")
    private let home = "/Users/dom smith"
    private var resources: String { app.path + "/Contents/Resources" }
    private var code: String { resources + "/engine" }
    private var enginePython: String { resources + "/python-engine/bin/python3.14" }
    private var prepPython: String { resources + "/python-prep/bin/python3.14" }
    private var data: String { home + "/Library/Application Support/Tecopa Plateworks" }
    private let shellEnvironment = [
        "PATH": "/usr/bin:/bin", "HOME": "/Users/dom smith", "PYTHONPATH": "/opt/other",
        "PYTHONHOME": "/opt/other", "TECOPA_ORDERS_DIR": "/shell/orders", "GDAL_DATA": "/opt/gdal",
    ]

    private func world() -> (FakeWorld, Runtime) {
        let w = FakeWorld()
        let plist = """
            <?xml version="1.0" encoding="UTF-8"?>
            <plist version="1.0"><dict>
            <key>TecopaEngineVersion</key><string>74cbc38</string>
            </dict></plist>
            """
        w.binary(app.path + "/Contents/Info.plist", Data(plist.utf8))
        w.file(data + "/settings.json", #"{"TECOPA_ORDERS_DIR": "/Users/dom smith/Tecopa Orders"}"#)
        var runtime = w.runtime(repo: nil, home: home)
        runtime.layout = .bundle(app)
        runtime.environment = shellEnvironment
        return (w, runtime)
    }

    /// The environment every bundle script gets: the engine's, from the shell's
    /// own without the dropped variables, the settings and the engine version.
    private var expectedEnvironment: [String: String] {
        EngineEnvironment.build(
            layout: .bundle(app), home: home,
            base: shellEnvironment.filter { !ScriptRunner.droppedVariables.contains($0.key) },
            settings: ["TECOPA_ORDERS_DIR": "/Users/dom smith/Tecopa Orders"], engineVersion: "74cbc38")
    }

    func testAnAppScriptRunsInTheEngineInterpreterFromTheDataRoot() throws {
        let (w, runtime) = world()
        _ = try ScriptRunner.run("scripts/verify_regions.py", ["lassen_ca"], runtime)
        XCTAssertEqual(w.commands, [[enginePython, "-P", code + "/scripts/verify_regions.py", "lassen_ca"]])
        XCTAssertEqual(w.workingDirectories, [data])
        XCTAssertEqual(w.environments, [expectedEnvironment])
        // the settings win over the shell, and the paths are the bundle's
        XCTAssertEqual(w.environments.first??["TECOPA_ORDERS_DIR"], "/Users/dom smith/Tecopa Orders")
        XCTAssertEqual(w.environments.first??["TECOPA_REGIONS"], data + "/regions")
        XCTAssertEqual(w.environments.first??["TECOPA_ENGINE_VERSION"], "74cbc38")
        XCTAssertNil(w.environments.first??["PYTHONPATH"])
        XCTAssertNil(w.environments.first??["GDAL_DATA"])
    }

    func testAPrepScriptRunsInThePrepInterpreter() throws {
        let (w, runtime) = world()
        let command = try ScriptRunner.command("region_prep.py", ["--id", "a b"], runtime, table: ScriptRunner.table)
        XCTAssertEqual(command.python, prepPython)
        XCTAssertEqual(command.arguments, ["-P", code + "/region_prep.py", "--id", "a b"])
        XCTAssertEqual(command.cwd, data)
        XCTAssertEqual(command.environment, expectedEnvironment)

        // started as a tracked run: the same program, folder and environment
        w.folder(data + "/regions")
        _ = try ScriptRunner.start("scripts/bake_playa.py", ["lassen_ca"], command: "plate_playa", runtime)
        let run = try XCTUnwrap(w.detached.first)
        XCTAssertEqual(run.cwd, data)
        XCTAssertEqual(Array(run.arguments.suffix(4)),
                       [prepPython, "-P", code + "/scripts/bake_playa.py", "lassen_ca"])
        var unbuffered = expectedEnvironment
        unbuffered["PYTHONUNBUFFERED"] = "1"
        XCTAssertEqual(run.environment, unbuffered)
    }

    func testAModuleRowRunsThroughRunpyWithItsArguments() throws {
        let (w, runtime) = world()
        _ = try ScriptRunner.run("app.plates", ["verify", "/Users/dom smith/a poster.png"], runtime)
        let bootstrap = "import sys,runpy; sys.path.insert(0, '\(code)'); "
            + "runpy.run_module('app.plates', run_name='__main__', alter_sys=True)"
        XCTAssertEqual(w.commands, [[enginePython, "-P", "-c", bootstrap, "verify", "/Users/dom smith/a poster.png"]])
        XCTAssertEqual(w.workingDirectories, [data])
        XCTAssertEqual(w.environments, [expectedEnvironment])
    }

    func testTheVenvColumnAloneDecidesTheInterpreter() throws {
        // invariant 13: a prep row never gets the engine interpreter, and the reverse
        let (_, runtime) = world()
        for (name, row) in ScriptRunner.table {
            let command = try ScriptRunner.command(name, [], runtime, table: ScriptRunner.table)
            XCTAssertEqual(command.python, row.venv == .prep ? prepPython : enginePython, name)
        }
        let repo = FakeWorld().runtime(repo: "/repo")
        for (name, row) in ScriptRunner.table {
            let command = try ScriptRunner.command(name, [], repo, table: ScriptRunner.table)
            XCTAssertEqual(command.python, "/repo/" + row.venv.rawValue + "/bin/python", name)
        }
    }

    func testAPathWithAQuoteIsAPythonLiteralInTheBootstrap() {
        XCTAssertEqual(ScriptRunner.pythonLiteral(#"/a/it's \ here"#), #"'/a/it\'s \\ here'"#)
        XCTAssertEqual(ScriptRunner.pythonLiteral("/a\nb"), #"'/a\nb'"#)
    }

    func testAMissingBundledInterpreterIsAnEnvironmentFault() {
        let (w, base) = world()
        var runtime = base
        runtime.fileExists = { $0 != self.prepPython }
        XCTAssertThrowsError(try ScriptRunner.run("region_prep.py", [], runtime)) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
        XCTAssertEqual(w.commands, [])
    }

    func testBadSettingsStopTheScript() {
        let (w, runtime) = world()
        w.file(data + "/settings.json", "not json")
        XCTAssertThrowsError(try ScriptRunner.run("scripts/verify_regions.py", [], runtime)) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
        XCTAssertEqual(w.commands, [])
    }

    func testAPlateFolderIsUnderTheDataRootInTheApp() throws {
        let (_, runtime) = world()
        XCTAssertEqual(try Plates.regionsRoot(runtime), data + "/regions")
        XCTAssertEqual(try Plates.folder("lassen_ca", runtime), data + "/regions/lassen_ca")
        XCTAssertEqual(try Plates.regionsRoot(FakeWorld().runtime(repo: "/repo")), "/repo/regions")
    }
}
