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
}
