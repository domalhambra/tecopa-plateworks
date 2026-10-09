import XCTest
@testable import TecopaKit

final class LauncherTests: XCTestCase {
    private let open = ["/usr/bin/open", "-g", "/Applications/Tecopa Plateworks.app"]
    private let pgrep = [
        "/usr/bin/pgrep", "-f",
        #"^/Applications/Tecopa Plateworks\.app/Contents/MacOS/TecopaPlateworks( |$)"#,
    ]
    private let quit = ["/usr/bin/osascript", "-e", "quit app \"Tecopa Plateworks\""]

    /// A machine where `open` starts the launcher and its engine, and `osascript`
    /// stops both.
    private func world(running: Bool) -> FakeWorld {
        let w = FakeWorld()
        w.launcherRunning = running
        if running { w.serve("/readyz", 200, FakeWorld.readyBody) }
        w.onRun = { world, command in
            if command.first == "/usr/bin/open" {
                world.serve("/readyz", 200, FakeWorld.readyBody)
                world.launcherRunning = true
            }
            if command.first == "/usr/bin/osascript" {
                world.stopServing()
                world.launcherRunning = false
            }
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
        // the launcher can wait 90 seconds on the Documents-permission prompt and
        // then 60 for the engine, so the tool waits 160: 320 polls of half a second
        let w = FakeWorld()          // open succeeds, and nothing ever serves
        do {
            _ = try await Launcher.start(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .environment)
            XCTAssertEqual(f.message, "The engine did not answer within 160 seconds.")
            XCTAssertEqual(
                f.hint,
                "Run `tecopa logs`. The launcher shows an alert when it cannot start the engine, "
                    + "and macOS may be waiting for a Documents-folder permission click.")
        } catch { XCTFail("\(error)") }
        XCTAssertEqual(w.commands, [open])
        XCTAssertEqual(w.requests.count, 321)       // one look before `open`, then 320 polls
    }

    func testStartOverAForeignAnswerRunsNoCommand() async {
        let w = world(running: false)
        w.serve("/readyz", 200, "<html>hello</html>")
        do {
            _ = try await Launcher.start(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .environment)
            XCTAssertTrue(f.message.contains("not Tecopa Plateworks"), f.message)
        } catch { XCTFail("\(error)") }
        XCTAssertEqual(w.commands, [])
    }

    func testStartOverAPortThatDoesNotAnswerInTimeRunsNoCommand() async {
        // an engine that is busy with a render is not a stopped engine: opening the
        // launcher on it would be a second owner
        let w = world(running: false)
        w.timeOut("/readyz")
        do {
            _ = try await Launcher.start(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .engineUnreachable)
            XCTAssertEqual(f.message, "Something on port 8848 accepts connections but did not answer.")
            XCTAssertEqual(f.hint, "An engine may be busy with a render. Run `tecopa logs`.")
        } catch { XCTFail("\(error)") }
        XCTAssertEqual(w.commands, [])
    }

    func testAnEngineThatIsSlowAfterOpenIsNotReadyYet() async throws {
        let w = FakeWorld()
        w.onRun = { world, command in
            if command.first == "/usr/bin/open" { world.timeOut("/readyz") }
        }
        var runtime = w.runtime()
        runtime.sleep = { _ in
            // the look before `open`, then three polls that time out
            if w.requests.count == 4 {
                w.stopServing()
                w.serve("/readyz", 200, FakeWorld.readyBody)
            }
        }
        let out = try await Launcher.start(runtime)
        XCTAssertEqual(out["started"], .bool(true))
        XCTAssertEqual(w.requests.count, 5)
        XCTAssertEqual(w.commands, [open])
    }

    func testStopQuitsTheLauncherAndWaitsForThePortAndTheProcess() async throws {
        let w = world(running: true)
        let out = try await Launcher.stop(w.runtime())
        // the full argv: which process is looked for, and which app is told to quit
        XCTAssertEqual(w.commands, [pgrep, quit, pgrep])
        XCTAssertEqual(out, .object(["stopped": .bool(true), "running": .bool(false)]))
    }

    func testStopPollsUntilTheLauncherProcessIsGone() async throws {
        // the port closes first, and the app needs two more looks to exit
        let w = FakeWorld()
        w.launcherRunning = true
        w.serve("/readyz", 200, FakeWorld.readyBody)
        w.onRun = { world, command in
            if command.first == "/usr/bin/osascript" { world.stopServing() }
            if world.commands.count == 4 { world.launcherRunning = false }
        }
        let out = try await Launcher.stop(w.runtime())
        XCTAssertEqual(w.commands, [pgrep, quit, pgrep, pgrep, pgrep])
        XCTAssertEqual(out["stopped"], .bool(true))
        XCTAssertNil(out["note"])
    }

    func testStopSaysWhenTheLauncherProcessIsStillExiting() async throws {
        let w = FakeWorld()
        w.launcherRunning = true
        w.serve("/readyz", 200, FakeWorld.readyBody)
        w.onRun = { world, command in
            if command.first == "/usr/bin/osascript" { world.stopServing() }
        }
        let out = try await Launcher.stop(w.runtime())
        XCTAssertEqual(w.commands, [pgrep, quit] + Array(repeating: pgrep, count: 10))
        XCTAssertEqual(out["stopped"], .bool(true))
        XCTAssertEqual(out["running"], .bool(false))
        XCTAssertEqual(out["note"]?.stringValue, "The launcher process is still exiting.")
    }

    func testStopWhenNothingRunsIsData() async throws {
        let w = world(running: false)
        let out = try await Launcher.stop(w.runtime())
        XCTAssertEqual(w.commands, [pgrep])
        XCTAssertEqual(out["stopped"], .bool(false))
        XCTAssertEqual(out["note"]?.stringValue, "The launcher is not running.")
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

    func testAPgrepFaultIsNotAStoppedLauncher() async {
        // pgrep exits 1 for "no match". Any other code says nothing about the launcher.
        let w = world(running: true)
        w.result(for: "pgrep", ProcessResult(exitCode: 3, stdout: "", stderr: "pgrep: internal error\n"))
        do {
            _ = try await Launcher.stop(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .environment)
            XCTAssertEqual(f.message, "pgrep failed with exit 3: pgrep: internal error")
        } catch { XCTFail("\(error)") }
        XCTAssertEqual(w.commands, [pgrep])          // no osascript
    }

    func testAPortThatDoesNotAnswerInTimeIsStillThereForStop() async {
        let w = FakeWorld()
        w.launcherRunning = true
        w.serve("/readyz", 200, FakeWorld.readyBody)
        w.onRun = { world, command in
            if command.first == "/usr/bin/osascript" {
                world.stopServing()
                world.timeOut("/readyz")
            }
        }
        do {
            _ = try await Launcher.stop(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .refused)
            XCTAssertTrue(f.message.contains("still answers"), f.message)
        } catch { XCTFail("\(error)") }
        XCTAssertEqual(w.commands, [pgrep, quit])
        XCTAssertEqual(w.requests.count, 24)
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

    func testRestartWaitsForTheProcessToExitBeforeItOpensTheLauncher() async throws {
        let w = world(running: true)
        let out = try await Launcher.restart(w.runtime())
        XCTAssertEqual(w.commands, [pgrep, quit, pgrep, open])
        XCTAssertEqual(out["stop"]?["stopped"], .bool(true))
        XCTAssertEqual(out["start"]?["started"], .bool(true))
        XCTAssertEqual(out["start"]?["running"], .bool(true))
    }

    func testTheProcessPatternMatchesTheLauncherAndNoOtherCommandLine() throws {
        // pgrep -f reads the pattern as an extended regular expression over the full
        // command line. These cases have the same meaning in NSRegularExpression.
        XCTAssertEqual(Launcher.processPattern, pgrep[2])
        let pattern = try NSRegularExpression(pattern: Launcher.processPattern)
        func matches(_ line: String) -> Bool {
            pattern.firstMatch(in: line, range: NSRange(line.startIndex..., in: line)) != nil
        }
        let binary = "/Applications/Tecopa Plateworks.app/Contents/MacOS/TecopaPlateworks"
        XCTAssertTrue(matches(binary))
        XCTAssertTrue(matches(binary + " -psn_0_12345"))
        XCTAssertFalse(matches("/usr/bin/vim " + binary))
        XCTAssertFalse(matches("/usr/bin/pgrep -f " + binary))
        XCTAssertFalse(matches(binary + "Helper"))
        XCTAssertFalse(matches("/Users/dom" + binary))
        XCTAssertFalse(matches("/Applications/Tecopa PlateworksXapp/Contents/MacOS/TecopaPlateworks"))
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
