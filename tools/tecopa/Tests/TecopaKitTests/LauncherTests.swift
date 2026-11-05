import XCTest
@testable import TecopaKit

final class LauncherTests: XCTestCase {
    private let open = ["/usr/bin/open", "-g", "/Applications/Tecopa Plateworks.app"]
    private let pgrep = [
        "/usr/bin/pgrep", "-f",
        #"/Tecopa Plateworks\.app/Contents/MacOS/TecopaPlateworks( |$)"#,
    ]
    private let quit = ["/usr/bin/osascript", "-e", "quit app id \"org.plateworks.tecopa\""]
    private static let marker = "/home/Library/Application Support/Tecopa Plateworks/.quit-forced"

    private static let noJobs = #"{"jobs":[]}"#
    private static let noSessions = #"{"sessions":[]}"#
    private static let oneRunningJob =
        #"{"jobs":[{"jid":"a","queue":"render","state":"running"},{"jid":"b","queue":"proof","state":"done"}]}"#
    private static let unreadNote = "The engine's jobs and sessions could not be read before the stop."

    /// A launcher-run engine: /readyz, and the two debug routes `stop` reads. The
    /// default is an engine that holds no job and no session, so a stop is clean.
    private static func serveEngine(_ w: FakeWorld, jobs: String = noJobs,
                                    sessions: String = noSessions) {
        w.serve("/readyz", 200, FakeWorld.readyBody)
        w.serve("/api/debug/jobs", 200, jobs)
        w.serve("/api/debug/sessions", 200, sessions)
    }

    /// A machine with the new app installed at /Applications.
    private static func machine() -> FakeWorld {
        let w = FakeWorld()
        w.app()
        return w
    }

