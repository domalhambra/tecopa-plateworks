import Foundation

/// Engine control. The launcher app owns uvicorn as a child process, so "start" opens
/// the app and "stop" quits it. The tool never starts an engine of its own: two
/// owners of one engine is the fault the launcher spec was written to prevent.
public enum Launcher {
    public static let appPath = "/Applications/Tecopa Plateworks.app"
    public static let port = 8848
    /// Matches the launcher's own process, by its path inside the app bundle.
    static let processPattern = "Tecopa Plateworks.app/Contents/MacOS/TecopaPlateworks"

    enum Serving { case tecopa, foreign, none }

    static func probe(_ runtime: Runtime) async -> Serving {
        guard let reply = try? await runtime.client.raw("/readyz", timeout: 2) else { return .none }
        return (reply.json["ready"] != nil && reply.json["regions"] != nil) ? .tecopa : .foreign
    }

    static func requireLauncherPort(_ runtime: Runtime) throws {
        guard runtime.port == port else {
            throw TecopaFailure(
                .usage, "Engine control applies only to the launcher's engine on port \(port).",
                hint: "Stop a development engine where it was started.")
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
                .environment, "Port \(port) answers, but it is not Tecopa Plateworks.",
                hint: "Quit the other program on that port.")
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
        for _ in 0..<150 {              // 75 seconds: the launcher itself waits 60
            if await probe(runtime) == .tecopa {
                return .object(["started": .bool(true), "running": .bool(true)])
            }
            await runtime.sleep(0.5)
        }
        throw TecopaFailure(
            .environment, "The engine did not answer within 75 seconds.",
            hint: "Run `tecopa logs`. The launcher shows an alert when it cannot start the engine.")
    }

    public static func stop(_ runtime: Runtime) async throws -> JSONValue {
        try requireLauncherPort(runtime)
        let launcherRuns = try runtime.exec("/usr/bin/pgrep", ["-f", processPattern]).exitCode == 0
        guard launcherRuns else {
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
        for _ in 0..<24 {               // 12 seconds: the launcher gives the engine 5, then SIGKILL
            if await probe(runtime) == .none {
                return .object(["stopped": .bool(true), "running": .bool(false)])
            }
            await runtime.sleep(0.5)
        }
        throw TecopaFailure(
            .refused, "The engine still answers on port \(port) after the launcher quit.",
            hint: "The launcher adopted an engine that it did not start. Stop that engine where it was started.")
    }

    public static func restart(_ runtime: Runtime) async throws -> JSONValue {
        let stopped = try await stop(runtime)
        let started = try await start(runtime)
        return .object(["stop": stopped, "start": started])
    }

    static let entries: [CatalogEntry] = [
        CatalogEntry(
            name: "engine_start",
            summary: "Open the launcher app, which starts the engine on port 8848, and wait for it to answer.",
            readOnly: false
        ) { runtime, _ in try await start(runtime) },
        CatalogEntry(
            name: "engine_stop",
            summary: "Quit the launcher app, which stops the engine it started, and wait for the port to close.",
            readOnly: false
        ) { runtime, _ in try await stop(runtime) },
        CatalogEntry(
            name: "engine_restart",
            summary: "Quit and reopen the launcher app. Use after a change to the engine's Python code.",
            readOnly: false
        ) { runtime, _ in try await restart(runtime) },
    ]
}
