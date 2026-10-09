import XCTest
@testable import TecopaKit

final class EngineClientTests: XCTestCase {
    func testNoReplyIsEngineUnreachableWithTheDoctorHint() async {
        let world = FakeWorld()
        do {
            _ = try await world.runtime().client.get("/api/regions")
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .engineUnreachable)
            XCTAssertEqual(f.hint, "Run `tecopa doctor`.")
            XCTAssertTrue(f.message.contains("8848"))
        } catch { XCTFail("\(error)") }
    }

    func testAnEngineRefusalKeepsTheEnginesOwnBody() async {
        let world = FakeWorld()
        world.serve("/api/regions", 503, #"{"detail":"DEM bounds drift: lassen_ca"}"#)
        do {
            _ = try await world.runtime().client.get("/api/regions")
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .refused)
            XCTAssertEqual(f.status, 503)
            XCTAssertEqual(f.body?["detail"]?.stringValue, "DEM bounds drift: lassen_ca")
        } catch { XCTFail("\(error)") }
    }

    func testRawReturnsA503AsAReply() async throws {
        // /readyz answers 503 when a plate cannot render: that is an answer, not an outage
        let world = FakeWorld()
        world.serve("/readyz", 503, #"{"ready":false,"regions":[]}"#)
        let reply = try await world.runtime().client.raw("/readyz")
        XCTAssertEqual(reply.status, 503)
        XCTAssertEqual(reply.json["ready"], .bool(false))
    }

    func testAClosedGateNamesTheVariable() async {
        let world = FakeWorld()
        world.serve("/api/debug/jobs", 404, #"{"detail":"Not Found"}"#)
        do {
            _ = try await world.runtime().client.debug("/jobs")
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .refused)
            XCTAssertTrue(f.message.contains("debug routes are off"))
            XCTAssertTrue(f.hint?.contains("TECOPA_DEBUG=1") ?? false)
        } catch { XCTFail("\(error)") }
    }

    func testAnUnknownSessionIsNotMistakenForAClosedGate() async {
        let world = FakeWorld()
        world.serve("/api/debug/sessions/ab", 404, #"{"detail":"Unknown session"}"#)
        do {
            _ = try await world.runtime().client.debug("/sessions/ab")
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.body?["detail"]?.stringValue, "Unknown session")
            XCTAssertFalse(f.message.contains("debug routes are off"))
        } catch { XCTFail("\(error)") }
    }
}
