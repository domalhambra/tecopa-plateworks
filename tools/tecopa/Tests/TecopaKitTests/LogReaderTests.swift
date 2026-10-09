import XCTest
@testable import TecopaKit

final class LogReaderTests: XCTestCase {
    // the launcher stamps in UTC with brackets; uvicorn's own lines have no stamp
    private let log = """
    [2026-10-22 10:00:00 +0000] starting engine
    INFO:     Started server process [100]
    [2026-10-22 11:00:00 +0000] engine ready
    INFO:     127.0.0.1:5000 - "GET /readyz HTTP/1.1" 200 OK
    Traceback (most recent call last):
      File "app/render.py", line 1, in rasterize
    ValueError: bad crop
    """

    private func date(_ text: String) -> Date {
        ISO8601DateFormatter().date(from: text)!
    }

    func testLinesKeepsTheTail() {
        let kept = LogReader.filter(log, lines: 2, grep: nil, since: nil)
        XCTAssertEqual(kept, ["  File \"app/render.py\", line 1, in rasterize", "ValueError: bad crop"])
    }

    func testGrepIsACaseInsensitiveSubstring() {
        let kept = LogReader.filter(log, lines: 50, grep: "valueerror", since: nil)
        XCTAssertEqual(kept, ["ValueError: bad crop"])
    }

    func testSinceDropsOlderLinesAndUnstampedLinesInheritTheStampAbove() {
        let kept = LogReader.filter(log, lines: 50, grep: nil, since: date("2026-10-22T10:30:00Z"))
        XCTAssertEqual(kept.first, "[2026-10-22 11:00:00 +0000] engine ready")
        XCTAssertEqual(kept.count, 5)
        XCTAssertFalse(kept.contains("INFO:     Started server process [100]"))
    }

    func testSinceParsesADuration() throws {
        let now = date("2026-10-22T12:00:00Z")
        XCTAssertEqual(try LogReader.parseSince("30m", now: now), date("2026-10-22T11:30:00Z"))
        XCTAssertEqual(try LogReader.parseSince("2h", now: now), date("2026-10-22T10:00:00Z"))
        XCTAssertEqual(try LogReader.parseSince("1d", now: now), date("2026-10-21T12:00:00Z"))
    }

