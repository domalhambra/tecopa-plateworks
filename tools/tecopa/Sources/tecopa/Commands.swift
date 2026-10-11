import ArgumentParser
import TecopaKit

// One thin struct per command. Each one names its catalog entry and passes its
// arguments. No command holds logic of its own. A path goes through `absolutePath`:
// the catalog takes an absolute path only.

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
        @Flag(name: .long, help: "Stop even when a job is running or queued.")
        var force = false

        func run() async throws {
            try await execute("engine_stop", global, force ? ["force": .bool(true)] : [:])
        }
    }

    struct Restart: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "restart", abstract: "Quit and reopen the launcher app.")
        @OptionGroup var global: GlobalOptions
        @Flag(name: .long, help: "Stop even when a job is running or queued.")
        var force = false

        func run() async throws {
            try await execute("engine_restart", global, force ? ["force": .bool(true)] : [:])
        }
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
    @Option(name: .long, help: "How many lines to return, from 1 to 2000.")
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

/// Where a render's picture comes from, and its proof fields. The four commands
/// that make a picture share these options.
struct RenderPicture: ParsableArguments {
    @Option(name: .long, parsing: .upToNextOption,
            help: "GPX, KML or KMZ paths. Give --tracks or --session, never both.")
    var tracks: [String] = []
    @Option(name: .long, help: "A session id. The tool sends no upload, and renders the session.")
    var session: String?
    @Option(name: .long, help: "A region id, sent with the tracks.")
    var region: String?
    @Option(name: .long, help: "The path of a JSON file: one flat object of proof form fields.")
    var spec: String?
    @Option(name: .long, parsing: .upToNextOption,
            help: "key=value, one proof form field for each. Wins over --spec.")
    var set: [String] = []
    // a crop can start with a minus sign, so the next word is always its value
    @Option(name: .long, parsing: .unconditional, help: "x0,y0,x1,y1 in overview pixels.")
    var crop: String?

    var arguments: [String: JSONValue] {
        var arguments: [String: JSONValue] = [:]
        if !tracks.isEmpty { arguments["tracks"] = .array(tracks.map { .string(absolutePath($0)) }) }
        if let session { arguments["session"] = .string(session) }
        if let region { arguments["region"] = .string(region) }
        if let spec { arguments["spec"] = .string(absolutePath(spec)) }
        if !set.isEmpty { arguments["set"] = .array(set.map { .string($0) }) }
        if let crop { arguments["crop"] = .string(crop) }
        return arguments
    }
}

/// The options of a render that runs as a job: the output route's fields, the
/// file, and the choice not to wait.
struct RenderJob: ParsableArguments {
    @Option(name: .long, parsing: .upToNextOption,
            help: "key=value, one field of the output route for each.")
    var opt: [String] = []
    @Option(name: .long, help: "The path of the file to write. It must hold no file.")
    var out: String?
    @Flag(name: .long, help: "Return the job id at once and write no file. Then run `tecopa render fetch`.")
    var noWait = false

    var arguments: [String: JSONValue] {
        var arguments: [String: JSONValue] = [:]
        if !opt.isEmpty { arguments["opt"] = .array(opt.map { .string($0) }) }
        if let out { arguments["out"] = .string(absolutePath(out)) }
        if noWait { arguments["no_wait"] = .bool(true) }
        return arguments
    }
}

struct RenderCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "render",
        abstract: "Render a proof, a final, wallpapers or a film, or save a finished job's file.",
        subcommands: [Proof.self, Final.self, Wallpaper.self, Film.self, Fetch.self])

    struct Proof: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "proof", abstract: "Render a proof PNG and write it to --out.")
        @OptionGroup var global: GlobalOptions
        @OptionGroup var picture: RenderPicture
        @Option(name: .long, help: "The path of the PNG to write. It must hold no file.")
        var out: String?

        func run() async throws {
            var arguments = picture.arguments
            if let out { arguments["out"] = .string(absolutePath(out)) }
            try await execute("render_proof", global, arguments)
        }
    }

    struct Final: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "final", abstract: "Render the final poster and write it to --out.")
        @OptionGroup var global: GlobalOptions
        @OptionGroup var picture: RenderPicture
        @OptionGroup var job: RenderJob

        func run() async throws {
            try await execute("render_final", global,
                              picture.arguments.merging(job.arguments) { _, new in new })
        }
    }

    struct Wallpaper: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "wallpaper", abstract: "Render a zip of wallpapers, one for each preset.")
        @OptionGroup var global: GlobalOptions
        @OptionGroup var picture: RenderPicture
        @Option(name: .long, parsing: .upToNextOption, help: "Wallpaper preset ids. Required.")
        var presets: [String] = []
        @OptionGroup var job: RenderJob

        func run() async throws {
            var arguments = picture.arguments.merging(job.arguments) { _, new in new }
            if !presets.isEmpty { arguments["presets"] = .array(presets.map { .string($0) }) }
            try await execute("render_wallpaper", global, arguments)
        }
    }

    struct Film: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "film", abstract: "Render the time-lapse film and write it to --out.")
        @OptionGroup var global: GlobalOptions
        @OptionGroup var picture: RenderPicture
        @OptionGroup var job: RenderJob

        func run() async throws {
            try await execute("render_film", global,
                              picture.arguments.merging(job.arguments) { _, new in new })
        }
    }

    struct Fetch: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "fetch", abstract: "Write the file of a job that is done to --out.")
        @OptionGroup var global: GlobalOptions
        @Option(name: .long, help: "The job id that --no-wait returned.")
        var job: String?
        @Option(name: .long, help: "The path of the file to write. It must hold no file.")
        var out: String?

        func run() async throws {
            var arguments: [String: JSONValue] = [:]
            if let job { arguments["job"] = .string(job) }
            if let out { arguments["out"] = .string(absolutePath(out)) }
            try await execute("render_fetch", global, arguments)
        }
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
