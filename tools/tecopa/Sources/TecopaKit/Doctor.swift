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

    static func venvRows(_ runtime: Runtime, repo: String) -> [JSONValue] {
        var rows: [JSONValue] = []
        let python = repo + "/.venv/bin/python"
        if !runtime.fileExists(python) {
            rows.append(row("venv", "fail", "No interpreter at \(python).",
                            hint: "Read docs/changing-things.md, Set up a machine."))
        } else if let version = try? runtime.exec(python, ["--version"], cwd: repo), version.exitCode == 0 {
            let found = trimmed(version.stdout)             // "Python 3.14.2"
            let wanted = trimmed(runtime.readFile(repo + "/.python-version") ?? "")
            if versionMatches(found: found, wanted: wanted) == false {
                rows.append(row("venv", "warn", "\(found), and .python-version asks for \(wanted)."))
            } else {
                rows.append(row("venv", "ok", found))
            }
        } else {
            rows.append(row("venv", "fail", "The interpreter at \(python) does not run.",
                            hint: "Read docs/changing-things.md, Set up a machine."))
        }

        let prep = repo + "/.venv-prep/bin/python"
        rows.append(runtime.fileExists(prep)
            ? row("venv_prep", "ok", prep)
            : row("venv_prep", "warn", "No interpreter at \(prep). Plate builds are not available.",
                  hint: "Read docs/changing-things.md, Set up a machine."))
        return rows
    }

    static func launcherRow(_ runtime: Runtime, repo: String?) -> JSONValue {
        guard runtime.fileExists(Launcher.appPath) else {
            return row("launcher", "warn", "The launcher is not installed at \(Launcher.appPath).",
                       hint: "Run scripts/macos/build_app.sh --install.")
        }
        let plist = Launcher.appPath + "/Contents/Info.plist"
        let read = try? runtime.exec("/usr/libexec/PlistBuddy", ["-c", "Print :TecopaRepoPath", plist])
        let built = trimmed(read?.stdout ?? "")
        guard read?.exitCode == 0, !built.isEmpty else {
            return row("launcher", "fail", "The launcher holds no repository path.",
                       hint: "Run scripts/macos/build_app.sh --install.")
        }
        // the launcher starts <built>/.venv/bin/python and shows an alert without it
        if !runtime.fileExists(built + "/.venv/bin/python") {
            return row("launcher", "fail",
                       "The launcher was built for \(built), and no engine is there.",
                       hint: "Run scripts/macos/build_app.sh --install.")
        }
        if let repo, built != repo {
            return row("launcher", "fail",
                       "The launcher was built for \(built). The repository is at \(repo).",
                       hint: "Run scripts/macos/build_app.sh --install.")
        }
        return row("launcher", "ok", "Built for \(built).")
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
            return [row("engine", "fail", "Port \(runtime.port) answers, but it is not Tecopa Plateworks.",
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
                            hint: "Start the engine with TECOPA_DEBUG=1. The launcher sets it."))
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
            return row("log", "warn", "No log at \(runtime.logPath). The launcher has not run on this Mac.")
        }
        return row("log", "ok", runtime.logPath, extra: ["lines": tail["lines"] ?? .array([])])
    }

    public static func run(_ runtime: Runtime) async -> JSONValue {
        var rows: [JSONValue] = []
        var repo: String?
        do {
            let found = try runtime.repo()
            repo = found
            rows.append(row("repo", "ok", found))
        } catch let failure as TecopaFailure {
            rows.append(row("repo", "fail", failure.message, hint: failure.hint))
        } catch {
            rows.append(row("repo", "fail", "\(error)"))
        }
        if let repo { rows += venvRows(runtime, repo: repo) }
        rows.append(launcherRow(runtime, repo: repo))
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
        summary: "Check the repo, both venvs, the launcher, the port, the debug gate and the log. Works with no engine.",
        readOnly: true,
        text: { render($0) }
    ) { runtime, _ in await run(runtime) }
}
