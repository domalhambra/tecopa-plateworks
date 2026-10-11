import Foundation

/// Tracked runs. A script that takes minutes starts detached and the call returns
/// at once, because an MCP call must return quickly. One record for each run lets a
/// later call read the run and stop it.
///
/// A run has three files in the runs folder, all named by its id:
///   <id>.json   the record, written one time at the start
///   <id>.log    the script's stdout and stderr
///   <id>.exit   the script's exit code, written when the script ends
///
/// No function here deletes a record, a log or an exit file, and none writes over one.
enum Runs {
    static let entries: [CatalogEntry] = [listEntry, showEntry, cancelEntry]

    // MARK: The start

    /// The text that `/bin/sh -c` runs for every run. After it come the run's
    /// name, the log path, the exit file path, the program and its arguments.
    ///
    /// Each of those is a positional parameter, and `"$@"` gives the program its
    /// arguments as they are. No argument is a part of this text, so none goes
    /// through the shell's parsing.
    ///
    /// The exit code goes to another name first and is then moved to the exit
    /// file. A rename is one step, so a reader finds the whole number or no file.
    static let wrapper =
        #"log=$1; code=$2; shift 2; "$@" >>"$log" 2>&1; echo $? >"$code.tmp" && /bin/mv "$code.tmp" "$code""#

    /// The name the shell of a run has as its `$0`. It is in the shell's command
    /// line, and that is how `ps` tells a run from another program with its pid.
    static func processName(_ id: String) -> String { "tecopa-run-" + id }

    /// True for the one form of a run id, `YYYYMMDD-HHMMSS-<6 hex>`: digits, two
    /// hyphens, and six lower-case hexadecimal digits. The check is on the UTF-8
    /// bytes, so a fullwidth digit does not pass. An id goes into a path, so every
    /// id from a caller is checked first.
    static func isRunID(_ id: String) -> Bool {
        let bytes = Array(id.utf8)
        guard bytes.count == 22 else { return false }
        let digit = UInt8(ascii: "0")...UInt8(ascii: "9")
        let letter = UInt8(ascii: "a")...UInt8(ascii: "f")
        for (index, byte) in bytes.enumerated() {
            switch index {
            case 8, 15:
                guard byte == UInt8(ascii: "-") else { return false }
            case 16...:
                guard digit.contains(byte) || letter.contains(byte) else { return false }
            default:
                guard digit.contains(byte) else { return false }
            }
        }
        return true
    }

