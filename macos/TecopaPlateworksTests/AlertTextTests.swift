import XCTest

final class AlertTextTests: XCTestCase {
    func testSpecCopy() {
        XCTAssertEqual(AlertText.portInUse, "Port 8848 is in use by another program.")
        XCTAssertEqual(AlertText.quitConfirm(jobs: 3), "3 jobs are running. Quitting ends them.")
        XCTAssertEqual(AlertText.quitConfirm(jobs: 1), "1 job is running. Quitting ends it.")
    }

    func testEngineStoppedNamesTheLog() {
        let log = "/Users/x/Library/Logs/TecopaPlateworks.log"
        XCTAssertTrue(AlertText.engineStopped(status: 1, log: log).contains(log))
    }

    func testBadSettingsNamesTheFile() {
        let path = "/Users/x/Library/Application Support/Tecopa Plateworks/settings.json"
        XCTAssertEqual(AlertText.badSettings(path: path),
                       "Tecopa Plateworks could not read its settings: \(path) is not valid JSON.")
    }
}
