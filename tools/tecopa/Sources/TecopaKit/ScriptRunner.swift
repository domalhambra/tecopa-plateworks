import Foundation

/// Runs the repo's Python scripts. The table is an allowlist and the one place that
/// decides a script's venv (CLAUDE.md, invariant 13: the region-prep stack never
/// enters .venv). A script with no row does not run, and no flag overrides the table.
public enum ScriptRunner {
    public enum Venv: String, Sendable {
        case app = ".venv"
        case prep = ".venv-prep"
    }

    /// Add a row in the same change as the command that needs it.
    public static let table: [String: Venv] = [
        "scripts/verify_regions.py": .app,
    ]

    public static func run(_ script: String, _ arguments: [String],
                           _ runtime: Runtime) throws -> ProcessResult {
        guard let venv = table[script] else {
            throw TecopaFailure(
                .usage, "\(script) has no row in the script table.",
                hint: "Add a row to ScriptRunner.table in the same change as the command.")
        }
        let repo = try runtime.repo()
        let python = repo + "/" + venv.rawValue + "/bin/python"
        guard runtime.fileExists(python) else {
            throw TecopaFailure(.environment, "No interpreter at \(python).",
                                hint: "Read docs/changing-things.md, Set up a machine.")
        }
        return try runtime.exec(python, [script] + arguments, cwd: repo)
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
