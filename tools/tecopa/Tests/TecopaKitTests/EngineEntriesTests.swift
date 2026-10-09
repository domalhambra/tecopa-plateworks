import XCTest
@testable import TecopaKit

final class EngineEntriesTests: XCTestCase {
    func testCallWrapsSuccessInTheEnvelope() async {
        let world = FakeWorld()
        world.serve("/api/debug/caches", 200, #"{"base":{"entries":0}}"#)
        let (env, failure) = await Catalog.call("caches", world.runtime(), [:])
        XCTAssertNil(failure)
        XCTAssertEqual(env["ok"], .bool(true))
        XCTAssertEqual(env["data"]?["base"]?["entries"]?.intValue, 0)
    }

    func testCallReturnsTheFailureEnvelopeAndNeverThrows() async {
        let (env, failure) = await Catalog.call("jobs", FakeWorld().runtime(), [:])
        XCTAssertEqual(failure?.kind, .engineUnreachable)
        XCTAssertEqual(env["ok"], .bool(false))
        XCTAssertEqual(env["error"]?["kind"]?.stringValue, "engine_unreachable")
    }

    func testAnUnknownNameIsAUsageFailure() async {
        let (_, failure) = await Catalog.call("no_such", FakeWorld().runtime(), [:])
        XCTAssertEqual(failure?.kind, .usage)
    }

    func testEngineStatusWithNoEngineIsData() async {
        let (env, failure) = await Catalog.call("engine_status", FakeWorld().runtime(), [:])
        XCTAssertNil(failure)
        XCTAssertEqual(env["data"]?["running"], .bool(false))
        XCTAssertEqual(env["data"]?["port"]?.intValue, 8848)
    }

    func testEngineStatusRefusesAForeignProgramOnThePort() async {
        let world = FakeWorld()
        world.serve("/readyz", 200, "<html>hello</html>")
        let (_, failure) = await Catalog.call("engine_status", world.runtime(), [:])
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertTrue(failure?.message.contains("not Tecopa Plateworks") ?? false)
    }

    func testEngineStatusReportsTheGate() async {
        let world = FakeWorld()
        world.serve("/readyz", 200, FakeWorld.readyBody)
        world.serve("/api/debug/engine", 404, #"{"detail":"Not Found"}"#)
        var (env, _) = await Catalog.call("engine_status", world.runtime(), [:])
        XCTAssertEqual(env["data"]?["running"], .bool(true))
        XCTAssertEqual(env["data"]?["debug"], .bool(false))

        world.serve("/api/debug/engine", 200, #"{"engine":"tecopa-plateworks","pid":7}"#)
        (env, _) = await Catalog.call("engine_status", world.runtime(), [:])
        XCTAssertEqual(env["data"]?["debug"], .bool(true))
        XCTAssertEqual(env["data"]?["engine"]?["pid"]?.intValue, 7)
    }

    func testSessionsRefusesAnIdThatIsNotHexadecimal() async {
        // the id goes into a URL path; a session id is uuid4().hex and nothing else
        let (_, failure) = await Catalog.call("sessions", FakeWorld().runtime(),
                                              ["sid": .string("../engine")])
        XCTAssertEqual(failure?.kind, .usage)
    }
}
