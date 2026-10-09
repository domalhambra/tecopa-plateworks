import Foundation

/// Engine control. The launcher app owns uvicorn as a child process, so "start" opens
/// the app and "stop" quits it. The tool never starts an engine of its own: two
/// owners of one engine is the fault the launcher spec was written to prevent.
public enum Launcher {
    public static let appPath = "/Applications/Tecopa Plateworks.app"
    /// The launcher's engine port. `Runtime.defaultPort` is the one definition.
    public static let port = Runtime.defaultPort
    /// Matches the launcher's own process and nothing else. `pgrep -f` matches the
    /// full command line with an extended regular expression, so the pattern is
    /// anchored at the start, and the executable's name ends at a space or at the
    /// end. A process that only has the path in its arguments does not match.
    static let processPattern =
        "^" + appPath.replacingOccurrences(of: ".", with: "\\.")
        + "/Contents/MacOS/TecopaPlateworks( |$)"

    /// `busy`: the port accepts a connection and gives no answer in time.
    enum Serving { case tecopa, foreign, none, busy }

    static func probe(_ runtime: Runtime) async -> Serving {
        switch await runtime.client.probe("/readyz", timeout: 2) {
        case .reply(let reply): return EngineClient.isTecopa(reply) ? .tecopa : .foreign
        case .noAnswer: return .none
        case .timedOut: return .busy
        }
    }

    static func requireLauncherPort(_ runtime: Runtime) throws {
        guard runtime.port == port else {
            throw TecopaFailure(
                .usage, "Engine control applies only to the launcher's engine on port \(port).",
                hint: "Stop a development engine where it was started.")
        }
    }

    /// True if the launcher process exists. pgrep exits 0 for a match and 1 for no
    /// match. Any other code means pgrep could not do its work, and that is not
    /// "the launcher is not running".
    static func launcherRuns(_ runtime: Runtime) throws -> Bool {
        let found = try runtime.exec("/usr/bin/pgrep", ["-f", processPattern])
        switch found.exitCode {
        case 0: return true
        case 1: return false
        default:
            let said = found.stderr.trimmingCharacters(in: .whitespacesAndNewlines)
            throw TecopaFailure(.environment, "pgrep failed with exit \(found.exitCode): \(said)")
        }
    }

    public static func start(_ runtime: Runtime) async throws -> JSONValue {
        try requireLauncherPort(runtime)
        switch await probe(runtime) {
        case .tecopa:
            return .object([
                "started": .bool(false), "running": .bool(true),
                "note": .string("An engine already answers on port \(port)."),
            ])
        case .foreign:
            throw TecopaFailure(
                .environment, runtime.client.notTecopaMessage,
                hint: "Quit the other program on that port.")
        case .busy:
            // a slow engine is not a stopped one: a second launcher is not opened on it
            throw TecopaFailure(
                .engineUnreachable,
                "Something on port \(port) accepts connections but did not answer.",
                hint: "An engine may be busy with a render. Run `tecopa logs`.")
        case .none:
            break
        }
        guard runtime.fileExists(appPath) else {
            throw TecopaFailure(.environment, "The launcher is not installed at \(appPath).",
                                hint: "Run scripts/macos/build_app.sh --install.")
        }
        // -g: the launcher stays in the background. It still opens the studio in the
        // browser when the engine is ready; that is the launcher's own behaviour.
        let opened = try runtime.exec("/usr/bin/open", ["-g", appPath])
        guard opened.exitCode == 0 else {
            throw TecopaFailure(.environment, "macOS could not open the launcher: \(opened.stderr)")
        }
        // 160 seconds: the launcher can wait 90 on the macOS Documents-permission
        // prompt, and then 60 for the engine. `busy` is "not ready yet".
        for _ in 0..<320 {
            if await probe(runtime) == .tecopa {
                return .object(["started": .bool(true), "running": .bool(true)])
            }
            await runtime.sleep(0.5)
        }
        throw TecopaFailure(
            .environment, "The engine did not answer within 160 seconds.",
            hint: "Run `tecopa logs`. The launcher shows an alert when it cannot start the engine, "
                + "and macOS may be waiting for a Documents-folder permission click.")
    }

    /// The jobs a stop would end: those that run and those that wait for a slot.
    /// nil when the engine did not say, which is not the same as none.
    static func activeJobs(_ runtime: Runtime) async -> Int? {
        guard let rows = (try? await runtime.client.debug("/jobs"))?["jobs"]?.arrayValue else {
            return nil
        }
        return rows.filter { ["running", "queued"].contains($0["state"]?.stringValue ?? "") }.count
    }

