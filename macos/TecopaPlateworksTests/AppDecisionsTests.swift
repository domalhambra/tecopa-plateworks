import XCTest
import TecopaKit

final class AppDecisionsTests: XCTestCase {
    func testStartActions() {
        XCTAssertEqual(startAction(.adopt), .adopt)
        XCTAssertEqual(startAction(.foreign), .refuseForeign)
        XCTAssertEqual(startAction(.busy), .refuseNotAnswering)
        XCTAssertEqual(startAction(.none), .spawn)
    }

    func testQuitGate() {
        var q = QuitGate()
        XCTAssertEqual(q.answer(ownsEngine: false, forced: false), .now)
        q = QuitGate()
        XCTAssertEqual(q.answer(ownsEngine: true, forced: false), .readJobsFirst)
        XCTAssertEqual(q.answer(ownsEngine: true, forced: false), .alreadyWaiting)
        q.cancel()
        XCTAssertEqual(q.answer(ownsEngine: true, forced: false), .readJobsFirst)
        var f = QuitGate()
        XCTAssertEqual(f.answer(ownsEngine: true, forced: true), .stopWithoutConfirm)
    }

    func testAfterJobs() {
        XCTAssertEqual(afterJobs(.active(0)), .stopEngine)
        XCTAssertEqual(afterJobs(.active(2)), .confirm(jobs: 2))
        XCTAssertEqual(afterJobs(.unknown), .stopEngine)
        XCTAssertEqual(afterJobs(.timedOut), .confirm(jobs: nil))
    }

    func testAdoptNoteNamesBothVersions() {
        let note = adoptNote(bundleVersion: "128b3ad", engineVersion: "74cbc38")
        XCTAssertTrue(note?.contains("128b3ad") ?? false)
        XCTAssertTrue(note?.contains("74cbc38") ?? false)
        XCTAssertNil(adoptNote(bundleVersion: "128b3ad", engineVersion: "128b3ad"))
        XCTAssertTrue(adoptNote(bundleVersion: "128b3ad", engineVersion: nil)?.contains("unknown") ?? false)
    }

    func testTheQuitMarkerIsFreshFor15Seconds() {
        let now = Date(timeIntervalSince1970: 1000)
        XCTAssertTrue(quitMarkerIsFresh(modified: now.addingTimeInterval(-14), now: now))
        XCTAssertFalse(quitMarkerIsFresh(modified: now.addingTimeInterval(-15), now: now))
        XCTAssertFalse(quitMarkerIsFresh(modified: nil, now: now))
    }
}
