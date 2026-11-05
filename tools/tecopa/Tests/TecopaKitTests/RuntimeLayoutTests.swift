import XCTest
@testable import TecopaKit

/// How a runtime finds its engine layout (phase 2 spec, decision 5): the layout it
/// was given, then a named repo, then the app that holds the running binary.
final class RuntimeLayoutTests: XCTestCase {
    private let app = URL(fileURLWithPath: "/Applications/Tecopa Plateworks.app")

    func testAnExplicitLayoutWinsOverEverySource() throws {
        let w = FakeWorld()
        w.containingApp = URL(fileURLWithPath: "/elsewhere/Other.app")
        var runtime = w.runtime(repo: "/repo")
        runtime.layout = .bundle(app)
        XCTAssertEqual(try runtime.engineLayout(), .bundle(app))
    }

    func testTheInitTakesALayout() throws {
        let runtime = Runtime(layout: .bundle(app))
        XCTAssertEqual(runtime.layout, .bundle(app))
        XCTAssertEqual(try runtime.engineLayout(), .bundle(app))
    }

    func testANamedRepoIsTheRepoLayoutEvenInsideAnApp() throws {
        let w = FakeWorld()
        w.containingApp = app
        XCTAssertEqual(try w.runtime(repo: "/repo").engineLayout(), .repo("/repo"))

        var runtime = w.runtime(repo: nil)
        runtime.environment = ["TECOPA_REPO": "/checkout"]
        XCTAssertEqual(try runtime.engineLayout(), .repo("/checkout"))
    }

    func testAWrongNamedRepoFailsAndNeverFallsThroughToTheApp() {
        // the locator's rule: a named path that is wrong is an error, never a search
        let w = FakeWorld()
        w.containingApp = app
        var runtime = w.runtime(repo: "/gone")
        runtime.fileExists = { _ in false }
        XCTAssertThrowsError(try runtime.engineLayout()) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
    }

    func testWithNoRepoTheAppThatHoldsTheBinaryIsTheLayout() throws {
        let w = FakeWorld()
        w.containingApp = app
        XCTAssertEqual(try w.runtime(repo: nil).engineLayout(), .bundle(app))
    }

    func testWithNoRepoAndNoAppTheRepoFailureComesBack() {
        let w = FakeWorld()
        XCTAssertThrowsError(try w.runtime(repo: nil).engineLayout()) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
            XCTAssertEqual((error as? TecopaFailure)?.message, "No repository path is known.")
        }
    }

    func testTheContainingAppComesFromTheBundleOrTheHelpersFolder() {
        let found = { (bundle: String, executable: String?) in
            Runtime.appContaining(bundle: URL(fileURLWithPath: bundle), executable: executable)
        }
        // the app's own binary: the main bundle is the app
        XCTAssertEqual(found("/Applications/Tecopa Plateworks.app",
                             "/Applications/Tecopa Plateworks.app/Contents/MacOS/Tecopa Plateworks"), app)
        // the helper: the main bundle is the folder of the binary
        XCTAssertEqual(found("/Applications/Tecopa Plateworks.app/Contents/Helpers",
                             "/Applications/Tecopa Plateworks.app/Contents/Helpers/tecopa"), app)
        // a development build and a test runner are in no app
        XCTAssertNil(found("/repo/tools/tecopa/.build/release", "/repo/tools/tecopa/.build/release/tecopa"))
        XCTAssertNil(found("/usr/bin", nil))
        // a Helpers folder that is not in an app is not an app
        XCTAssertNil(found("/opt/Contents/Helpers", "/opt/Contents/Helpers/tecopa"))
    }
}
