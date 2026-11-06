import XCTest
@testable import TecopaKit

final class EngineLayoutTests: XCTestCase {
    private let app = URL(fileURLWithPath: "/dist/Tecopa Plateworks.app")
    private let resources = "/dist/Tecopa Plateworks.app/Contents/Resources"

    func testABundleLayoutNamesItsResources() {
        let layout = EngineLayout.bundle(app)
        XCTAssertEqual(layout.codeRoot, resources + "/engine")
        XCTAssertEqual(layout.enginePython, resources + "/python-engine/bin/python3.14")
        XCTAssertEqual(layout.prepPython, resources + "/python-prep/bin/python3.14")
        XCTAssertEqual(layout.platesRoot, resources + "/plates")
        XCTAssertEqual(layout.dataRoot(home: "/Users/dom"),
                       "/Users/dom/Library/Application Support/Tecopa Plateworks")
    }

    func testARepoLayoutNamesTheTwoVenvs() {
        let layout = EngineLayout.repo("/Users/dom/Tecopa Plateworks")
        XCTAssertEqual(layout.codeRoot, "/Users/dom/Tecopa Plateworks")
        XCTAssertEqual(layout.enginePython, "/Users/dom/Tecopa Plateworks/.venv/bin/python")
        XCTAssertEqual(layout.prepPython, "/Users/dom/Tecopa Plateworks/.venv-prep/bin/python")
        XCTAssertEqual(layout.platesRoot, "/Users/dom/Tecopa Plateworks/regions")
        XCTAssertEqual(layout.dataRoot(home: "/Users/dom"), "/Users/dom/Tecopa Plateworks")
    }

    func testTheTwoInterpretersAreNeverOneFile() {
        for layout in [EngineLayout.bundle(app), .repo("/repo")] {
            XCTAssertNotEqual(layout.enginePython, layout.prepPython, "\(layout)")
        }
    }

    func testTheRepoLayoutAgreesWithScriptRunner() {
        let layout = EngineLayout.repo("/repo")
        XCTAssertEqual(layout.enginePython, "/repo/" + ScriptRunner.Venv.app.rawValue + "/bin/python")
        XCTAssertEqual(layout.prepPython, "/repo/" + ScriptRunner.Venv.prep.rawValue + "/bin/python")
    }

    func testTheEngineVersionComesFromInfoPlist() {
        let w = FakeWorld()
        let plist = """
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0"><dict>
            <key>CFBundleIdentifier</key><string>org.plateworks.tecopa</string>
            <key>TecopaEngineVersion</key><string>74cbc38</string>
            </dict></plist>
            """
        w.binary("/dist/Tecopa Plateworks.app/Contents/Info.plist", Data(plist.utf8))
        let runtime = w.runtime()
        XCTAssertEqual(EngineLayout.bundle(app).infoValue("TecopaEngineVersion", runtime), "74cbc38")
        XCTAssertEqual(EngineLayout.bundle(app).infoValue("CFBundleIdentifier", runtime),
                       "org.plateworks.tecopa")
        XCTAssertNil(EngineLayout.bundle(app).infoValue("NoSuchKey", runtime))
        XCTAssertNil(EngineLayout.repo("/repo").infoValue("TecopaEngineVersion", runtime))
        let missing = URL(fileURLWithPath: "/elsewhere/Tecopa Plateworks.app")
        XCTAssertNil(EngineLayout.bundle(missing).infoValue("TecopaEngineVersion", runtime))
    }
}
