import Foundation

/// The launcher log. The launcher and the engine it starts both append to one file,
/// so three line shapes are mixed in it:
///   [2026-09-02 19:56:17 +0000] launcher line      (UTC, in brackets)
///   2026-09-02T12:56:20 INFO tecopa.api message    (the engine's logger, local time)
///   INFO:     Started server process [13779]       (uvicorn, no timestamp)
public enum LogReader {
    /// Read at most this much from the end of the file.
    static let tailBytes: UInt64 = 2_000_000

    private static let launcherStamp: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd HH:mm:ss Z"
        return f
    }()

    private static let engineStamp: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f
    }()

    /// "90s", "30m", "2h", "1d" before `now`.
    public static func parseSince(_ text: String, now: Date) throws -> Date {
        let units: [Character: Double] = ["s": 1, "m": 60, "h": 3600, "d": 86400]
        guard let unit = text.last, let seconds = units[unit],
              let count = Double(text.dropLast()), count >= 0 else {
            throw TecopaFailure(.usage, "--since takes a number and a unit: 90s, 30m, 2h, 1d.")
        }
        return now.addingTimeInterval(-count * seconds)
    }

    static func stamp(of line: String) -> Date? {
        if line.hasPrefix("["), let end = line.firstIndex(of: "]") {
            return launcherStamp.date(from: String(line[line.index(after: line.startIndex)..<end]))
        }
        let head = Array(line.prefix(19))
        if head.count == 19, head[4] == "-", head[10] == "T" {
            return engineStamp.date(from: String(head))
        }
        return nil
    }

    /// The last `lines` lines that pass both filters. A line with no timestamp takes
    /// the timestamp of the nearest stamped line above it, so a traceback stays with
    /// the request that raised it.
    public static func filter(_ text: String, lines: Int, grep: String?, since: Date?) -> [String] {
        var kept: [String] = []
        var current: Date?
        for raw in text.split(separator: "\n", omittingEmptySubsequences: true) {
            let line = String(raw)
            if let found = stamp(of: line) { current = found }
            if let since {
                guard let current, current >= since else { continue }
            }
            if let grep, !grep.isEmpty, line.range(of: grep, options: .caseInsensitive) == nil {
                continue
            }
            kept.append(line)
        }
        return Array(kept.suffix(max(0, lines)))
    }

    public static func read(path: String, lines: Int, grep: String?, since: Date?) -> JSONValue {
        guard let handle = FileHandle(forReadingAtPath: path) else {
            return .object(["path": .string(path), "exists": .bool(false), "lines": .array([])])
        }
        defer { try? handle.close() }
        let size = (try? handle.seekToEnd()) ?? 0
        let start = size > tailBytes ? size - tailBytes : 0
        try? handle.seek(toOffset: start)
        let data = (try? handle.readToEnd()) ?? Data()
        var text = String(decoding: data, as: UTF8.self)
        // a read that starts inside the file starts inside a line: drop that part
        if start > 0, let newline = text.firstIndex(of: "\n") {
            text = String(text[text.index(after: newline)...])
        }
        let kept = filter(text, lines: lines, grep: grep, since: since)
        return .object([
            "path": .string(path), "exists": .bool(true),
            "lines": .array(kept.map { .string($0) }),
        ])
    }

    static let entry = CatalogEntry(
        name: "logs",
        summary: "Read the tail of the launcher log, which also holds the engine's output.",
        readOnly: true,
        parameters: [
            EntryParameter("lines", .integer, "How many lines to return. Default 50."),
            EntryParameter("grep", .string, "Keep only lines that contain this text, in any letter case."),
            EntryParameter("since", .string, "Keep only lines newer than this age: 90s, 30m, 2h, 1d."),
        ],
        text: { data in
            guard data["exists"]?.boolValue == true else {
                return "No log at \(data["path"]?.stringValue ?? "?")."
            }
            return (data["lines"]?.arrayValue ?? []).compactMap { $0.stringValue }.joined(separator: "\n")
        }
    ) { runtime, arguments in
        let since = try arguments["since"]?.stringValue.map { try parseSince($0, now: Date()) }
        return read(path: runtime.logPath,
                    lines: arguments["lines"]?.intValue ?? 50,
                    grep: arguments["grep"]?.stringValue,
                    since: since)
    }
}
