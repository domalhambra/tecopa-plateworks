import XCTest
@testable import TecopaKit

/// The real process runner, with programs that every Mac has. No test here uses
/// the network.
final class SeamsTests: XCTestCase {
    func testBothPipesDrainPast64K() throws {
        // a pipe holds 64 KB: a runner that reads one pipe at a time blocks for ever
        let result = try SystemProcessRunner().run(
            "/bin/sh", ["-c", "head -c 200000 /dev/zero; head -c 200000 /dev/zero >&2"], cwd: nil)
        XCTAssertEqual(result.exitCode, 0)
        XCTAssertEqual(result.stdout.utf8.count, 200_000)
        XCTAssertEqual(result.stderr.utf8.count, 200_000)
    }

    func testStdinIsTheNullDevice() throws {
        // with the tool's own stdin, cat would wait for the terminal or the MCP client
        let result = try SystemProcessRunner(timeout: 5).run("/bin/cat", [], cwd: nil)
        XCTAssertEqual(result, ProcessResult(exitCode: 0, stdout: "", stderr: ""))
    }

    func testAMissingExecutableIsAnEnvironmentFailure() {
        XCTAssertThrowsError(try Runtime().exec("/no/such/program", [])) { error in
            let failure = error as? TecopaFailure
            XCTAssertEqual(failure?.kind, .environment)
            XCTAssertTrue(failure?.message.contains("/no/such/program") ?? false)
        }
    }

    func testAChildPastTheDeadlineIsTerminated() {
        let start = Date()
        XCTAssertThrowsError(try SystemProcessRunner(timeout: 0.5).run("/bin/sleep", ["30"], cwd: nil)) { error in
            let failure = error as? TecopaFailure
            XCTAssertEqual(failure?.kind, .environment)
            XCTAssertEqual(failure?.message, "sleep did not finish within 0.5 seconds.")
        }
        XCTAssertLessThan(Date().timeIntervalSince(start), 2)
    }

    func testAChildThatIgnoresTheTerminationSignalIsKilled() {
        let start = Date()
        XCTAssertThrowsError(try SystemProcessRunner(timeout: 0.5).run(
            "/bin/sh", ["-c", "trap '' TERM; while :; do sleep 1; done"], cwd: nil)) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
        XCTAssertLessThan(Date().timeIntervalSince(start), 6)
    }

    func testAChildEndedByASignalReports128PlusTheSignal() throws {
        // SIGTERM is 15. A plain 15 would read as the child's own exit code.
        let result = try SystemProcessRunner().run("/bin/sh", ["-c", "kill -TERM $$"], cwd: nil)
        XCTAssertEqual(result.exitCode, 143)
        let plain = try SystemProcessRunner().run("/bin/sh", ["-c", "exit 15"], cwd: nil)
        XCTAssertEqual(plain.exitCode, 15)
    }

    func testTheDeadlineMessageHasNoTrailingZero() {
        XCTAssertEqual(secondsText(300), "300")
        XCTAssertEqual(secondsText(0.5), "0.5")
    }
}