    /// The sessions the engine holds, or nil when the engine did not say.
    static func heldSessions(_ runtime: Runtime) async -> Int? {
        (try? await runtime.client.debug("/sessions"))?["sessions"]?.arrayValue?.count
    }

    /// The engine keeps its jobs and its sessions in memory by default, so a stop
    /// ends them. A stop is refused while a job runs or waits, unless `force` is
    /// true. When the engine does not say what it holds (the gate is off, or the
    /// read fails), the tool cannot know, so the stop continues and says so.
    public static func stop(_ runtime: Runtime, force: Bool = false) async throws -> JSONValue {
        try requireLauncherPort(runtime)
        guard try launcherRuns(runtime) else {
            if await probe(runtime) != .none {
                throw TecopaFailure(
                    .refused, "An engine answers on port \(port), but the launcher is not running.",
                    hint: "The launcher did not start this engine. Stop it where it was started.")
            }
            return .object([
                "stopped": .bool(false), "running": .bool(false),
                "note": .string("The launcher is not running."),
            ])
        }
        let jobs = await activeJobs(runtime)
        if let jobs, jobs > 0, !force {
            throw TecopaFailure(
                .refused, "\(jobs) job(s) are running or queued. Stopping the engine ends them.",
                hint: "Wait for them (`tecopa jobs`), or stop with force.")
        }
        let sessions = await heldSessions(runtime)
        var notes: [String] = []
        if jobs == nil || sessions == nil {
            notes.append("The engine's jobs and sessions could not be read before the stop.")
        }
        let quit = try runtime.exec("/usr/bin/osascript", ["-e", "quit app \"Tecopa Plateworks\""])
        if quit.exitCode != 0 {
            let text = quit.stderr.lowercased()
            let denied = text.contains("1743") || text.contains("not authoriz") || text.contains("not permitted")
            throw TecopaFailure(
                .environment,
                denied ? "macOS did not allow the quit." : "The quit failed: \(quit.stderr)",
                hint: denied
                    ? "Allow the calling app to control Tecopa Plateworks: System Settings > Privacy & Security > Automation."
                    : nil)
        }
        // 12 seconds: the launcher gives the engine 5, then SIGKILL. `busy` is "still there".
        var closed = false
        for _ in 0..<24 {
            if await probe(runtime) == .none {
                closed = true
                break
            }
            await runtime.sleep(0.5)
        }
        guard closed else {
            throw TecopaFailure(
                .refused, "The engine still answers on port \(port) after the launcher quit.",
                hint: "The launcher adopted an engine that it did not start. Stop that engine where it was started.")
        }
        // The port closes before the app is gone. Wait for the process too, so that
        // an `open` that follows cannot reach an app that is still quitting.
        var out: [String: JSONValue] = ["stopped": .bool(true), "running": .bool(false)]
        if let jobs { out["jobs_ended"] = .int(Int64(jobs)) }
        if let sessions { out["sessions_ended"] = .int(Int64(sessions)) }
        var gone = false
        for _ in 0..<10 {
            if try !launcherRuns(runtime) {
                gone = true
                break
            }
            await runtime.sleep(0.5)
        }
        if !gone { notes.append("The launcher process is still exiting.") }
        if !notes.isEmpty { out["note"] = .string(notes.joined(separator: " ")) }
        return .object(out)
    }

    public static func restart(_ runtime: Runtime, force: Bool = false) async throws -> JSONValue {
        let stopped = try await stop(runtime, force: force)
        let started = try await start(runtime)
        return .object(["stop": stopped, "start": started])
    }

    static let forceParameter = EntryParameter(
        "force", .boolean, "Stop even when a job is running or queued.")

    static let entries: [CatalogEntry] = [
        CatalogEntry(
            name: "engine_start",
            summary: "Open the launcher app, which starts the engine on port \(port), and wait for it to answer.",
            readOnly: false
        ) { runtime, _ in try await start(runtime) },
        CatalogEntry(
            name: "engine_stop",
            summary: "Quit the launcher app, which stops the engine it started. "
                + "This ends every running job and every studio session that is held in memory. "
                + "Refuses while a job is running or queued, unless force is true.",
            readOnly: false,
            parameters: [forceParameter]
        ) { runtime, arguments in
            try await stop(runtime, force: arguments["force"]?.boolValue ?? false)
        },
        CatalogEntry(
            name: "engine_restart",
            summary: "Quit and reopen the launcher app, for example after a change to the engine's Python code. "
                + "This ends every running job and every studio session that is held in memory. "
                + "Refuses while a job is running or queued, unless force is true.",
            readOnly: false,
            parameters: [forceParameter]
        ) { runtime, arguments in
            try await restart(runtime, force: arguments["force"]?.boolValue ?? false)
        },
    ]
}
