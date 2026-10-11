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
    @Option(name: .long, help: "A JSON file: one flat object of proof form fields. Quote a text value.")
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
    @Option(name: .long, help: "The output path. Required, except with --no-wait.")
    var out: String?
    @Flag(name: .long, help: "Return the job id at once. Takes no --out.")
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

        var arguments: [String: JSONValue] {
            var arguments = picture.arguments
            if let out { arguments["out"] = .string(absolutePath(out)) }
            return arguments
        }

        func run() async throws { try await execute("render_proof", global, arguments) }
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

        var arguments: [String: JSONValue] {
            var arguments: [String: JSONValue] = [:]
            if let job { arguments["job"] = .string(job) }
            if let out { arguments["out"] = .string(absolutePath(out)) }
            return arguments
        }

        func run() async throws { try await execute("render_fetch", global, arguments) }
    }
}

/// The flag of the two commands that render a poster file.
struct PlateFlag: ParsableArguments {
    @Flag(name: .long, help: "Render on this engine's plate when it is not the plate of the file.")
    var allowPlateMismatch = false
}

struct ReprintCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "reprint",
        abstract: "Render a poster file again, or read what it holds.",
        discussion: "`tecopa reprint <file> --out <path>` is `tecopa reprint run`. "
            + "The file comes first, before the options.",
        subcommands: [Run.self, Inspect.self],
        defaultSubcommand: Run.self)

    struct Inspect: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "inspect",
            abstract: "Read a poster file's manifest: the plate, the sources, the edition. Renders nothing.")
        @OptionGroup var global: GlobalOptions
        @Argument(help: "The poster file.")
        var file: String?

        var arguments: [String: JSONValue] {
            file.map { ["file": .string(absolutePath($0))] } ?? [:]
        }

        func run() async throws { try await execute("reprint_inspect", global, arguments) }
    }

    struct Run: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "run",
            abstract: "Render a poster file again from its own manifest, and write it to --out.",
            discussion: "`tecopa reprint <file> --out <path>`: the file comes first, before the options.")
        @OptionGroup var global: GlobalOptions
        @Argument(help: "The poster file. Give it before the options.")
        var file: String?
        @Option(name: .long, help: "The output path. Required, with --no-wait too.")
        var out: String?
        @Option(name: .long, parsing: .upToNextOption,
                help: "key=value, one field of the reprint route for each: format, embed_spec.")
        var opt: [String] = []
        @OptionGroup var plate: PlateFlag
        @Flag(name: .long,
              help: "For a film: return the job id at once. A still is always written to --out.")
        var noWait = false

        var arguments: [String: JSONValue] {
            var arguments: [String: JSONValue] = [:]
            if let file { arguments["file"] = .string(absolutePath(file)) }
            if let out { arguments["out"] = .string(absolutePath(out)) }
            if !opt.isEmpty { arguments["opt"] = .array(opt.map { .string($0) }) }
            if plate.allowPlateMismatch { arguments["allow_plate_mismatch"] = .bool(true) }
            if noWait { arguments["no_wait"] = .bool(true) }
            return arguments
        }

        func run() async throws { try await execute("reprint", global, arguments) }
    }
}

/// `continue` is a Swift keyword, so the struct has another name than its command.
struct ContinueCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "continue",
        abstract: "Open a poster file for its next edition: add tracks, proof it, and render the final.")
    @OptionGroup var global: GlobalOptions
    @Argument(help: "The poster file. Give it before the options.")
    var file: String?
    @Option(name: .long, parsing: .upToNextOption, help: "GPX, KML or KMZ paths: the new tracks of this edition.")
    var tracks: [String] = []
    @Option(name: .long, parsing: .upToNextOption,
            help: "key=value, one proof form field for each. Each one replaces a field of the file.")
    var set: [String] = []
    // a crop can start with a minus sign, so the next word is always its value
    @Option(name: .long, parsing: .unconditional,
            help: "x0,y0,x1,y1 in overview pixels. Without it, the crop is the file's own.")
    var crop: String?
    @OptionGroup var job: RenderJob
    @OptionGroup var plate: PlateFlag

    var arguments: [String: JSONValue] {
        var arguments = job.arguments
        if let file { arguments["file"] = .string(absolutePath(file)) }
        if !tracks.isEmpty { arguments["tracks"] = .array(tracks.map { .string(absolutePath($0)) }) }
        if !set.isEmpty { arguments["set"] = .array(set.map { .string($0) }) }
        if let crop { arguments["crop"] = .string(crop) }
        if plate.allowPlateMismatch { arguments["allow_plate_mismatch"] = .bool(true) }
        return arguments
    }

    func run() async throws { try await execute("continue", global, arguments) }
}

