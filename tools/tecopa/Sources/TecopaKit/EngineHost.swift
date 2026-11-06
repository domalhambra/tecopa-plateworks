import Foundation

/// The app's side of the engine (spec 5.5): who holds the port, the data folders and
/// the seed, the spawn, the readiness wait and the stop. Foundation only.
public enum EngineHost {
    /// What `/readyz` on the port says: the engine (adopt it), another program, a
    /// port that is held and silent, or nothing.
    public enum PortState: Equatable, Sendable { case adopt, foreign, busy, none }
    public enum Started: Equatable, Sendable { case adopted, owned(pid: Int32) }

    public static let readyTimeout: Double = 60
    public static let stopGrace: Double = 5
    static let pollInterval: Double = 0.5
    static let stopPoll: Double = 0.1

    /// The one definition of who holds the port. A 503 with the engine's shape is the
    /// engine: a plate that is not cached is not an engine that is down.
    public static func classify(_ runtime: Runtime) async -> PortState {
        switch await runtime.client.probe("/readyz", timeout: 2) {
        case .reply(let reply): return EngineClient.isTecopa(reply) ? .adopt : .foreign
        case .timedOut: return .busy
        case .noAnswer: return .none
        }
    }

    /// Make the data root and its `regions`, `blobs` and `uploads`, then seed the
    /// bundle's plates. A repo layout has no bundle to seed from.
    public static func prepareData(layout: EngineLayout, home: String, bundleVersion: String,
                                   fileManager: FileManager = .default) throws -> SeedReport {
        let root = layout.dataRoot(home: home)
        for folder in [root, root + "/regions", root + "/blobs", root + "/uploads"] {
            do {
                try fileManager.createDirectory(atPath: folder, withIntermediateDirectories: true)
            } catch {
                throw TecopaFailure(.environment,
                                    "Could not make the folder \(folder): \(error.localizedDescription)")
            }
        }
        guard case .bundle = layout else { return SeedReport() }
        return try PlateSeeder.seed(bundlePlates: URL(fileURLWithPath: layout.platesRoot),
                                    regionsRoot: URL(fileURLWithPath: root + "/regions"),
                                    bundleVersion: bundleVersion, fileManager: fileManager)
    }

    /// Adopt an engine that answers, or spawn one and wait for it. `onSpawn` gets
    /// the pid before the wait, so a quit while the engine starts can stop it.
    /// `onExit` fires whenever the child exits, during the wait or after.
    public static func start(layout: EngineLayout, runtime: Runtime, spawner: any EngineSpawning,
                             environment: [String: String],
                             onSpawn: @escaping @Sendable (Int32) -> Void = { _ in },
                             onExit: @escaping @Sendable (Int32) -> Void = { _ in }) async throws -> Started {
        let port = runtime.port
        switch await classify(runtime) {
        case .adopt:
            return .adopted
        case .foreign:
            throw TecopaFailure(.environment, "Port \(port) is in use by another program.")
        case .busy:
            throw TecopaFailure(.engineUnreachable, "An engine on port \(port) is not answering.")
        case .none:
            break
        }
        let command = EngineEnvironment.command(layout: layout, port: port)
        let exited = ExitFlag()
        let pid = try spawner.spawn(command.executable, command.arguments,
                                    cwd: layout.dataRoot(home: runtime.home), environment: environment,
                                    logPath: runtime.logPath) { status in
            exited.set()
            onExit(status)
        }
        onSpawn(pid)
        let hint = "Read the log: " + runtime.logPath
        for _ in 0..<Int(readyTimeout / pollInterval) {
            if exited.isSet {
                throw TecopaFailure(.engineUnreachable, "The engine exited before it answered.", hint: hint)
            }
            if await classify(runtime) == .adopt { return .owned(pid: pid) }
            await runtime.sleep(pollInterval)
        }
        if exited.isSet {
            throw TecopaFailure(.engineUnreachable, "The engine exited before it answered.", hint: hint)
        }
        try? await stop(pid: pid, runtime: runtime, spawner: spawner)
        throw TecopaFailure(.engineUnreachable,
                            "The engine did not answer within \(secondsText(readyTimeout)) seconds.",
                            hint: hint)
    }

    /// SIGTERM, up to 5 seconds for the child to end, then SIGKILL.
    public static func stop(pid: Int32, runtime: Runtime, spawner: any EngineSpawning) async throws {
        guard spawner.isRunning(pid) else { return }
        try spawner.signal(pid, SIGTERM)
        for _ in 0..<Int((stopGrace / stopPoll).rounded()) {
            if !spawner.isRunning(pid) { return }
            await runtime.sleep(stopPoll)
        }
        if spawner.isRunning(pid) { try spawner.signal(pid, SIGKILL) }
    }

    /// The jobs a quit would end. `.unknown` when the engine did not say.
    public static func activeJobs(_ runtime: Runtime) async -> JobsRead {
        await Launcher.readJobs(runtime)
    }
}

/// Set once by the child's exit, read by the wait, from different threads.
private final class ExitFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var value = false
    func set() { lock.withLock { value = true } }
    var isSet: Bool { lock.withLock { value } }
}
