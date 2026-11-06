import Foundation

/// Runs the repo's Python scripts. The table is an allowlist and the one place that
/// decides a script's venv (CLAUDE.md, invariant 13: the region-prep stack never
/// enters .venv). A script with no row does not run, and no flag overrides the table.
public enum ScriptRunner {
    public enum Venv: String, Sendable {
        case app = ".venv"
        case prep = ".venv-prep"
    }

    /// One row of the table: what the name is, and the venv that runs it.
    struct Row: Equatable, Sendable {
        enum Kind: Equatable, Sendable {
            /// The name is a path under the repo: `python <name> …`.
            case script
            /// The name is a Python module: `python -m <name> …`.
            case module
        }

        let kind: Kind
        let venv: Venv

        static func script(_ venv: Venv) -> Row { Row(kind: .script, venv: venv) }
        static func module(_ venv: Venv) -> Row { Row(kind: .module, venv: venv) }
    }

    /// The key is the script's path under the repo, or the module's name. Add a row
    /// in the same change as the command that needs it.
    ///
    /// The two prep rows are the scripts that import the region-prep stack: the
    /// plate build, and the playa bake, which needs `pynhd`. No other row is prep.
    static let table: [String: Row] = [
        "scripts/verify_regions.py": .script(.app),     // regions verify
        "region_prep.py": .script(.prep),               // plate build
        "scripts/build_labels.py": .script(.app),       // plate labels
        "scripts/bake_playa.py": .script(.prep),        // plate playa
        "scripts/pack_region.py": .script(.app),        // plate pack
        "app.plates": .module(.app),                    // plate install, plate check
        "scripts/order.py": .script(.app),              // order new, order prepare, order preview
    ]

    /// One command that the table allows: the interpreter of the row's venv, its
    /// arguments, the working directory and the whole environment. In a repo the
    /// directory is the repo; in the app it is the data root.
    struct Command: Equatable, Sendable {
        let python: String
        let arguments: [String]
        let cwd: String
        let environment: [String: String]
    }

    /// The variables of the caller that change what a Python interpreter loads:
    /// its standard library, its module path, a file it runs at its start, and the
    /// interpreter that a macOS launcher names. The table picks the interpreter,
    /// and with one of these the caller's shell would pick what it loads. That
    /// could load the prep stack into `.venv`, or the reverse (invariant 13).
    static let droppedVariables = ["PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "__PYVENV_LAUNCHER__"]

    /// The environment of a script: the tool's own, without `droppedVariables`.
    /// A script that runs in the call and a script that starts detached both get
    /// this one. Each other variable goes through: `scripts/order.py` reads
    /// `TECOPA_ORDERS_DIR`.
    static func environment(_ runtime: Runtime) -> [String: String] {
        runtime.environment.filter { !droppedVariables.contains($0.key) }
    }

    /// Check the table and the interpreter. `run` and `start` both begin here, so
    /// a script cannot run in the call by one rule and detached by another.
    static func command(_ name: String, _ arguments: [String], _ runtime: Runtime,
                        table: [String: Row]) throws -> Command {
        guard let row = table[name] else {
            throw TecopaFailure(
                .usage, "\(name) has no row in the script table.",
                hint: "Add a row to ScriptRunner.table in the same change as the command.")
        }
        let layout = try runtime.engineLayout()
        let missing = { (python: String) in
            TecopaFailure(.environment, "No interpreter at \(python).",
                          hint: "Read docs/changing-things.md, Set up a machine.")
        }
        switch layout {
        case .repo(let repo):
            let python = repo + "/" + row.venv.rawValue + "/bin/python"
            guard runtime.fileExists(python) else { throw missing(python) }
            let target = row.kind == .module ? ["-m", name] : [name]
            return Command(python: python, arguments: target + arguments, cwd: repo,
                           environment: environment(runtime))
        case .bundle:
            // The row's venv column picks the bundled interpreter: invariant 13.
            let python = row.venv == .prep ? layout.prepPython : layout.enginePython
            guard runtime.fileExists(python) else { throw missing(python) }
            // `-P` keeps the data root, the working directory, off sys.path. Each
            // script puts the code root on it; a module gets it from the bootstrap.
            let code = layout.codeRoot
            let target: [String]
            switch row.kind {
            case .script:
                target = ["-P", code + "/" + name]
            case .module:
                target = ["-P", "-c", "import sys,runpy; sys.path.insert(0, \(pythonLiteral(code))); "
                    + "runpy.run_module(\(pythonLiteral(name)), run_name='__main__', alter_sys=True)"]
            }
            return Command(python: python, arguments: target + arguments,
                           cwd: layout.dataRoot(home: runtime.home),
                           environment: try bundleEnvironment(layout, runtime))
        }
    }

    /// The environment of a script in the app: the engine's own (phase 1 spec 5.3),
    /// from the tool's environment without `droppedVariables`, the data root's
    /// `settings.json` and the bundle's engine version.
    static func bundleEnvironment(_ layout: EngineLayout, _ runtime: Runtime) throws -> [String: String] {
        let path = layout.dataRoot(home: runtime.home) + "/settings.json"
        let settings = try EngineEnvironment.settings(from: runtime.readData(path), path: path)
        return EngineEnvironment.build(
            layout: layout, home: runtime.home, base: environment(runtime), settings: settings,
            engineVersion: layout.infoValue("TecopaEngineVersion", runtime) ?? "unknown")
    }

    /// A Python string literal of `text`, in single quotes. Only the bootstrap of a
    /// module row uses it, for the code root and the module's name.
    static func pythonLiteral(_ text: String) -> String {
        let escaped = text.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "'", with: "\\'")
            .replacingOccurrences(of: "\n", with: "\\n")
            .replacingOccurrences(of: "\r", with: "\\r")
        return "'" + escaped + "'"
    }