    /// One time as the start of a run id and as an ISO 8601 text, both in UTC.
    static func stamp(_ date: Date) -> (id: String, iso: String) {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? TimeZone(secondsFromGMT: 0) ?? calendar.timeZone
        let parts = calendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: date)
        func text(_ value: Int?, _ width: Int) -> String {
            let digits = String(value ?? 0)
            return String(repeating: "0", count: max(0, width - digits.count)) + digits
        }
        let day = (text(parts.year, 4), text(parts.month, 2), text(parts.day, 2))
        let time = (text(parts.hour, 2), text(parts.minute, 2), text(parts.second, 2))
        return ("\(day.0)\(day.1)\(day.2)-\(time.0)\(time.1)\(time.2)",
                "\(day.0)-\(day.1)-\(day.2)T\(time.0):\(time.1):\(time.2)Z")
    }

    /// The path of one of a run's three files. `kind` is `json`, `log` or `exit`.
    static func path(_ id: String, _ kind: String, _ runtime: Runtime) -> String {
        runtime.runsFolder + "/" + id + "." + kind
    }

    static func showHint(_ id: String) -> String { "Run `tecopa runs show \(id)`." }

    /// Start one program detached, and write its record.
    ///
    /// The order: the folder, a new id whose three paths are free, the start, the
    /// record. The record holds the process id, so it cannot be written first. If
    /// the record cannot be written, the run is stopped: a run with no record
    /// cannot be read or stopped later.
    ///
    /// `command` is the catalog name of the entry that starts the run. `cwd` is
    /// the program's working directory. The result is
    /// `{"run": id, "pid": n, "log": path, "hint": "Run `tecopa runs show <id>`."}`.
    static func start(program: String, arguments: [String], cwd: String, command: String,
                      failureText: String?, _ runtime: Runtime) throws -> JSONValue {
        // A C string ends at its first NUL byte, so the program would get another argument.
        guard !([program, cwd] + arguments).contains(where: { $0.utf8.contains(0) }) else {
            throw TecopaFailure(.usage, "An argument of a run cannot hold a NUL byte.")
        }
        try runtime.makeFolder(runtime.runsFolder)

        let now = runtime.now()
        let id = stamp(now).id + "-" + runtime.randomHex(6)
        guard isRunID(id) else {
            throw TecopaFailure(.environment, "The tool made a run id that is not a run id: \(id)")
        }
        let record = Record(
            id: id, command: command, argv: [program] + arguments, cwd: cwd, pid: 0,
            started: stamp(now).iso, log: path(id, "log", runtime), exitFile: path(id, "exit", runtime),
            failureText: failureText)
        let recordPath = path(id, "json", runtime)
        // The same second and the same six digits: the first run keeps its files.
        for taken in [recordPath, record.log, record.exitFile] where runtime.pathKind(taken) != nil {
            throw TecopaFailure(.environment, "A run with the id \(id) is already in \(runtime.runsFolder).",
                                hint: "Run the command again.")
        }

        var environment = runtime.environment
        // Python holds back its output when it does not write to a terminal. With
        // this, each line is in the log when the script prints it.
        environment["PYTHONUNBUFFERED"] = "1"
        let shell = ["-c", wrapper, processName(id), record.log, record.exitFile, program] + arguments
        let pid: Int32
        do {
            pid = try runtime.runner.startDetached("/bin/sh", shell, cwd: cwd, environment: environment)
        } catch let failure as TecopaFailure {
            throw failure
        } catch {
            throw TecopaFailure(.environment, "Could not start \(program): \(error.localizedDescription)")
        }

        do {
            try runtime.writeNew(recordPath, Data(record.with(pid: pid).json.text().utf8))
        } catch {
            try? runtime.runner.signalGroup(pid, SIGTERM)
            let said = (error as? TecopaFailure)?.message ?? error.localizedDescription
            throw TecopaFailure(
                .environment,
                "The record of the run could not be written, so the run (process \(pid)) was stopped. "
                    + Render.sentence(said))
        }
        return .object([
            "run": .string(id), "pid": .int(Int64(pid)), "log": .string(record.log),
            "hint": .string(showHint(id)),
        ])
    }

    // MARK: The record

    /// One run, as its `<id>.json` holds it.
    struct Record: Equatable, Sendable {
        let id: String
        /// The catalog name of the entry that started the run.
        let command: String
        /// The program and its arguments, without the shell around them.
        let argv: [String]
        let cwd: String
        /// The process id of the run's shell. With its own session, this is also
        /// the id of the run's process group.
        let pid: Int32
        /// ISO 8601, UTC.
        let started: String
        let log: String
        let exitFile: String
        /// A run whose log holds this text is `failed`, whatever its exit code.
        let failureText: String?

        func with(pid: Int32) -> Record {
            Record(id: id, command: command, argv: argv, cwd: cwd, pid: pid, started: started,
                   log: log, exitFile: exitFile, failureText: failureText)
        }

        var json: JSONValue {
            .object([
                "id": .string(id), "command": .string(command), "argv": .array(argv.map { .string($0) }),
                "cwd": .string(cwd), "pid": .int(Int64(pid)), "started": .string(started),
                "log": .string(log), "exit_file": .string(exitFile),
                "failure_text": failureText.map { .string($0) } ?? .null,
            ])
        }
    }

    /// Read one record from the text of its file. nil when the text is not a
    /// record of the run `id`: not JSON, a key that is missing or has another
    /// type, or the id of another run.
    ///
    /// A process id of 1 or less is not a record. `runs cancel` signals the group
    /// with this id, and group 1 and group 0 are not one run's processes.
    static func record(in data: Data, id: String) -> Record? {
        guard let value = try? JSONValue.parse(data),
              value["id"]?.stringValue == id,
              let command = value["command"]?.stringValue,
              let argv = value["argv"]?.arrayValue, argv.allSatisfy({ $0.stringValue != nil }),
              let cwd = value["cwd"]?.stringValue,
              let number = value["pid"]?.intValue, number > 1, let pid = Int32(exactly: number),
              let started = value["started"]?.stringValue,
              let log = value["log"]?.stringValue,
              let exitFile = value["exit_file"]?.stringValue else {
            return nil
        }
        var failureText: String?
        switch value["failure_text"] {
        case nil, .null?: break
        case .string(let text)?: failureText = text
        default: return nil
        }
        return Record(id: id, command: command, argv: argv.compactMap(\.stringValue), cwd: cwd, pid: pid,
                      started: started, log: log, exitFile: exitFile, failureText: failureText)
    }

    /// The record of the run that a caller names. The id is checked before it
    /// goes into a path.
    static func record(_ arguments: [String: JSONValue], _ runtime: Runtime) throws -> Record {
        guard let id = arguments["run"]?.stringValue, !id.isEmpty else {
            throw TecopaFailure(.usage, "run is required: the id of a run.", hint: "Run `tecopa runs`.")
        }
        guard isRunID(id) else {
            throw TecopaFailure(.usage, "Not a run id: \(id.debugDescription)", hint: "Run `tecopa runs`.")
        }
        let file = path(id, "json", runtime)
        guard let data = runtime.readData(file) else {
            throw TecopaFailure(.usage, "No run has the id \(id).", hint: "Run `tecopa runs`.")
        }
        guard let record = record(in: data, id: id) else {
            throw TecopaFailure(.environment, "The run record at \(file) cannot be read.")
        }
        return record
    }

    // MARK: The state

    enum State: String, Sendable {
        /// No exit file, and the process table has the run's shell.
        case running
        /// Exit code 0, and the log does not hold the record's failure text.
        case done
        /// Any other exit code, or the failure text is in the log.
        case failed
        /// No exit file and no such process. The Mac restarted, or the run was killed.
        case lost
        /// Not a state of a run: the record's file cannot be read as a record.
        case unreadable
    }

    struct Status: Equatable, Sendable {
        let state: State
        let exitCode: Int?

        var json: [String: JSONValue] {
            ["state": .string(state.rawValue), "exit_code": exitCode.map { .int(Int64($0)) } ?? .null]
        }
    }

    /// The text of a run's log, or nil when the run has written none.
    static func log(_ record: Record, _ runtime: Runtime) -> String? {
        runtime.readData(record.log).map { String(decoding: $0, as: UTF8.self) }
    }

    /// The state of a run that has an exit file, or nil when it has none.
    private static func ended(_ record: Record, _ runtime: Runtime, log: String?) -> Status? {
        guard let text = runtime.readFile(record.exitFile) else { return nil }
        // An exit file with no number is not a run that ended well.
        guard let code = Int(text.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            return Status(state: .failed, exitCode: nil)
        }
        guard code == 0 else { return Status(state: .failed, exitCode: code) }
        if let mark = record.failureText, !mark.isEmpty, log?.contains(mark) == true {
            return Status(state: .failed, exitCode: 0)
        }
        return Status(state: .done, exitCode: 0)
    }

    /// The state of one run. The checks are in this order:
    ///
    /// 1. An exit file: `done` or `failed`.
    /// 2. No exit file, and `ps` prints a command line for the pid that holds
    ///    the run's own name: `running`.
    /// 3. No exit file and no such process: `lost`.
    ///
    /// The pid alone is not enough: macOS gives the pid of a run that ended to
    /// another program later. The run's name has its id, and no other program
    /// has that name.
    ///
    /// A run can end between check 1 and check 2. So when `ps` finds no process,
    /// the exit file is read one more time before the run is called lost.
    ///
    /// `log` is the log's text when the caller has read it, so it is read one time.
    static func status(_ record: Record, _ runtime: Runtime, log: String?) throws -> Status {
        if let status = ended(record, runtime, log: log) { return status }
        let found = try runtime.exec("/bin/ps", ["-o", "command=", "-p", String(record.pid)])
        // ps exits 1 when no process has the pid. Any other code is not an answer.
        guard found.exitCode == 0 || found.exitCode == 1 else {
            let said = found.stderr.trimmingCharacters(in: .whitespacesAndNewlines)
            throw TecopaFailure(.environment, "ps failed with exit \(found.exitCode): \(said)")
        }
        if found.exitCode == 0, found.stdout.contains(processName(record.id)) {
            return Status(state: .running, exitCode: nil)
        }
        return ended(record, runtime, log: log) ?? Status(state: .lost, exitCode: nil)
    }

    /// The state of a run for the list: the log is read only when the record has
    /// a failure text to look for.
    static func status(_ record: Record, _ runtime: Runtime) throws -> Status {
        let needsLog = record.failureText?.isEmpty == false
        return try status(record, runtime, log: needsLog ? log(record, runtime) : nil)
    }

    // MARK: The log

    /// `runs show` returns at least one line and at most this many.
    static let lineRange = 1...2000
    static let defaultLines = 40

    /// The last `count` lines of a log that are not empty. A line ends at a line
    /// feed, at a carriage return, or at both: a progress bar writes each step
    /// after a carriage return, and each step is a line here.
    static func tail(_ text: String, lines count: Int) -> [String] {
        text.split(whereSeparator: \.isNewline).suffix(max(0, count)).map(String.init)
    }

    // MARK: Entries

    private static let runParameter = EntryParameter(
        "run", .string, "The id of a run, from the command that started it or from runs. Required.")

    static let listEntry = CatalogEntry(
        name: "runs",
        summary: "List every tracked run of a long script, newest first, each with its state: "
            + "running, done, failed or lost. Reads only.",
        readOnly: true,
        text: { data in
            let rows = (data["runs"]?.arrayValue ?? []).map { run -> String in
                let state = run["state"]?.stringValue ?? "?"
                guard let id = run["id"]?.stringValue else {
                    return "\(run["file"]?.stringValue ?? "?")  \(state)"
                }
                return [id, state, run["command"]?.stringValue ?? "?", run["started"]?.stringValue ?? "?"]
                    .joined(separator: "  ")
            }
            return rows.isEmpty ? "No runs." : rows.joined(separator: "\n")
        }
    ) { runtime, _ in
        // A run id starts with its time, so the names in reverse order are newest
        // first. A folder that is missing is no runs: a read makes no folder.
        let names = (runtime.listFolder(runtime.runsFolder) ?? [])
            .filter { $0.hasSuffix(".json") }.sorted(by: >)
        var runs: [JSONValue] = []
        for name in names {
            let id = String(name.dropLast(".json".count))
            guard isRunID(id), let data = runtime.readData(runtime.runsFolder + "/" + name),
                  let record = record(in: data, id: id) else {
                // never a crash, and never left out: the file is there
                runs.append(.object(["file": .string(name), "state": .string(State.unreadable.rawValue)]))
                continue
            }
            guard case .object(var row) = record.json else { continue }
            row.merge(try status(record, runtime).json) { _, new in new }
            runs.append(.object(row))
        }
        return .object(["folder": .string(runtime.runsFolder), "runs": .array(runs)])
    }

    static let showEntry = CatalogEntry(
        name: "runs_show",
        summary: "Show one tracked run: its record, its state, its exit code and the last lines of its log. "
            + "Reads only.",
        readOnly: true,
        parameters: [
            runParameter,
            EntryParameter("lines", .integer,
                           "How many lines of the log to return, from \(lineRange.lowerBound) to "
                               + "\(lineRange.upperBound). Default \(defaultLines)."),
        ],
        text: { data in
            var lines: [String] = []
            if let id = data["id"]?.stringValue { lines.append("run: \(id)") }
            for key in ["state", "exit_code", "command", "pid", "started", "cwd"] {
                switch data[key] {
                case .string(let text)?: lines.append("\(key): \(text)")
                case .int(let number)?: lines.append("\(key): \(number)")
                default: break
                }
            }
            let argv = Render.strings(data["argv"])
            if !argv.isEmpty { lines.append("argv: " + argv.joined(separator: " ")) }
            if let log = data["log"]?.stringValue { lines.append("log: \(log)") }
            let tail = Render.strings(data["lines"])
            if !tail.isEmpty { lines.append(contentsOf: [""] + tail) }
            return lines.joined(separator: "\n")
        }
    ) { runtime, arguments in
        let record = try record(arguments, runtime)
        let asked = arguments["lines"]?.intValue ?? defaultLines
        let count = min(max(asked, lineRange.lowerBound), lineRange.upperBound)
        let text = log(record, runtime)
        guard case .object(var result) = record.json else { return record.json }
        result.merge(try status(record, runtime, log: text).json) { _, new in new }
        result["lines"] = .array(tail(text ?? "", lines: count).map { .string($0) })
        return .object(result)
    }

    static let cancelEntry = CatalogEntry(
        name: "runs_cancel",
        summary: "Stop one tracked run: send SIGTERM to its process group. Refuses a run that is not running. "
            + "It does not wait, and it deletes nothing.",
        readOnly: false,
        parameters: [runParameter],
        text: { data in
            let id = data["run"]?.stringValue ?? "?"
            return "SIGTERM sent to run \(id). " + showHint(id)
        }
    ) { runtime, arguments in
        let record = try record(arguments, runtime)
        // Only a run whose own shell is in the process table gets the signal. A
        // run that ended has a pid that macOS can give to another program.
        let status = try status(record, runtime)
        guard status.state == .running else {
            throw TecopaFailure(
                .refused, "Run \(record.id) is not running: its state is \(status.state.rawValue).",
                hint: showHint(record.id))
        }
        do {
            // The run's shell leads its own session, so its group has its pid.
            try runtime.runner.signalGroup(record.pid, SIGTERM)
        } catch let failure as TecopaFailure {
            throw failure
        } catch {
            throw TecopaFailure(.environment,
                                "Could not signal run \(record.id): \(error.localizedDescription)")
        }
        return .object(["run": .string(record.id), "signalled": .bool(true)])
    }
}
