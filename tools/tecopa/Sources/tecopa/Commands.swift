import ArgumentParser
import TecopaKit

// One thin struct per command. Each one names its catalog entry and passes its
// arguments. No command holds logic of its own.

struct EngineCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "engine",
        abstract: "Read or control the launcher's engine.",
        subcommands: [Status.self, Start.self, Stop.self, Restart.self])

    struct Status: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "status", abstract: "Report if the engine answers, and the debug gate.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("engine_status", global) }
    }

    struct Start: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "start", abstract: "Open the launcher app and wait for the engine.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("engine_start", global) }
    }

    struct Stop: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "stop", abstract: "Quit the launcher app and wait for the port to close.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("engine_stop", global) }
    }

    struct Restart: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "restart", abstract: "Quit and reopen the launcher app.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("engine_restart", global) }
    }
}

struct RegionsCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "regions",
        abstract: "List the plates, or check them against sources.json.",
        subcommands: [List.self, Verify.self],
        defaultSubcommand: List.self)

    struct List: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "list", abstract: "List the plates with the readiness report.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("regions", global) }
    }

    struct Verify: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "verify", abstract: "Run scripts/verify_regions.py.")
        @OptionGroup var global: GlobalOptions
        @Argument(help: "Region ids to check. Without one, every plate is checked.")
        var regions: [String] = []

        func run() async throws {
            let ids = regions.map { JSONValue.string($0) }
            try await execute("regions_verify", global, ids.isEmpty ? [:] : ["regions": .array(ids)])
        }
    }
}

struct JobsCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "jobs", abstract: "List every job in the three queues.")
    @OptionGroup var global: GlobalOptions
    func run() async throws { try await execute("jobs", global) }
}

struct SessionsCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "sessions", abstract: "List the sessions, or show one.")
    @OptionGroup var global: GlobalOptions
    @Argument(help: "A session id. Without it, every session is listed.")
    var sid: String?
    @Flag(name: .long, help: "With a session id: include the track geometry.")
    var full = false

    func run() async throws {
        var arguments: [String: JSONValue] = [:]
        if let sid { arguments["sid"] = .string(sid) }
        if full { arguments["full"] = .bool(true) }
        try await execute("sessions", global, arguments)
    }
}

struct CachesCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "caches", abstract: "Report the terrain and route-ink caches.")
    @OptionGroup var global: GlobalOptions
    func run() async throws { try await execute("caches", global) }
}

struct LogsCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "logs", abstract: "Read the tail of the launcher log.")
    @OptionGroup var global: GlobalOptions
    @Option(name: .long, help: "How many lines to return.")
    var lines: Int = 50
    @Option(name: .long, help: "Keep only lines that contain this text.")
    var grep: String?
    @Option(name: .long, help: ArgumentHelp(LogReader.sinceSummary))
    var since: String?

    func run() async throws {
        var arguments: [String: JSONValue] = ["lines": .int(Int64(lines))]
        if let grep { arguments["grep"] = .string(grep) }
        if let since { arguments["since"] = .string(since) }
        try await execute("logs", global, arguments)
    }
}

struct DoctorCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "doctor",
        abstract: "Check the repo, the venvs, the launcher, the port and the log. Works with no engine.")
    @OptionGroup var global: GlobalOptions

    func run() async throws {
        let report = try await execute("doctor", global)
        // a failed check is an environment fault; warnings alone exit 0
        if (report["fail_count"]?.intValue ?? 0) > 0 { throw ExitCode(4) }
    }
}
