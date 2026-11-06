import XCTest
// Not @testable: this file sees only what the app target sees, so a type that is
// not public fails to compile here.
import TecopaKit

final class PublicAPITests: XCTestCase {
    func testAReplyCanBeBuiltOutsideTheModule() {
        let reply = EngineClient.Reply(
            status: 503, json: .object(["ready": .bool(false), "regions": .array([])]))
        XCTAssertTrue(EngineClient.isTecopa(reply))
    }

    func testReadJobsIsPublicAndCountsRunningAndQueued() async {
        let w = FakeWorld()
        w.serve("/api/debug/jobs", 200,
                #"{"jobs":[{"state":"running"},{"state":"queued"},{"state":"done"}]}"#)
        let read: JobsRead = await Launcher.readJobs(w.runtime())
        XCTAssertEqual(read, .active(2))
    }
}
