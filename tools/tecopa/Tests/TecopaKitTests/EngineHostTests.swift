import XCTest
@testable import TecopaKit

/// A spawner over no real process: it records each spawn and each signal. SIGTERM
/// ends the child unless `ignoresSigterm`; SIGKILL always does. Each end calls the
/// child's `onExit`, as the real one does.
final class FakeSpawner: EngineSpawning, @unchecked Sendable {
    struct Spawn: Equatable {
        let executable: String
        let arguments: [String]
        let cwd: String
        let environment: [String: String]
        let logPath: String
    }

    private let lock = NSLock()
    private var exits: [Int32: @Sendable (Int32) -> Void] = [:]
    private var running: Set<Int32> = []
    private(set) var spawns: [Spawn] = []
    private(set) var signals: [Int32] = []
    var ignoresSigterm = false
    /// The child exits with this status the moment it is spawned.
    var exitAtOnce: Int32?
    let pid: Int32 = 5001

    func spawn(_ executable: String, _ arguments: [String], cwd: String, environment: [String: String],
               logPath: String, onExit: @escaping @Sendable (Int32) -> Void) throws -> Int32 {
        lock.withLock {
            spawns.append(Spawn(executable: executable, arguments: arguments, cwd: cwd,
                                environment: environment, logPath: logPath))
            exits[pid] = onExit
            running.insert(pid)
        }
        if let exitAtOnce { exit(pid, exitAtOnce) }
        return pid
    }

    /// The child ends with this status.
    func exit(_ pid: Int32, _ status: Int32) {
        let handler: ((Int32) -> Void)? = lock.withLock {
            guard running.remove(pid) != nil else { return nil }
            return exits[pid]
        }
        handler?(status)
    }

    func isRunning(_ pid: Int32) -> Bool { lock.withLock { running.contains(pid) } }

    func signal(_ pid: Int32, _ signal: Int32) throws {
        let ends: Bool = lock.withLock {
            signals.append(signal)
            return signal == SIGKILL || (signal == SIGTERM && !ignoresSigterm)
        }
        if ends { exit(pid, 128 + signal) }
    }
}

/// Records what reached it, across threads.
final class Box<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: T
    init(_ value: T) { stored = value }
    var value: T {
        get { lock.withLock { stored } }
        set { lock.withLock { stored = newValue } }
    }
}

final class EngineHostTests: XCTestCase {
    private let layout = EngineLayout.bundle(URL(fileURLWithPath: "/dist/Tecopa Plateworks.app"))
    private let notReady = #"{"ready":false,"regions":[{"id":"lassen_ca","dem_present":false}]}"#
    private let environment = ["PATH": "/usr/bin", "TECOPA_DEBUG": "1"]

    private func start(_ w: FakeWorld, _ spawner: FakeSpawner, runtime: Runtime? = nil,
                       onSpawn: @escaping @Sendable (Int32) -> Void = { _ in },
                       onExit: @escaping @Sendable (Int32) -> Void = { _ in }) async throws
        -> EngineHost.Started {
        try await EngineHost.start(layout: layout, runtime: runtime ?? w.runtime(), spawner: spawner,
                                   environment: environment, onSpawn: onSpawn, onExit: onExit)
    }

