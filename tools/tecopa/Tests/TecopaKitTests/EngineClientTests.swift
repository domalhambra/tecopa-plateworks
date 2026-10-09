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

    func testEveryRequestGoesTo127001OnTheGivenPort() async {
        let world = FakeWorld()
        world.serve("/readyz", 200, FakeWorld.readyBody)
        world.serve("/api/regions", 200, #"[{"id":"lassen_ca"}]"#)
        world.serve("/api/debug/engine", 200, #"{"engine":"tecopa-plateworks"}"#)
        for name in ["engine_status", "regions", "jobs"] {
            _ = await Catalog.call(name, world.runtime(port: 9000), [:])
        }
        XCTAssertEqual(world.requests.count, 5)
        for url in world.requests {
            XCTAssertEqual(url.host, "127.0.0.1", url.absoluteString)
            XCTAssertEqual(url.port, 9000, url.absoluteString)
        }
    }

    func testAPathThatDoesNotStartWithASlashIsRefused() async {
        // "http://127.0.0.1:8848" + "@example.com/x" is a URL whose host is example.com
        let world = FakeWorld()
        do {
            _ = try await world.runtime().client.raw("@example.com/x")
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .usage)
        } catch { XCTFail("\(error)") }
        XCTAssertEqual(world.requests, [])
    }

    func testAPortOutOfRangeIsRefused() async {
        let world = FakeWorld()
        for port in [0, 65536, -1] {
            do {
                _ = try await world.runtime(port: port).client.raw("/readyz")
                XCTFail("expected a failure")
            } catch let f as TecopaFailure {
                XCTAssertEqual(f.kind, .usage, "\(port)")
                XCTAssertTrue(f.message.contains("Not a valid engine address"), f.message)
            } catch { XCTFail("\(error)") }
        }
        XCTAssertEqual(world.requests, [])
    }

    func testATimeoutAndNoAnswerAreDifferentProbes() async throws {
        let world = FakeWorld()
        let client = world.runtime().client
        var found = await client.probe("/readyz")
        XCTAssertEqual(found, .noAnswer)

        world.timeOut("/readyz")
        found = await client.probe("/readyz", timeout: 2.5)
        XCTAssertEqual(found, .timedOut)
        do {
            _ = try await client.raw("/readyz", timeout: 3)
            XCTFail("expected a failure")
        } catch let f as TecopaFailure {
            XCTAssertEqual(f.kind, .engineUnreachable)
            XCTAssertEqual(f.message, "The engine on port 8848 did not answer within 3 seconds.")
            XCTAssertEqual(f.hint, "It may be busy with a render. Run `tecopa logs`.")
        }

        world.stopServing()
        world.serve("/readyz", 503, #"{"ready":false,"regions":[]}"#)
        found = await client.probe("/readyz")
        XCTAssertEqual(found, .reply(EngineClient.Reply(status: 503, json: .object([
            "ready": .bool(false), "regions": .array([])]))))
    }

    func testIsGateOffIsTrueOnlyForTheClosedGate() async {
        let world = FakeWorld()
        world.serve("/api/debug/jobs", 404, #"{"detail":"Not Found"}"#)
        world.serve("/api/debug/sessions/ab", 404, #"{"detail":"Unknown session"}"#)
        world.serve("/api/debug/caches", 500, "Internal Server Error")
        let client = world.runtime().client
        var seen: [Bool] = []
        for path in ["/jobs", "/sessions/ab", "/caches", "/engine"] {
            do {
                _ = try await client.debug(path)
                XCTFail("expected a failure")
            } catch let f as TecopaFailure {
                seen.append(EngineClient.isGateOff(f))
            } catch { XCTFail("\(error)") }
        }
        XCTAssertEqual(seen, [true, false, false, false])
    }
}