    func testABadDurationIsAUsageFailure() {
        XCTAssertThrowsError(try LogReader.parseSince("5x", now: Date())) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .usage)
        }
    }

    func testAMissingLogIsDataAndNotAFailure() {
        let value = LogReader.read(path: "/no/such/file.log", lines: 10, grep: nil, since: nil)
        XCTAssertEqual(value["exists"], .bool(false))
        XCTAssertEqual(value["lines"], .array([]))
    }

    func testSinceReadsAnEngineLoggerStampAsLocalTime() {
        // the engine's logger writes local time with no zone. Read as UTC, the line
        // would move by the zone's offset and `since` would keep or drop the wrong lines.
        let moment = date("2026-10-22T18:30:00Z")
        let local = DateFormatter()
        local.locale = Locale(identifier: "en_US_POSIX")
        local.timeZone = TimeZone.current
        local.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        let stamped = "\(local.string(from: moment)) INFO tecopa.api render done"
        let text = stamped + "\nINFO:     an unstamped line below it"

        XCTAssertEqual(LogReader.stamp(of: stamped), moment)
        let kept = LogReader.filter(text, lines: 50, grep: nil, since: moment.addingTimeInterval(-60))
        XCTAssertEqual(kept, [stamped, "INFO:     an unstamped line below it"])
        let dropped = LogReader.filter(text, lines: 50, grep: nil, since: moment.addingTimeInterval(60))
        XCTAssertEqual(dropped, [])
    }

    func testSinceRefusesANumberThatIsNotPlainDigits() throws {
        // Double("inf"), Double("1e3") and Double("0x10") are all numbers
        let refused = [
            "infs", "nans", "1e3s", "0x10s", "s", "", "5", "-5m", "+5m", " 5m", "5 m", "5m ",
            "1.2.3h", ".5h", "5.h", "1,5h", "５m", "5ｍ", "5M", "5ms",
        ]
        for text in refused {
            XCTAssertThrowsError(try LogReader.parseSince(text, now: Date()), text) { error in
                XCTAssertEqual((error as? TecopaFailure)?.kind, .usage, text)
            }
        }
        let now = date("2026-10-22T12:00:00Z")
        XCTAssertEqual(try LogReader.parseSince("90s", now: now), date("2026-10-22T11:58:30Z"))
        XCTAssertEqual(try LogReader.parseSince("1.5h", now: now), date("2026-10-22T10:30:00Z"))
        XCTAssertEqual(try LogReader.parseSince("0s", now: now), now)
        XCTAssertEqual(try LogReader.parseSince("007m", now: now), date("2026-10-22T11:53:00Z"))
    }

    /// A folder for one test, removed when the test ends.
    private func temporaryFolder() throws -> URL {
        let folder = FileManager.default.temporaryDirectory
            .appendingPathComponent("tecopa-tests-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: folder) }
        return folder
    }

    private func lines(_ value: JSONValue) -> [String] {
        (value["lines"]?.arrayValue ?? []).compactMap { $0.stringValue }
    }

    func testACutInsideALineDropsOnlyThatPartialLine() throws {
        // ten lines of eight bytes each: "line-00\n" is bytes 0 to 7
        let path = try temporaryFolder().appendingPathComponent("log").path
        let all = (0..<10).map { String(format: "line-%02d", $0) }
        try (all.joined(separator: "\n") + "\n").write(toFile: path, atomically: true, encoding: .utf8)

        // the last 20 bytes start at byte 60, inside line-07
        let cut = lines(LogReader.read(path: path, lines: 50, grep: nil, since: nil, tailBytes: 20))
        XCTAssertEqual(cut, ["line-08", "line-09"])
        XCTAssertFalse(cut.contains { $0.hasSuffix("-07") })

        // the last 9 bytes start at byte 71, the newline that ends line-08
        let onNewline = lines(LogReader.read(path: path, lines: 50, grep: nil, since: nil, tailBytes: 9))
        XCTAssertEqual(onNewline, ["line-09"])
    }

    func testACutOnALineBoundaryDropsNoLine() throws {
        let path = try temporaryFolder().appendingPathComponent("log").path
        let all = (0..<10).map { String(format: "line-%02d", $0) }
        try (all.joined(separator: "\n") + "\n").write(toFile: path, atomically: true, encoding: .utf8)

        // the last 24 bytes are exactly the last three lines
        let exact = lines(LogReader.read(path: path, lines: 50, grep: nil, since: nil, tailBytes: 24))
        XCTAssertEqual(exact, ["line-07", "line-08", "line-09"])

        // a file that fits is read whole, and so is a file of exactly the limit
        let whole = lines(LogReader.read(path: path, lines: 50, grep: nil, since: nil, tailBytes: 80))
        XCTAssertEqual(whole, all)
        let roomy = lines(LogReader.read(path: path, lines: 50, grep: nil, since: nil))
        XCTAssertEqual(roomy, all)
    }

    func testTheLogsEntryClampsLinesToItsRange() async throws {
        let home = try temporaryFolder()
        let logs = home.appendingPathComponent("Library/Logs")
        try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        let all = (1...2100).map { "line \($0)" }
        try (all.joined(separator: "\n") + "\n").write(
            to: logs.appendingPathComponent("TecopaPlateworks.log"), atomically: true, encoding: .utf8)
        let runtime = FakeWorld().runtime(home: home.path)

        func returned(_ asked: JSONValue?) async -> [String] {
            let (env, failure) = await Catalog.call("logs", runtime, asked.map { ["lines": $0] } ?? [:])
            XCTAssertNil(failure)
            XCTAssertEqual(env["data"]?["exists"], .bool(true))
            return (env["data"]?["lines"]?.arrayValue ?? []).compactMap { $0.stringValue }
        }

        var got = await returned(.int(0))
        XCTAssertEqual(got, ["line 2100"])
        got = await returned(.int(-5))
        XCTAssertEqual(got, ["line 2100"])
        got = await returned(.int(3))
        XCTAssertEqual(got, ["line 2098", "line 2099", "line 2100"])
        got = await returned(.int(5000))
        XCTAssertEqual(got.count, 2000)
        XCTAssertEqual(got.first, "line 101")
        got = await returned(.int(Int64.max))
        XCTAssertEqual(got.count, 2000)
        got = await returned(nil)
        XCTAssertEqual(got.count, 50)
    }
}