struct RunsCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "runs",
        abstract: "List the tracked runs of the long scripts, show one, or stop one.",
        discussion: "`tecopa runs` is `tecopa runs list`.",
        subcommands: [List.self, Show.self, Cancel.self],
        defaultSubcommand: List.self)

    struct List: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "list", abstract: "List every run, newest first, each with its state.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("runs", global) }
    }

    struct Show: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "show",
            abstract: "Show one run: its record, its state, its exit code and the end of its log.")
        @OptionGroup var global: GlobalOptions
        @Argument(help: "The run id.")
        var id: String?
        @Option(name: .long, help: "How many lines of the log to return, from 1 to 2000. Default 40.")
        var lines: Int?

        var arguments: [String: JSONValue] {
            var arguments: [String: JSONValue] = [:]
            if let id { arguments["run"] = .string(id) }
            if let lines { arguments["lines"] = .int(Int64(lines)) }
            return arguments
        }

        func run() async throws { try await execute("runs_show", global, arguments) }
    }

    struct Cancel: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "cancel",
            abstract: "Stop one run: send SIGTERM to its process group. Refuses a run that is not running.")
        @OptionGroup var global: GlobalOptions
        @Argument(help: "The run id.")
        var id: String?

        var arguments: [String: JSONValue] {
            id.map { ["run": .string($0)] } ?? [:]
        }

        func run() async throws { try await execute("runs_cancel", global, arguments) }
    }
}

struct PlateCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "plate",
        abstract: "Plan, build, bake, pack, install or check a plate.",
        discussion: "`plate build`, `plate labels` and `plate playa` start a tracked run and return at once. "
            + "Read it with `tecopa runs show <id>`.",
        subcommands: [Plan.self, Build.self, Labels.self, Playa.self, Pack.self, Install.self, Check.self])

    struct Plan: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "plan",
            abstract: "Price a new plate for these tracks. The engine fetches nothing and writes nothing.")
        @OptionGroup var global: GlobalOptions
        @Option(name: .long, parsing: .upToNextOption, help: "GPX, KML or KMZ paths.")
        var tracks: [String] = []

        var arguments: [String: JSONValue] {
            tracks.isEmpty ? [:] : ["tracks": .array(tracks.map { .string(absolutePath($0)) })]
        }

        func run() async throws { try await execute("plate_plan", global, arguments) }
    }

    struct Build: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "build",
            abstract: "Start the build of a new plate as a tracked run. Refuses a plate that exists.",
            discussion: "`tecopa plate plan` gives the id, the bbox and the EPSG code.")
        @OptionGroup var global: GlobalOptions
        @Option(name: .long, help: "The region id: lower-case letters, digits and underscores.")
        var id: String?
        @Option(name: .long, help: "The plate's name.")
        var name: String?
        // One word, as `--crop` is. A western longitude starts with a minus sign, and
        // the parser reads such a word as an option unless the next word is always
        // the value. So the four numbers cannot be four words.
        @Option(name: .long, parsing: .unconditional,
                help: "west,south,east,north in degrees, as one word: --bbox -121.6,40.3,-121.2,40.6")
        var bbox: String?
        @Option(name: .long, help: "The EPSG code of the plate's projection.")
        var epsg: Int?
        @Option(name: .long, help: "The cell size in metres, or auto.")
        var resolution: String?

        var arguments: [String: JSONValue] {
            var arguments: [String: JSONValue] = [:]
            if let id { arguments["id"] = .string(id) }
            if let name { arguments["name"] = .string(name) }
            // the entry takes the four texts and checks each one
            if let bbox {
                arguments["bbox"] = .array(
                    bbox.split(separator: ",", omittingEmptySubsequences: false).map { .string(String($0)) })
            }
            if let epsg { arguments["epsg"] = .int(Int64(epsg)) }
            if let resolution { arguments["resolution"] = .string(resolution) }
            return arguments
        }

        func run() async throws { try await execute("plate_build", global, arguments) }
    }

    /// The one argument of the commands that name a plate.
    struct Plate: ParsableArguments {
        @Argument(help: "The region id.")
        var id: String?

        var arguments: [String: JSONValue] {
            id.map { ["id": .string($0)] } ?? [:]
        }
    }

    struct Labels: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "labels",
            abstract: "Start the label bake of a built plate as a tracked run. "
                + "Refuses a plate that already lists labels.json.")
        @OptionGroup var global: GlobalOptions
        @OptionGroup var plate: Plate
        func run() async throws { try await execute("plate_labels", global, plate.arguments) }
    }

    struct Playa: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "playa",
            abstract: "Start the playa bake of a built plate as a tracked run. "
                + "Refuses a plate that already lists playa.json.")
        @OptionGroup var global: GlobalOptions
        @OptionGroup var plate: Plate
        func run() async throws { try await execute("plate_playa", global, plate.arguments) }
    }

    struct Pack: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "pack", abstract: "Pack a built plate into a .trailplate.zip file under plates/.")
        @OptionGroup var global: GlobalOptions
        @OptionGroup var plate: Plate
        @Flag(name: .long,
              help: "Pack a drifted plate with the true hashes in the zip's copy of sources.json.")
        var resync = false

        var arguments: [String: JSONValue] {
            var arguments = plate.arguments
            if resync { arguments["resync"] = .bool(true) }
            return arguments
        }

        func run() async throws { try await execute("plate_pack", global, arguments) }
    }

    struct Install: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "install",
            abstract: "Install a plate from a local .trailplate.zip file. An installed plate is never replaced.")
        @OptionGroup var global: GlobalOptions
        @Argument(help: "The .trailplate.zip file.")
        var file: String?

        var arguments: [String: JSONValue] {
            file.map { ["file": .string(absolutePath($0))] } ?? [:]
        }

        func run() async throws { try await execute("plate_install", global, arguments) }
    }

    struct Check: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "check", abstract: "Check a poster file against the plate that is installed.")
        @OptionGroup var global: GlobalOptions
        @Argument(help: "The poster PNG.")
        var poster: String?

        var arguments: [String: JSONValue] {
            poster.map { ["poster": .string(absolutePath($0))] } ?? [:]
        }

        func run() async throws { try await execute("plate_check", global, arguments) }
    }
}

