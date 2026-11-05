import XCTest
@testable import TecopaKit

final class EngineEnvironmentTests: XCTestCase {
    private let layout = EngineLayout.bundle(URL(fileURLWithPath: "/dist/Tecopa Plateworks.app"))
    private let resources = "/dist/Tecopa Plateworks.app/Contents/Resources"
    private let support = "/home/Library/Application Support/Tecopa Plateworks"

    private func build(base: [String: String] = ["PATH": "/usr/bin:/bin"],
                       settings: [String: String] = [:]) -> [String: String] {
        EngineEnvironment.build(layout: layout, home: "/home", base: base, settings: settings,
                                engineVersion: "74cbc38")
    }

    func testTheBundleEnvironmentSetsEveryPathAbsolute() {
        let env = build()
        XCTAssertEqual(env["TECOPA_REGIONS"], support + "/regions")
        XCTAssertEqual(env["TECOPA_BLOBS"], support + "/blobs")
        XCTAssertEqual(env["TECOPA_UPLOADS"], support + "/uploads")
        XCTAssertEqual(env["TECOPA_PREP_PYTHON"], resources + "/python-prep/bin/python3.14")
        XCTAssertEqual(env["TECOPA_PREP_SCRIPT"], resources + "/engine/region_prep.py")
        XCTAssertEqual(env["TECOPA_LABELS_SCRIPT"], resources + "/engine/scripts/build_labels.py")
        XCTAssertEqual(env["TECOPA_ENGINE_VERSION"], "74cbc38")
        XCTAssertEqual(env["TECOPA_DEBUG"], "1")
        XCTAssertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
        XCTAssertEqual(env["PYTHONNOUSERSITE"], "1")
        XCTAssertEqual(env["PATH"], "/usr/bin:/bin")
        for (key, value) in env where key.hasPrefix("TECOPA_")
            && !["TECOPA_ENGINE_VERSION", "TECOPA_DEBUG"].contains(key) {
            XCTAssertTrue(value.hasPrefix("/"), "\(key)=\(value)")
        }
        XCTAssertNil(env["TECOPA_ORDERS_DIR"])
        XCTAssertNil(env["TECOPA_INTAKE_DIR"])
    }

    func testTheCleanedVariablesNeverReachTheEngine() {
        var base: [String: String] = ["PATH": "/usr/bin", "HOME": "/home"]
        for name in EngineEnvironment.removedNames { base[name] = "/somewhere" }
        for prefix in EngineEnvironment.removedPrefixes { base[prefix + "ANYTHING"] = "x" }
        base["GDAL_DRIVER_PATH"] = "/opt"
        base["DYLD_LIBRARY_PATH"] = "/opt/lib"
        base["TECOPA_REGIONS"] = "regions"
        let env = build(base: base)
        for name in ["PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "__PYVENV_LAUNCHER__", "PROJ_LIB",
                     "PROJ_DATA", "GDAL_DATA", "TECOPA_RELIEF_WORKERS", "GDAL_DRIVER_PATH",
                     "DYLD_LIBRARY_PATH", "GDAL_ANYTHING", "DYLD_ANYTHING", "TECOPA_ANYTHING"] {
            XCTAssertNil(env[name], name)
        }
        XCTAssertEqual(EngineEnvironment.removedNames, [
            "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "__PYVENV_LAUNCHER__", "PROJ_LIB",
            "PROJ_DATA", "GDAL_DATA", "TECOPA_RELIEF_WORKERS"])
        XCTAssertEqual(EngineEnvironment.removedPrefixes, ["GDAL_", "DYLD_", "TECOPA_"])
        XCTAssertEqual(env["TECOPA_REGIONS"], support + "/regions")
        XCTAssertEqual(env["HOME"], "/home")
    }

    func testSettingsFillOrdersIntakeAndFontsAndAbsentKeysStayUnset() {
        let env = build(
            base: ["PATH": "/usr/bin", "TECOPA_INTAKE_DIR": "/shell/intake", "TECOPA_FONT": "/shell/font.otf"],
            settings: ["TECOPA_ORDERS_DIR": "/home/Tecopa Orders",
                       "TECOPA_FONT_TITLE": "/home/Library/Fonts/Title.otf"])
        XCTAssertEqual(env["TECOPA_ORDERS_DIR"], "/home/Tecopa Orders")
        XCTAssertEqual(env["TECOPA_FONT_TITLE"], "/home/Library/Fonts/Title.otf")
        XCTAssertNil(env["TECOPA_INTAKE_DIR"])
        XCTAssertNil(env["TECOPA_FONT"])
        XCTAssertTrue(EngineEnvironment.isSettingsKey("TECOPA_INTAKE_DIR"))
        XCTAssertTrue(EngineEnvironment.isSettingsKey("TECOPA_FONT"))
        XCTAssertFalse(EngineEnvironment.isSettingsKey("TECOPA_REGIONS"))
    }

    func testASettingsKeyOutsideTheTableIsIgnored() {
        let env = build(settings: ["TECOPA_REGIONS": "/elsewhere", "PYTHONPATH": "/evil",
                                   "TECOPA_DEBUG": "0"])
        XCTAssertEqual(env["TECOPA_REGIONS"], support + "/regions")
        XCTAssertNil(env["PYTHONPATH"])
        XCTAssertEqual(env["TECOPA_DEBUG"], "1")
    }

    func testSettingsJsonParses() throws {
        let path = support + "/settings.json"
        XCTAssertEqual(try EngineEnvironment.settings(from: nil, path: path), [:])
        let data = Data(#"{"TECOPA_ORDERS_DIR": "/home/Tecopa Orders", "TECOPA_FONT_BODY": "/f.otf"}"#.utf8)
        XCTAssertEqual(try EngineEnvironment.settings(from: data, path: path),
                       ["TECOPA_ORDERS_DIR": "/home/Tecopa Orders", "TECOPA_FONT_BODY": "/f.otf"])
        for bad in ["{not json", "[1, 2]"] {
            XCTAssertThrowsError(try EngineEnvironment.settings(from: Data(bad.utf8), path: path)) { error in
                XCTAssertEqual(error as? TecopaFailure, TecopaFailure(
                    .environment, "settings.json is not valid JSON: " + path))
            }
        }
    }

    func testTheEngineCommandIsTheSpecsCommand() {
        let command = EngineEnvironment.command(layout: layout, port: 8848)
        XCTAssertEqual(command.executable, resources + "/python-engine/bin/python3.14")
        XCTAssertEqual(command.arguments, [
            "-P", "-m", "uvicorn", "app.main:app", "--app-dir", resources + "/engine",
            "--host", "127.0.0.1", "--port", "8848"])
    }
}
