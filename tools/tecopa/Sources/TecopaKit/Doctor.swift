import Foundation

/// The checks that need no engine. `doctor` is the command for the worst case: the
/// engine does not start and nothing else can say why. It never throws, and one
/// failed check never stops the others.
public enum Doctor {
    static func row(_ name: String, _ status: String, _ detail: String,
                    hint: String? = nil, extra: [String: JSONValue] = [:]) -> JSONValue {
        var out: [String: JSONValue] = [
            "name": .string(name), "status": .string(status), "detail": .string(detail)]
        if let hint { out["hint"] = .string(hint) }
        for (key, value) in extra { out[key] = value }
        return .object(out)
    }

    static func trimmed(_ text: String) -> String {
        text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// True if the interpreter's version starts with ALL the components of the
    /// wanted version: 3.14 matches 3.14.2, 3.1 does not, and 3.14.1 does not match
    /// 3.14.10. nil when `wanted` is not dot-separated digits ("cpython-3.14"): such
    /// a value is not compared.
    static func versionMatches(found: String, wanted: String) -> Bool? {
        let wantedParts = wanted.split(separator: ".", omittingEmptySubsequences: false)
        guard !wantedParts.isEmpty,
              wantedParts.allSatisfy({ part in
                  !part.isEmpty && part.utf8.allSatisfy {
                      (UInt8(ascii: "0")...UInt8(ascii: "9")).contains($0)
                  }
              }) else { return nil }
        // "Python 3.14.2": the version is the token after "Python "
        guard found.hasPrefix("Python "),
              let token = found.dropFirst("Python ".count).split(whereSeparator: \.isWhitespace).first
        else { return false }
        return token.split(separator: ".", omittingEmptySubsequences: false).starts(with: wantedParts)
    }

    /// The two interpreters of one layout: the engine's, then the prep one.
    static func venvRows(_ runtime: Runtime, layout: EngineLayout) -> [JSONValue] {
        var rows: [JSONValue] = []
        let root = layout.codeRoot
        let python = layout.enginePython
        if !runtime.fileExists(python) {
            rows.append(row("venv", "fail", "No interpreter at \(python).",
                            hint: "Read docs/changing-things.md, Set up a machine."))
        } else if let version = try? runtime.exec(python, ["--version"], cwd: root), version.exitCode == 0 {
            let found = trimmed(version.stdout)             // "Python 3.14.2"
            let wanted = trimmed(runtime.readFile(root + "/.python-version") ?? "")
            if versionMatches(found: found, wanted: wanted) == false {
                rows.append(row("venv", "warn", "\(found), and .python-version asks for \(wanted)."))
            } else {
                rows.append(row("venv", "ok", found))
            }
        } else {
            rows.append(row("venv", "fail", "The interpreter at \(python) does not run.",
                            hint: "Read docs/changing-things.md, Set up a machine."))
        }

        let prep = layout.prepPython
        if case .bundle = layout {
            // In the app, plate builds and bakes run in the bundled prep interpreter:
            // it must run, as the engine's must.
            let ran = runtime.fileExists(prep) ? try? runtime.exec(prep, ["--version"], cwd: root) : nil
            rows.append(ran?.exitCode == 0
                ? row("venv_prep", "ok", trimmed(ran?.stdout ?? ""))
                : row("venv_prep", "fail", "The bundled interpreter \(prep) does not run.",
                      hint: "Reinstall the app."))
            return rows
        }
        rows.append(runtime.fileExists(prep)
            ? row("venv_prep", "ok", prep)
            : row("venv_prep", "warn", "No interpreter at \(prep). Plate builds are not available.",
                  hint: "Read docs/changing-things.md, Set up a machine."))
        return rows
    }

    /// The Tecopa Plateworks app at `Launcher.appPath`: its id, its engine version,
    /// and both bundled interpreters. A missing app is a warning: the tool works
    /// without it, and `engine start` says what is missing.
    static func appRow(_ runtime: Runtime) -> JSONValue {
        let path = Launcher.appPath(runtime)
        guard runtime.fileExists(path) else {
            return row("app", "warn", "Tecopa Plateworks is not installed at \(path).",
                       hint: "Set TECOPA_APP to a built copy, or install the app.")
        }
        let layout = EngineLayout.bundle(URL(fileURLWithPath: path))
        let id = layout.infoValue("CFBundleIdentifier", runtime)
        guard id == Launcher.bundleID else {
            return row("app", "fail",
                       "The app at \(path) is \(id ?? "unidentified"), not \(Launcher.bundleID).")
        }
        guard let version = layout.infoValue("TecopaEngineVersion", runtime) else {
            return row("app", "fail", "The app at \(path) has no TecopaEngineVersion.")
        }
        for python in [layout.enginePython, layout.prepPython] {
            let ran = try? runtime.exec(python, ["--version"])
            guard ran?.exitCode == 0 else {
                return row("app", "fail", "The bundled interpreter \(python) does not run.")
            }
        }
        return row("app", "ok", "\(Launcher.bundleID), engine \(version), both interpreters run.")
    }

    static func engineRows(_ runtime: Runtime) async -> [JSONValue] {
        let timeout: TimeInterval = 3
        let reply: EngineClient.Reply
        switch await runtime.client.probe("/readyz", timeout: timeout) {
        case .reply(let found):
            reply = found
        case .noAnswer:
            // `engine start` controls only the launcher's engine
            return [row("engine", "warn", "No engine answers on port \(runtime.port).",
                        hint: runtime.port == Launcher.port
                            ? "Run `tecopa engine start`."
                            : "Start the development engine on that port.")]
        case .timedOut:
            return [row("engine", "warn",
                        "Port \(runtime.port) accepts connections but did not answer within \(secondsText(timeout)) seconds.",
                        hint: "An engine may be busy with a render. Run `tecopa logs`.")]
        }
        // the debug gate of another program is not this tool's business: no second row
        guard EngineClient.isTecopa(reply) else {
            return [row("engine", "fail", runtime.client.notTecopaMessage,
                        hint: "Quit the other program on that port.")]
        }
        let plates = reply.json["regions"]?.arrayValue ?? []
        var rows: [JSONValue] = []
        if reply.json["ready"]?.boolValue == true {
            rows.append(row("engine", "ok", "Ready on port \(runtime.port), \(plates.count) plates."))
        } else {
            let bad = plates.filter { $0["ready"]?.boolValue != true }
                .compactMap { $0["id"]?.stringValue }
            rows.append(row(
                "engine", "fail",
                bad.isEmpty
                    ? "The engine answers and reports that it is not ready, with no plate named."
                    : "The engine answers, and these plates cannot render: \(bad.joined(separator: ", ")).",
                hint: "Run `tecopa regions verify`. Then read docs/changing-things.md, Repair an orphaned DEM."))
        }
        do {
            _ = try await runtime.client.debug("/engine")
            rows.append(row("debug_gate", "ok", "The debug routes are on."))
        } catch let failure as TecopaFailure where EngineClient.isGateOff(failure) {
            rows.append(row("debug_gate", "warn", "The debug routes are off.",
                            hint: "Start the engine with TECOPA_DEBUG=1. The app sets it."))
        } catch {
            // the gate's state is not known, so it is not reported as off
            let said = (error as? TecopaFailure)?.message ?? "\(error)"
            rows.append(row("debug_gate", "warn", "The debug routes did not answer: \(said)"))
        }
        return rows
    }

    static func logRow(_ runtime: Runtime) -> JSONValue {
        let tail = LogReader.read(path: runtime.logPath, lines: 15, grep: nil, since: nil)
        guard tail["exists"]?.boolValue == true else {
            return row("log", "warn", "No log at \(runtime.logPath). The app has not run on this Mac.")
        }
        return row("log", "ok", runtime.logPath, extra: ["lines": tail["lines"] ?? .array([])])
    }

    public static func run(_ runtime: Runtime) async -> JSONValue {
        var rows: [JSONValue] = []
        if case .bundle(let app)? = try? runtime.engineLayout() {
            // The app has no repo: the bundle's code and its two interpreters.
            let layout = EngineLayout.bundle(app)
            let marker = layout.codeRoot + "/" + RepoLocator.marker
            rows.append(runtime.readFile(marker) != nil
                ? row("code", "ok", layout.codeRoot)
                : row("code", "fail", "The app's engine code cannot be read: \(marker).",
                      hint: "Reinstall the app."))
            rows += venvRows(runtime, layout: layout)
            return await finish(rows, runtime)
        }
        var repo: String?
        do {
            let found = try runtime.repo()
            repo = found
            // The locator only asks if the marker is there. macOS guards the contents
            // of ~/Documents and not the names, so only a read proves the access.
            if runtime.readFile(found + "/" + RepoLocator.marker) != nil {
                rows.append(row("repo", "ok", found))
            } else {
                rows.append(row(
                    "repo", "fail",
                    "The repo is at \(found), and \(RepoLocator.marker) there cannot be read.",
                    hint: "macOS can refuse a program the Documents folder. Allow it in System Settings, "
                        + "Privacy & Security, Files and Folders."))
            }
        } catch let failure as TecopaFailure {
            rows.append(row("repo", "fail", failure.message, hint: failure.hint))
        } catch {
            rows.append(row("repo", "fail", "\(error)"))
        }
        if let repo { rows += venvRows(runtime, layout: .repo(repo)) }
        return await finish(rows, runtime)
    }

    /// The rows that do not depend on the layout, and the counts.
    private static func finish(_ found: [JSONValue], _ runtime: Runtime) async -> JSONValue {
        var rows = found
        rows.append(appRow(runtime))
        rows += await engineRows(runtime)
        rows.append(logRow(runtime))

        func count(_ status: String) -> JSONValue {
            .int(Int64(rows.filter { $0["status"]?.stringValue == status }.count))
        }
        return .object([
            "checks": .array(rows),
            "ok_count": count("ok"), "warn_count": count("warn"), "fail_count": count("fail"),
        ])
    }

    static func render(_ report: JSONValue) -> String {
        var lines: [String] = []
        for check in report["checks"]?.arrayValue ?? [] {
            let status = (check["status"]?.stringValue ?? "?").padding(toLength: 5, withPad: " ", startingAt: 0)
            let name = (check["name"]?.stringValue ?? "?").padding(toLength: 11, withPad: " ", startingAt: 0)
            lines.append("\(status) \(name) \(check["detail"]?.stringValue ?? "")")
            if let hint = check["hint"]?.stringValue { lines.append("      hint: \(hint)") }
            if check["name"]?.stringValue == "log" {
                for line in check["lines"]?.arrayValue ?? [] {
                    lines.append("      | \(line.stringValue ?? "")")
                }
            }
        }
        return lines.joined(separator: "\n")
    }

    static let entry = CatalogEntry(
        name: "doctor",
        summary: "Check the repo (in the app: its engine code), both interpreters, the app, the port, the debug "
            + "gate and the log. Works with no engine.",
        readOnly: true,
        text: { render($0) }
    ) { runtime, _ in await run(runtime) }
}