struct OrderCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "order",
        abstract: "Prepare a customer order, preview its sizes, or read what Prepare decided.",
        discussion: "`order prepare` and `order preview` each start a tracked run and return at once. "
            + "Read a run with `tecopa runs show <id>`. After Prepare, run `tecopa order status <folder>`. "
            + "The preview writes its PDF under the order's out/preview/ folder.",
        subcommands: [Prepare.self, Preview.self, Status.self])

    /// The one argument of each command.
    struct Folder: ParsableArguments {
        @Argument(help: "The order folder, which holds in/ and order.toml.")
        var folder: String?

        var arguments: [String: JSONValue] {
            folder.map { ["folder": .string(absolutePath($0))] } ?? [:]
        }
    }

    struct Prepare: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "prepare",
            abstract: "Start Prepare as a tracked run: build or reuse the order's plate and frame the tracks.")
        @OptionGroup var global: GlobalOptions
        @OptionGroup var order: Folder
        func run() async throws { try await execute("order_prepare", global, order.arguments) }
    }

    struct Preview: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "preview",
            abstract: "Start the size preview as a tracked run: every size that suits the tracks, as one PDF.")
        @OptionGroup var global: GlobalOptions
        @OptionGroup var order: Folder
        func run() async throws { try await execute("order_preview", global, order.arguments) }
    }

    struct Status: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "status",
            abstract: "Print the order's report, from its own work/ folder. With --json: all of its state.")
        @OptionGroup var global: GlobalOptions
        @OptionGroup var order: Folder
        func run() async throws { try await execute("order_status", global, order.arguments) }
    }
}

struct StudioCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "studio",
        abstract: "Read what the studio's browser tabs reported: their state, and their errors.",
        subcommands: [State.self, Errors.self])

    struct State: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "state",
            abstract: "List each studio tab that has reported, with its session, view and proof flags.")
        @OptionGroup var global: GlobalOptions
        func run() async throws { try await execute("studio_state", global) }
    }

    struct Errors: AsyncParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "errors",
            abstract: "List the errors the studio's tabs reported, newest first.")
        @OptionGroup var global: GlobalOptions
        @Option(name: .long, help: "A tab id from `tecopa studio state`. Keeps only that tab's errors.")
        var tab: String?
        @Option(name: .long, help: "error, rejection or toast. Keeps only that kind.")
        var kind: String?

        func run() async throws {
            var arguments: [String: JSONValue] = [:]
            if let tab { arguments["tab"] = .string(tab) }
            if let kind { arguments["kind"] = .string(kind) }
            try await execute("studio_errors", global, arguments)
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
