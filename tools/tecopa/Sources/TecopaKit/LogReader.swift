import Foundation

/// The launcher log. The launcher and the engine it starts both append to one file,
/// so three line shapes are mixed in it:
///   [2026-09-02 19:56:17 +0000] launcher line      (UTC, in brackets)
///   2026-09-02T12:56:20 INFO tecopa.api message    (the engine's logger, local time)
///   INFO:     Started server process [13779]       (uvicorn, no timestamp)
public enum LogReader {
    /// Read at most this much from the end of the file.
    public static let tailBytes: UInt64 = 2_000_000
    /// The `logs` entry returns at least one line and at most this many.
    static let lineRange = 1...2000

    /// What `since` does, for the MCP schema and the CLI help. It states the rule,
    /// because an empty result can be read as "no errors".
    public static let sinceSummary =
        "Keep only lines newer than this age: 90s, 30m, 2h, 1d. A line with no timestamp "
        + "takes the timestamp of the nearest stamped line above it, so on a long-running "
        + "engine recent uvicorn lines can be dropped. Use lines alone when unsure."

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

    /// "90s", "30m", "2h", "1d" before `now`. The number is ASCII digits with at most
    /// one "." fraction, and one unit follows it. `Double` alone also reads "inf",
    /// "1e3" and "0x10", so the bytes are checked first.
    public static func parseSince(_ text: String, now: Date) throws -> Date {
        let refusal = TecopaFailure(.usage, "--since takes a number and a unit: 90s, 30m, 2h, 1d.")
        let units: [UInt8: Double] = [
            UInt8(ascii: "s"): 1, UInt8(ascii: "m"): 60, UInt8(ascii: "h"): 3600, UInt8(ascii: "d"): 86400]
        let bytes = Array(text.utf8)
        guard let unit = bytes.last, let seconds = units[unit] else { throw refusal }
        let number = bytes.dropLast()
        let parts = number.split(separator: UInt8(ascii: "."), omittingEmptySubsequences: false)
        guard parts.count == 1 || parts.count == 2,
              parts.allSatisfy({ part in
                  !part.isEmpty && part.allSatisfy { (UInt8(ascii: "0")...UInt8(ascii: "9")).contains($0) }
              }),
              let count = Double(String(decoding: number, as: UTF8.self)),
              (count * seconds).isFinite else {
            throw refusal
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

    /// `tailBytes` is a parameter so that a test can cut a small file.
    public static func read(path: String, lines: Int, grep: String?, since: Date?,
                            tailBytes: UInt64 = LogReader.tailBytes) -> JSONValue {
        guard let handle = FileHandle(forReadingAtPath: path) else {
            return .object(["path": .string(path), "exists": .bool(false), "lines": .array([])])
        }
        defer { try? handle.close() }
        let size = (try? handle.seekToEnd()) ?? 0
        let start = size > tailBytes ? size - tailBytes : 0
        // A read that starts inside the file can start inside a line. Begin one byte
        // before the cut and drop through the first newline. If the cut is on a line
        // boundary, that byte is the newline and no line is lost. If the cut is inside
        // a line, only that partial line is dropped.
        try? handle.seek(toOffset: start > 0 ? start - 1 : 0)
        var data = (try? handle.readToEnd()) ?? Data()
        if start > 0, let newline = data.firstIndex(of: 0x0A) {
            data = Data(data[data.index(after: newline)...])
        }
        let text = String(decoding: data, as: UTF8.self)
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
            EntryParameter("lines", .integer, "How many lines to return, from 1 to 2000. Default 50."),
            EntryParameter("grep", .string, "Keep only lines that contain this text, in any letter case."),
            EntryParameter("since", .string, sinceSummary),
        ],
        text: { data in
            guard data["exists"]?.boolValue == true else {
                return "No log at \(data["path"]?.stringValue ?? "?")."
            }
            return (data["lines"]?.arrayValue ?? []).compactMap { $0.stringValue }.joined(separator: "\n")
        }
    ) { runtime, arguments in
        let since = try arguments["since"]?.stringValue.map { try parseSince($0, now: Date()) }
        let asked = arguments["lines"]?.intValue ?? 50
        return read(path: runtime.logPath,
                    lines: min(max(asked, lineRange.lowerBound), lineRange.upperBound),
                    grep: arguments["grep"]?.stringValue,
                    since: since)
    }
}