    private func expectFailure(_ kind: TecopaFailure.Kind, _ message: String, hint: String? = nil,
                               _ body: () async throws -> Void) async {
        do {
            try await body()
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, kind)
            XCTAssertEqual(f.message, message)
            if let hint { XCTAssertEqual(f.hint, hint) }
        } catch { XCTFail("\(error)") }
    }

    // MARK: classify

    func testAnEngineShapedReplyIsAdopted() async {
        let w = FakeWorld()
        w.serve("/readyz", 200, FakeWorld.readyBody)
        let state = await EngineHost.classify(w.runtime())
        XCTAssertEqual(state, .adopt)
    }

    func testA503WithTheEngineShapeIsStillTheEngine() async {
        let w = FakeWorld()
        w.serve("/readyz", 503, notReady)
        let state = await EngineHost.classify(w.runtime())
        XCTAssertEqual(state, .adopt)
    }

    func testAnotherProgramIsForeign() async {
        let w = FakeWorld()
        w.serve("/readyz", 200, "<html>hello</html>")
        let state = await EngineHost.classify(w.runtime())
        XCTAssertEqual(state, .foreign)
    }

    func testAPortThatTimesOutIsBusy() async {
        let w = FakeWorld()
        w.timeOut("/readyz")
        let state = await EngineHost.classify(w.runtime())
        XCTAssertEqual(state, .busy)
    }

    func testNothingListeningIsNone() async {
        let state = await EngineHost.classify(FakeWorld().runtime())
        XCTAssertEqual(state, .none)
    }

    func testLauncherProbeAndClassifyAgree() async {
        let cases: [(FakeWorld) -> Void] = [
            { $0.serve("/readyz", 200, FakeWorld.readyBody) },
            { $0.serve("/readyz", 503, self.notReady) },
            { $0.serve("/readyz", 200, "<html>hello</html>") },
            { $0.timeOut("/readyz") },
            { _ in },
        ]
        for (index, setUp) in cases.enumerated() {
            let w = FakeWorld()
            setUp(w)
            let state = await EngineHost.classify(w.runtime())
            let serving = await Launcher.probe(w.runtime())
            let expected: Launcher.Serving
            switch state {
            case .adopt: expected = .tecopa
            case .foreign: expected = .foreign
            case .busy: expected = .busy
            case .none: expected = .none
            }
            XCTAssertEqual(serving, expected, "case \(index)")
        }
    }

    // MARK: start

    func testStartOverAdoptForeignOrBusySpawnsNothing() async throws {
        var w = FakeWorld()
        w.serve("/readyz", 503, notReady)
        var spawner = FakeSpawner()
        let started = try await start(w, spawner)
        XCTAssertEqual(started, .adopted)
        XCTAssertEqual(spawner.spawns, [])

        w = FakeWorld()
        w.serve("/readyz", 200, "<html>hello</html>")
        spawner = FakeSpawner()
        await expectFailure(.environment, "Port 8848 is in use by another program.") {
            _ = try await self.start(w, spawner)
        }
        XCTAssertEqual(spawner.spawns, [])

        w = FakeWorld()
        w.timeOut("/readyz")
        spawner = FakeSpawner()
        await expectFailure(.engineUnreachable, "An engine on port 8848 is not answering.") {
            _ = try await self.start(w, spawner)
        }
        XCTAssertEqual(spawner.spawns, [])
    }

    func testStartSpawnsTheSpecsCommandInTheDataRoot() async throws {
        let w = FakeWorld()
        w.serveSteps("/readyz", [.noAnswer, .answer(200, FakeWorld.readyBody)])
        let spawner = FakeSpawner()
        let started = try await start(w, spawner)
        XCTAssertEqual(started, .owned(pid: 5001))
        let resources = "/dist/Tecopa Plateworks.app/Contents/Resources"
        XCTAssertEqual(spawner.spawns, [FakeSpawner.Spawn(
            executable: resources + "/python-engine/bin/python3.14",
            arguments: ["-P", "-m", "uvicorn", "app.main:app", "--app-dir", resources + "/engine",
                        "--host", "127.0.0.1", "--port", "8848"],
            cwd: "/home/Library/Application Support/Tecopa Plateworks",
            environment: environment,
            logPath: "/home/Library/Logs/TecopaPlateworks.log")])
        XCTAssertEqual(w.requests.count, 2)
    }

    func testTheWaitAcceptsA503WithTheEngineShape() async throws {
        let w = FakeWorld()
        w.serveSteps("/readyz", [.noAnswer, .timedOut, .answer(503, notReady)])
        let started = try await start(w, FakeSpawner())
        XCTAssertEqual(started, .owned(pid: 5001))
        XCTAssertEqual(w.requests.count, 3)
        XCTAssertEqual(w.clock, 0.5)
    }

    func testTheWaitIgnoresAForeignReplyAndGivesUpAfter60Seconds() async {
        let w = FakeWorld()
        w.serveSteps("/readyz", [.noAnswer, .answer(200, "<html>hello</html>")])
        let spawner = FakeSpawner()
        await expectFailure(.engineUnreachable, "The engine did not answer within 60 seconds.",
                            hint: "Read the log: /home/Library/Logs/TecopaPlateworks.log") {
            _ = try await self.start(w, spawner)
        }
        XCTAssertEqual(w.clock, 60)
        XCTAssertEqual(w.requests.count, 121)
        XCTAssertEqual(spawner.signals, [SIGTERM])
    }

    func testAnEngineThatExitsDuringTheWaitFailsAtOnce() async {
        let w = FakeWorld()
        let spawner = FakeSpawner()
        spawner.exitAtOnce = 1
        await expectFailure(.engineUnreachable, "The engine exited before it answered.",
                            hint: "Read the log: /home/Library/Logs/TecopaPlateworks.log") {
            _ = try await self.start(w, spawner)
        }
        XCTAssertEqual(w.requests.count, 1)      // the classify only
        XCTAssertEqual(w.clock, 0)
        XCTAssertEqual(spawner.signals, [])
    }

    func testOnSpawnFiresBeforeTheWait() async throws {
        let w = FakeWorld()
        w.serveSteps("/readyz", [.noAnswer, .answer(200, FakeWorld.readyBody)])
        let seen = Box<[Int]>([])
        let pid = Box<Int32>(0)
        _ = try await start(w, FakeSpawner(), onSpawn: { spawned in
            pid.value = spawned
            seen.value.append(w.requests.count)
        })
        XCTAssertEqual(pid.value, 5001)
        XCTAssertEqual(seen.value, [1])          // after the classify, before the first poll
    }

    func testAChildStillStartingCanBeStopped() async {
        // Review Focus 5: a quit while the engine starts stops the child
        let w = FakeWorld()
        let spawner = FakeSpawner()
        let pid = Box<Int32>(0)
        var runtime = w.runtime()
        let stopped = Box(false)
        runtime.sleep = { _ in
            guard !stopped.value else { return }
            stopped.value = true
            try? await EngineHost.stop(pid: pid.value, runtime: w.runtime(), spawner: spawner)
        }
        await expectFailure(.engineUnreachable, "The engine exited before it answered.") {
            _ = try await self.start(w, spawner, runtime: runtime, onSpawn: { pid.value = $0 })
        }
        XCTAssertEqual(spawner.signals, [SIGTERM])
        XCTAssertFalse(spawner.isRunning(5001))
    }

    func testOnExitFiresAfterTheEngineIsUp() async throws {
        let w = FakeWorld()
        w.serveSteps("/readyz", [.noAnswer, .answer(200, FakeWorld.readyBody)])
        let spawner = FakeSpawner()
        let status = Box<Int32?>(nil)
        let started = try await start(w, spawner, onExit: { status.value = $0 })
        XCTAssertEqual(started, .owned(pid: 5001))
        XCTAssertNil(status.value)
        spawner.exit(5001, 1)
        XCTAssertEqual(status.value, 1)
    }

    // MARK: stop

    func testStopSendsSigtermAndWaitsUpTo5Seconds() async throws {
        let w = FakeWorld()
        let spawner = FakeSpawner()
        _ = try spawner.spawn("/py", [], cwd: "/", environment: [:], logPath: "/log", onExit: { _ in })
        try await EngineHost.stop(pid: 5001, runtime: w.runtime(), spawner: spawner)
        XCTAssertEqual(spawner.signals, [SIGTERM])
        XCTAssertEqual(w.clock, 0)
    }

    func testStopSendsSigkillAfter5Seconds() async throws {
        let w = FakeWorld()
        let spawner = FakeSpawner()
        spawner.ignoresSigterm = true
        _ = try spawner.spawn("/py", [], cwd: "/", environment: [:], logPath: "/log", onExit: { _ in })
        try await EngineHost.stop(pid: 5001, runtime: w.runtime(), spawner: spawner)
        XCTAssertEqual(spawner.signals, [SIGTERM, SIGKILL])
        XCTAssertEqual(w.clock, 5, accuracy: 1e-9)
        XCTAssertEqual(w.slept.count, 50)
        XCTAssertFalse(spawner.isRunning(5001))
    }

    // MARK: jobs

    func testActiveJobsCountsRunningAndQueued() async {
        var w = FakeWorld()
        w.serve("/api/debug/jobs", 200,
                #"{"jobs":[{"state":"running"},{"state":"queued"},{"state":"done"}]}"#)
        var read = await EngineHost.activeJobs(w.runtime())
        XCTAssertEqual(read, .active(2))

        w = FakeWorld()
        w.serve("/api/debug/jobs", 404, #"{"detail":"Not Found"}"#)
        read = await EngineHost.activeJobs(w.runtime())
        XCTAssertEqual(read, .unknown)

        read = await EngineHost.activeJobs(FakeWorld().runtime())
        XCTAssertEqual(read, .unknown)

        w = FakeWorld()
        w.timeOut("/api/debug/jobs")
        read = await EngineHost.activeJobs(w.runtime())
        XCTAssertEqual(read, .timedOut)
    }

    // MARK: data

    func testPrepareDataMakesTheFoldersBeforeSeeding() throws {
        // Review Focus 2: first launch, with no Application Support folder at all
        let fm = FileManager.default
        let top = fm.temporaryDirectory.appendingPathComponent("Engine Host \(UUID().uuidString)")
        defer { try? fm.removeItem(at: top) }
        let home = top.appendingPathComponent("home dir").path
        let app = top.appendingPathComponent("dist/Tecopa Plateworks.app")
        let plate = app.appendingPathComponent("Contents/Resources/plates/lassen_ca")
        try fm.createDirectory(at: plate, withIntermediateDirectories: true)
        try Data("{}".utf8).write(to: plate.appendingPathComponent("region.json"))
        try fm.createDirectory(atPath: home, withIntermediateDirectories: true)

        let report = try EngineHost.prepareData(layout: .bundle(app), home: home, bundleVersion: "74cbc38")
        let data = home + "/Library/Application Support/Tecopa Plateworks"
        for folder in ["", "/regions", "/blobs", "/uploads"] {
            var isFolder: ObjCBool = false
            XCTAssertTrue(fm.fileExists(atPath: data + folder, isDirectory: &isFolder), folder)
            XCTAssertTrue(isFolder.boolValue, folder)
        }
        XCTAssertEqual(report.created, ["lassen_ca"])
        XCTAssertTrue(fm.fileExists(atPath: data + "/regions/lassen_ca/region.json"))
    }
}