    /// Run one row of the table and wait for it.
    public static func run(_ name: String, _ arguments: [String],
                           _ runtime: Runtime) throws -> ProcessResult {
        try run(name, arguments, runtime, table: table)
    }

    /// `run` over a given table. Only a test gives another table than the tool's
    /// own: a row that the tool does not have yet.
    static func run(_ name: String, _ arguments: [String], _ runtime: Runtime,
                    table: [String: Row]) throws -> ProcessResult {
        let command = try command(name, arguments, runtime, table: table)
        return try runtime.exec(command.python, command.arguments, cwd: command.cwd,
                                environment: command.environment)
    }

    /// Start one row of the table as a tracked run, and return at once. The checks
    /// are those of `run`. `command` is the catalog name of the entry that starts
    /// the run, for example `plate_build`. A run whose log holds `failureText` is
    /// `failed` whatever its exit code.
    ///
    /// The result is `{"run", "pid", "log", "hint"}`: see `Runs.start`, which gives
    /// the run the environment of `environment(_:)`.
    static func start(_ name: String, _ arguments: [String], command: String,
                             failureText: String? = nil, _ runtime: Runtime) throws -> JSONValue {
        try start(name, arguments, command: command, failureText: failureText, runtime, table: table)
    }

    /// `start` over a given table, for a test.
    static func start(_ name: String, _ arguments: [String], command: String,
                      failureText: String? = nil, _ runtime: Runtime,
                      table: [String: Row]) throws -> JSONValue {
        let row = try self.command(name, arguments, runtime, table: table)
        return try Runs.start(program: row.python, arguments: row.arguments, cwd: row.cwd,
                              environment: row.environment, command: command,
                              failureText: failureText, runtime)
    }

    /// The engine's own rule for a region id, `^[a-z0-9_]{1,64}$` (app/main.py). The
    /// check is on the UTF-8 bytes, so no Unicode letter, digit or combining mark
    /// passes, and an id can never be read as a flag or a path.
    static func isRegionID(_ id: String) -> Bool {
        let bytes = Array(id.utf8)
        return (1...64).contains(bytes.count) && bytes.allSatisfy { byte in
            (UInt8(ascii: "a")...UInt8(ascii: "z")).contains(byte)
                || (UInt8(ascii: "0")...UInt8(ascii: "9")).contains(byte)
                || byte == UInt8(ascii: "_")
        }
    }

    /// The line Python prints first when an exception ends a script.
    static let tracebackMarker = "Traceback (most recent call last)"

    static let verifyEntry = CatalogEntry(
        name: "regions_verify",
        summary: "Check each plate's assets against its sources.json, and its DEM geometry. Reads only.",
        readOnly: true,
        parameters: [
            EntryParameter("regions", .stringArray, "Region ids to check. Without it, every plate is checked."),
        ],
        text: { data in data["output"]?.stringValue ?? "" }
    ) { runtime, arguments in
        let ids = (arguments["regions"]?.arrayValue ?? []).compactMap { $0.stringValue }
        for id in ids {
            // an id is a folder name under regions/; anything else could be read as a flag
            guard isRegionID(id) else {
                throw TecopaFailure(.usage, "Not a region id: \(id)")
            }
        }
        let result = try run("scripts/verify_regions.py", ids, runtime)
        let stderr = result.stderr.trimmingCharacters(in: .whitespacesAndNewlines)
        // 0: every asset matches. 1: the script found drift, which is the answer.
        // Anything else: the script could not do its work.
        guard result.exitCode == 0 || result.exitCode == 1 else {
            throw TecopaFailure(
                .environment, "verify_regions.py exited \(result.exitCode): \(result.stderr)")
        }
        // Python also exits 1 when an exception ends the script. A crash is not drift.
        if result.exitCode == 1, stderr.contains(tracebackMarker) {
            let last = stderr.split(whereSeparator: \.isNewline)
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .last { !$0.isEmpty } ?? ""
            throw TecopaFailure(
                .environment, "verify_regions.py crashed: \(last)",
                body: .object(["stderr": .string(stderr)]))
        }
        return .object([
            "clean": .bool(result.exitCode == 0),
            "exit_code": .int(Int64(result.exitCode)),
            "output": .string(result.stdout.trimmingCharacters(in: .whitespacesAndNewlines)),
            "stderr": .string(stderr),
        ])
    }
}