    /// A machine where `open` starts the launcher and its engine, and `osascript`
    /// stops both.
    private func world(running: Bool) -> FakeWorld {
        let w = Self.machine()
        w.launcherRunning = running
        if running { Self.serveEngine(w) }
        w.onRun = { world, command in
            if command.first == "/usr/bin/open" {
                Self.serveEngine(world)
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

    func testStartFailsWhenTheAppIsNotInstalled() async {
        let w = world(running: false)
        var runtime = w.runtime()
        runtime.fileExists = { $0 != "/Applications/Tecopa Plateworks.app" }
        do {
            _ = try await Launcher.start(runtime)
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .environment)
            XCTAssertEqual(f.message, "Tecopa Plateworks is not installed at /Applications/Tecopa Plateworks.app.")
            XCTAssertNil(f.hint)
        } catch { XCTFail("\(error)") }
        XCTAssertEqual(w.commands, [])
    }

    func testStartFailsWhenTheEngineNeverAnswers() async {
        // the app waits 60 seconds for its engine, so the tool waits 70: 140 polls
        // of half a second. No Documents prompt any more.
        let w = Self.machine()          // open succeeds, and nothing ever serves
        do {
            _ = try await Launcher.start(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .environment)
            XCTAssertEqual(f.message, "The engine did not answer within 70 seconds.")
            XCTAssertEqual(
                f.hint, "Run `tecopa logs`. The app shows an alert when it cannot start the engine.")
            XCTAssertFalse(f.hint?.contains("Documents") ?? true)
        } catch { XCTFail("\(error)") }
        XCTAssertEqual(w.commands, [open])
        XCTAssertEqual(w.requests.count, 141)       // one look before `open`, then 140 polls
        XCTAssertEqual(w.clock, 70)
    }

    func testTheBundleIdIsTheNewOne() {
        XCTAssertEqual(Launcher.bundleID, "org.plateworks.tecopa")
        XCTAssertEqual(Launcher.appPath(FakeWorld().runtime()), "/Applications/Tecopa Plateworks.app")
    }

    func testTheAppPathFollowsTecopaApp() async throws {
        let w = world(running: false)
        var runtime = w.runtime()
        let dist = "/Users/dom/Tecopa Plateworks/dist/Tecopa Plateworks.app"
        runtime.environment["TECOPA_APP"] = dist
        w.app(dist)
        XCTAssertEqual(Launcher.appPath(runtime), dist)
        let out = try await Launcher.start(runtime)
        XCTAssertEqual(out["started"], .bool(true))
        // by path, never by bundle id: LaunchServices may hold several copies
        XCTAssertEqual(w.commands, [["/usr/bin/open", "-g", dist]])
    }

    func testInsideAnAppTheAppPathIsThatApp() {
        var runtime = world(running: false).runtime()
        runtime.layout = .bundle(URL(fileURLWithPath: "/Users/dom/x/dist/Tecopa Plateworks.app"))
        XCTAssertEqual(Launcher.appPath(runtime), "/Users/dom/x/dist/Tecopa Plateworks.app")
        runtime.environment["TECOPA_APP"] = "/Elsewhere/Tecopa Plateworks.app"
        XCTAssertEqual(Launcher.appPath(runtime), "/Elsewhere/Tecopa Plateworks.app")
    }

    func testAForcedStopLeavesTheQuitMarker() async throws {
        let w = world(running: true)
        Self.serveEngine(w, jobs: Self.oneRunningJob)
        w.existingFile(Self.marker)          // a stale marker from an earlier forced stop
        w.now = FakeWorld.date("2026-11-05T12:00:00Z")
        let out = try await Launcher.stop(w.runtime(), force: true)
        XCTAssertEqual(out["stopped"], .bool(true))
        XCTAssertEqual(w.removed, [Self.marker])
        XCTAssertEqual(w.written.map(\.path), [Self.marker])
        XCTAssertEqual(w.written.first.map { String(decoding: $0.data, as: UTF8.self) },
                       "2026-11-05T12:00:00Z\n")
        XCTAssertEqual(w.commands, [pgrep, quit, pgrep])

        // without force there is no marker: the tool already refused running jobs
        let plain = world(running: true)
        _ = try await Launcher.stop(plain.runtime())
        XCTAssertEqual(plain.written, [])
        XCTAssertEqual(plain.removed, [])
    }

    func testTheOldLauncherIsNeverOpenedOrQuit() async {
        // the old launcher still sits at /Applications: the tool refuses to drive it
        let message = "The app at /Applications/Tecopa Plateworks.app is the old launcher (guide.badwater.tecopa). "
            + "Set TECOPA_APP to the new build, or install it."
        for running in [false, true] {
            let w = world(running: running)
            w.app(id: "guide.badwater.tecopa")
            do {
                if running { _ = try await Launcher.stop(w.runtime(), force: true) }
                else { _ = try await Launcher.start(w.runtime()) }
                XCTFail("expected a failure")
            } catch let f as TecopaFailure {
                XCTAssertEqual(f.kind, .environment)
                XCTAssertEqual(f.message, message)
            } catch { XCTFail("\(error)") }
            XCTAssertEqual(w.commands, [], "running \(running)")
            XCTAssertEqual(w.written, [])
        }
        // restart goes through stop, so it refuses before the quit
        let w = world(running: true)
        w.app(id: "guide.badwater.tecopa")
        do {
            _ = try await Launcher.restart(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.message, message)
        } catch { XCTFail("\(error)") }
        XCTAssertEqual(w.commands, [])
    }

    func testAnAppWithNoReadableIdIsRefusedToo() async {
        let w = FakeWorld()          // the app exists, and its Info.plist reads as nothing
        do {
            _ = try await Launcher.start(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .environment)
            XCTAssertTrue(f.message.contains("(unidentified)"), f.message)
        } catch { XCTFail("\(error)") }
        XCTAssertEqual(w.commands, [])
    }

    func testAForcedStopMakesTheMarkerFolderWhenItIsMissing() async throws {
        let w = world(running: true)
        let folder = "/home/Library/Application Support/Tecopa Plateworks"
        _ = try await Launcher.stop(w.runtime(), force: true)
        XCTAssertEqual(w.madeFolders, [folder])
        XCTAssertEqual(w.written.map(\.path), [Self.marker])

        // a folder that exists is left alone
        let there = world(running: true)
        there.folder(folder)
        _ = try await Launcher.stop(there.runtime(), force: true)
        XCTAssertEqual(there.madeFolders, [])
        XCTAssertEqual(there.written.map(\.path), [Self.marker])
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
        let w = Self.machine()
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
        XCTAssertEqual(out, .object([
            "stopped": .bool(true), "running": .bool(false),
            "jobs_ended": .int(0), "sessions_ended": .int(0),
        ]))
        // the two reads come first, and the quit follows them
        XCTAssertEqual(w.requests.prefix(2).map(\.path), ["/api/debug/jobs", "/api/debug/sessions"])
    }

    func testStopPollsUntilTheLauncherProcessIsGone() async throws {
        // the port closes first, and the app needs two more looks to exit
        let w = Self.machine()
        w.launcherRunning = true
        Self.serveEngine(w)
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
        let w = Self.machine()
        w.launcherRunning = true
        Self.serveEngine(w)
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
        let w = Self.machine()
        w.launcherRunning = true
        Self.serveEngine(w)
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
        // the two reads before the quit, then 24 polls of the port
        XCTAssertEqual(w.requests.filter { $0.path == "/readyz" }.count, 24)
        XCTAssertEqual(w.requests.count, 26)
    }

    func testStopNamesTheAutomationPermissionWhenMacOSDeniesTheQuit() async {
        let w = Self.machine()
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

    func testStopRefusesWhileAJobRunsAndRunsNoQuit() async {
        // the engine keeps jobs and sessions in memory, so a stop ends them
        let w = world(running: true)
        Self.serveEngine(w, jobs: Self.oneRunningJob)
        do {
            _ = try await Launcher.stop(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .refused)
            XCTAssertEqual(f.message, "1 job(s) are running or queued. Stopping the engine ends them.")
            XCTAssertEqual(f.hint, "Wait for them (`tecopa jobs`), or stop with force.")
        } catch { XCTFail("\(error)") }
        XCTAssertEqual(w.commands, [pgrep])          // no osascript
    }

    func testAQueuedJobCountsAndAFinishedJobDoesNot() async {
        let w = world(running: true)
        Self.serveEngine(w, jobs: #"{"jobs":[{"state":"queued"},{"state":"running"},{"state":"done"},{"state":"error"}]}"#)
        do {
            _ = try await Launcher.stop(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .refused)
            XCTAssertEqual(f.message, "2 job(s) are running or queued. Stopping the engine ends them.")
        } catch { XCTFail("\(error)") }
        XCTAssertEqual(w.commands, [pgrep])

        // jobs that ended do not hold the stop
        let done = world(running: true)
        Self.serveEngine(done, jobs: #"{"jobs":[{"state":"done"},{"state":"error"}]}"#)
        let out = try? await Launcher.stop(done.runtime())
        XCTAssertEqual(out?["stopped"], .bool(true))
        XCTAssertEqual(out?["jobs_ended"], .int(0))
    }

    func testStopWithForceQuitsAndCountsTheJobsItEnded() async throws {
        let w = world(running: true)
        Self.serveEngine(w, jobs: Self.oneRunningJob)
        let out = try await Launcher.stop(w.runtime(), force: true)
        XCTAssertEqual(w.commands, [pgrep, quit, pgrep])
        XCTAssertEqual(out["stopped"], .bool(true))
        XCTAssertEqual(out["jobs_ended"], .int(1))
        XCTAssertEqual(out["sessions_ended"], .int(0))
        XCTAssertNil(out["note"])
    }

    func testStopCountsTheSessionsItEnded() async throws {
        let w = world(running: true)
        Self.serveEngine(w, sessions: #"{"sessions":[{"sid":"ab"},{"sid":"cd"}]}"#)
        let out = try await Launcher.stop(w.runtime())
        XCTAssertEqual(w.commands, [pgrep, quit, pgrep])
        XCTAssertEqual(out["jobs_ended"], .int(0))
        XCTAssertEqual(out["sessions_ended"], .int(2))
        XCTAssertNil(out["note"])
    }

    func testStopWithTheGateOffStillStopsAndSaysWhatItCouldNotRead() async throws {
        // the tool cannot know what the engine holds, so it does not refuse
        let w = world(running: true)
        w.serve("/api/debug/jobs", 404, #"{"detail":"Not Found"}"#)
        w.serve("/api/debug/sessions", 404, #"{"detail":"Not Found"}"#)
        let out = try await Launcher.stop(w.runtime())
        XCTAssertEqual(w.commands, [pgrep, quit, pgrep])
        XCTAssertEqual(out, .object([
            "stopped": .bool(true), "running": .bool(false), "note": .string(Self.unreadNote),
        ]))
    }

    func testStopWithOneReadThatFailsReportsTheOtherAndTheNote() async throws {
        let w = world(running: true)
        w.serve("/api/debug/sessions", 500, "Internal Server Error")
        var out = try await Launcher.stop(w.runtime())
        XCTAssertEqual(out["stopped"], .bool(true))
        XCTAssertEqual(out["jobs_ended"], .int(0))
        XCTAssertNil(out["sessions_ended"])
        XCTAssertEqual(out["note"]?.stringValue, Self.unreadNote)

        // a reply that is not the route's shape is not a count of zero
        let odd = world(running: true)
        Self.serveEngine(odd, jobs: "[]", sessions: #"{"sessions":[{"sid":"ab"}]}"#)
        out = try await Launcher.stop(odd.runtime())
        XCTAssertNil(out["jobs_ended"])
        XCTAssertEqual(out["sessions_ended"], .int(1))
        XCTAssertEqual(out["note"]?.stringValue, Self.unreadNote)
    }

    func testTheUnreadNoteJoinsTheStillExitingNote() async throws {
        let w = Self.machine()
        w.launcherRunning = true
        w.serve("/readyz", 200, FakeWorld.readyBody)
        w.onRun = { world, command in
            if command.first == "/usr/bin/osascript" { world.stopServing() }
        }
        let out = try await Launcher.stop(w.runtime())
        XCTAssertEqual(out["stopped"], .bool(true))
        XCTAssertEqual(out["note"]?.stringValue,
                       Self.unreadNote + " The launcher process is still exiting.")
    }

    func testRestartRefusesWhileAJobRunsAndOpensNothing() async {
        let w = world(running: true)
        Self.serveEngine(w, jobs: Self.oneRunningJob)
        do {
            _ = try await Launcher.restart(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .refused)
            XCTAssertTrue(f.message.hasPrefix("1 job(s) are running or queued."), f.message)
        } catch { XCTFail("\(error)") }
        XCTAssertEqual(w.commands, [pgrep])          // no osascript, and no open
    }

    func testRestartPassesForceToTheStop() async throws {
        let w = world(running: true)
        Self.serveEngine(w, jobs: Self.oneRunningJob)
        let out = try await Launcher.restart(w.runtime(), force: true)
        XCTAssertEqual(w.commands, [pgrep, quit, pgrep, open])
        XCTAssertEqual(out["stop"]?["jobs_ended"], .int(1))
        XCTAssertEqual(out["start"]?["started"], .bool(true))
    }

    func testForceReachesStopAndRestartThroughTheCatalog() async {
        for name in ["engine_stop", "engine_restart"] {
            // the wrong kind is refused, never read as false
            var w = world(running: true)
            Self.serveEngine(w, jobs: Self.oneRunningJob)
            var (env, failure) = await Catalog.call(name, w.runtime(), ["force": .string("yes")])
            XCTAssertEqual(failure?.kind, .usage, name)
            XCTAssertEqual(failure?.message, "force must be a boolean.", name)
            XCTAssertEqual(w.commands, [], name)
            XCTAssertEqual(w.requests, [], name)

            (env, failure) = await Catalog.call(name, w.runtime(), [:])
            XCTAssertEqual(failure?.kind, .refused, name)
            (env, failure) = await Catalog.call(name, w.runtime(), ["force": .bool(false)])
            XCTAssertEqual(failure?.kind, .refused, name)
            XCTAssertEqual(w.commands, [pgrep, pgrep], name)

            w = world(running: true)
            Self.serveEngine(w, jobs: Self.oneRunningJob)
            (env, failure) = await Catalog.call(name, w.runtime(), ["force": .bool(true)])
            XCTAssertNil(failure, name)
            let stopped = name == "engine_stop" ? env["data"] : env["data"]?["stop"]
            XCTAssertEqual(stopped?["jobs_ended"], .int(1), name)
        }
    }

    func testTheControlSummariesStateWhatAStopEnds() {
        XCTAssertEqual(Launcher.port, Runtime.defaultPort)
        XCTAssertEqual(
            Catalog.named("engine_start")?.summary,
            "Open the Tecopa Plateworks app, which starts the engine on port 8848, and wait for it to answer.")
        XCTAssertEqual(
            Catalog.named("engine_stop")?.summary,
            "Quit the Tecopa Plateworks app, which stops the engine it started. This ends every running job "
                + "and every studio session that is held in memory. Refuses while a job is running "
                + "or queued, unless force is true.")
        XCTAssertEqual(
            Catalog.named("engine_restart")?.summary,
            "Quit and reopen the Tecopa Plateworks app, for example after a change to the engine's Python "
                + "code. This ends every running job and every studio session that is held in memory. "
                + "Refuses while a job is running or queued, unless force is true.")
        for name in ["engine_stop", "engine_restart"] {
            let parameters = Catalog.named(name)?.parameters ?? []
            XCTAssertEqual(parameters.map(\.name), ["force"], name)
            XCTAssertEqual(parameters.first?.kind, .boolean, name)
            XCTAssertEqual(parameters.first?.summary, "Stop even when a job is running or queued.", name)
        }
        XCTAssertEqual(Catalog.named("engine_start")?.parameters.count, 0)
    }

    func testRestartWaitsForTheProcessToExitBeforeItOpensTheLauncher() async throws {
        let w = world(running: true)
        let out = try await Launcher.restart(w.runtime())
        XCTAssertEqual(w.commands, [pgrep, quit, pgrep, open])
        XCTAssertEqual(out["stop"]?["stopped"], .bool(true))
        XCTAssertEqual(out["start"]?["started"], .bool(true))
        XCTAssertEqual(out["start"]?["running"], .bool(true))
    }

    func testTheProcessPatternMatchesADistCopy() throws {
        // pgrep -f reads the pattern as an extended regular expression over the full
        // command line. These cases have the same meaning in NSRegularExpression.
        // Unanchored, so a dist/ build of the app counts as the app.
        XCTAssertEqual(Launcher.processPattern, pgrep[2])
        let pattern = try NSRegularExpression(pattern: Launcher.processPattern)
        func matches(_ line: String) -> Bool {
            pattern.firstMatch(in: line, range: NSRange(line.startIndex..., in: line)) != nil
        }
        let binary = "/Applications/Tecopa Plateworks.app/Contents/MacOS/TecopaPlateworks"
        XCTAssertTrue(matches(binary))
        XCTAssertTrue(matches(binary + " -psn_0_12345"))
        XCTAssertTrue(matches(
            "/Users/dom/Documents/Claude/20-29 Properties/25 Tecopa Plateworks/dist/Tecopa Plateworks.app"
                + "/Contents/MacOS/TecopaPlateworks"))
        XCTAssertFalse(matches(binary + "Helper"))
        XCTAssertFalse(matches("/Applications/Tecopa PlateworksXapp/Contents/MacOS/TecopaPlateworks"))
        XCTAssertFalse(matches("/Applications/Other.app/Contents/MacOS/Other"))
        XCTAssertFalse(matches("/Users/dom/.venv/bin/python -m uvicorn app.main:app --port 8848"))
    }

    func testControlRefusesAnyPortExcept8848() async {
        let w = world(running: false)
        for name in ["engine_start", "engine_stop", "engine_restart"] {
            let (_, failure) = await Catalog.call(name, w.runtime(port: 8000), [:])
            XCTAssertEqual(failure?.kind, .usage, name)
        }
        XCTAssertEqual(w.commands, [])
    }

    func testStopRefusesWhenTheJobsReadTimesOut() async {
        // a long render can hold the engine so that it does not answer; that render is
        // exactly the work a stop would end, so "no answer in time" must not read as "no jobs"
        let w = world(running: true)
        w.timeOut("/api/debug/jobs")
        do {
            _ = try await Launcher.stop(w.runtime())
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .refused)
            XCTAssertTrue(f.message.contains("busy with a render"))
            XCTAssertEqual(w.commands.map { $0[0] }, ["/usr/bin/pgrep"])
        } catch { XCTFail("\(error)") }
    }

    func testForceStopsAnEngineWhoseJobsReadTimesOut() async throws {
        let w = world(running: true)
        w.timeOut("/api/debug/jobs")
        let out = try await Launcher.stop(w.runtime(), force: true)
        XCTAssertEqual(out["stopped"], .bool(true))
        XCTAssertNil(out["jobs_ended"])
        XCTAssertTrue(out["note"]?.stringValue?.contains("could not be read") ?? false)
    }

}
