import XCTest
@testable import TecopaKit

final class LauncherTests: XCTestCase {
    private let open = ["/usr/bin/open", "-g", "/Applications/Tecopa Plateworks.app"]

    /// A machine where `open` starts the engine and `osascript` stops it.
    private func world(running: Bool) -> FakeWorld {
        let w = FakeWorld()
        if running { w.serve("/readyz", 200, FakeWorld.readyBody) }
        w.onRun = { world, command in
            if command.first == "/usr/bin/open" { world.serve("/readyz", 200, FakeWorld.readyBody) }
            if command.first == "/usr/bin/osascript" { world.stopServing() }
        }
        return w
    }

    func testStartOpensTheLauncherAndWaitsForTheEngine() async throws {
        let w = world(running: false)
        let out = try await Launcher.start(w.runtime())
        XCTAssertEqual(w.commands, [open])
        XCTAssertEqual(out["started"], .bool(true))
    }

    func testStartDoesNothingWhenAnEngineAnswers() async throws {
        let w = world(running: true)
        let out = try await Launcher.start(w.runtime())
        XCTAssertEqual(w.commands, [])
        XCTAssertEqual(out["started"], .bool(false))
        XCTAssertEqual(out["running"], .bool(true))
    }

    func testStartFailsWhenTheLauncherIsNotInstalled() async {
        let w = world(running: false)
        var runtime = w.runtime()
        runtime.fileExists = { $0 != Launcher.appPath }
        do {
            _ = try await Launcher.start(runtime)
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .environment)
            XCTAssertTrue(f.hint?.contains("build_app.sh --install") ?? false)
        } catch { XCTFail("\(error)") }
    }

    func testStartFailsWhenTheEngineNeverAnswers() async {
        let w = FakeWorld()          // open succeeds, and nothing ever serves
        do {
            _ = try await Launcher.start(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .environment)
            XCTAssertTrue(f.message.contains("75 seconds"))
        } catch { XCTFail("\(error)") }
    }

    func testStopQuitsTheLauncherAndWaitsForThePortToClose() async throws {
        let w = world(running: true)
        let out = try await Launcher.stop(w.runtime())
        XCTAssertEqual(w.commands.map { $0[0] }, ["/usr/bin/pgrep", "/usr/bin/osascript"])
        XCTAssertEqual(out["stopped"], .bool(true))
    }

    func testStopRefusesAnEngineTheLauncherDoesNotOwn() async {
        // a hand-started engine on 8848: the launcher is not running, so nothing the
        // tool may do can stop it
        let w = world(running: true)
        w.result(for: "pgrep", ProcessResult(exitCode: 1, stdout: "", stderr: ""))
        do {
            _ = try await Launcher.stop(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .refused)
            XCTAssertEqual(w.commands.map { $0[0] }, ["/usr/bin/pgrep"])
        } catch { XCTFail("\(error)") }
    }

    func testStopNamesTheAutomationPermissionWhenMacOSDeniesTheQuit() async {
        let w = FakeWorld()
        w.serve("/readyz", 200, FakeWorld.readyBody)
        w.result(for: "osascript", ProcessResult(
            exitCode: 1, stdout: "",
            stderr: "execution error: Not authorized to send Apple events to Tecopa Plateworks. (-1743)"))
        do {
            _ = try await Launcher.stop(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .environment)
            XCTAssertTrue(f.hint?.contains("Automation") ?? false)
        } catch { XCTFail("\(error)") }
    }

    func testControlRefusesAnyPortExcept8848() async {
        let w = world(running: false)
        for name in ["engine_start", "engine_stop", "engine_restart"] {
            let (_, failure) = await Catalog.call(name, w.runtime(port: 8000), [:])
            XCTAssertEqual(failure?.kind, .usage, name)
        }
        XCTAssertEqual(w.commands, [])
    }
}
