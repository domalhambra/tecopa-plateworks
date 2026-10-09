import ArgumentParser
import TecopaKit

// One thin struct per command. Each one names its catalog entry and passes its
// arguments. No command holds logic of its own.

struct EngineCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "engine",
        abstract: "Read or control the launcher's engine.",
        subcommands: [Status.self])

    struct Status: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "status", abstract: "Report if the engine answers, and the debug gate.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("engine_status", global) }
    }
}

struct RegionsCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "regions",
        abstract: "List the plates, or check them against sources.json.",
        subcommands: [List.self],
        defaultSubcommand: List.self)

    struct List: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "list", abstract: "List the plates with the readiness report.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("regions", global) }
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
