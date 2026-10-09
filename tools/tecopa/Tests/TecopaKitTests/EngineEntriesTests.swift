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

    func testEngineStatusRefusesAPortOutOfRange() async {
        // without the check this was {"running": false}: a stopped engine on port 0
        let world = FakeWorld()
        for port in [0, 65536, -1] {
            let (env, failure) = await Catalog.call("engine_status", world.runtime(port: port), [:])
            XCTAssertEqual(failure?.kind, .usage, "\(port)")
            XCTAssertTrue(failure?.message.contains("Not a valid engine address") ?? false)
            XCTAssertNil(env["data"])
        }
        XCTAssertEqual(world.requests, [])
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
        XCTAssertNil(env["data"]?["debug_error"])

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

    func testATimeoutIsNotReportedAsAStoppedEngine() async {
        // an engine that is busy with a render listens and does not answer in time
        let world = FakeWorld()
        world.timeOut("/readyz")
        let (env, failure) = await Catalog.call("engine_status", world.runtime(), [:])
        XCTAssertEqual(failure?.kind, .engineUnreachable)
        XCTAssertTrue(failure?.message.contains("did not answer within") ?? false)
        XCTAssertEqual(env["ok"], .bool(false))
        XCTAssertNil(env["data"]?["running"])
    }

    func testEngineStatusReportsADebugErrorThatIsNotTheGate() async {
        let world = FakeWorld()
        world.serve("/readyz", 200, FakeWorld.readyBody)
        world.serve("/api/debug/engine", 500, "Internal Server Error")
        let (env, failure) = await Catalog.call("engine_status", world.runtime(), [:])
        XCTAssertNil(failure)
        XCTAssertEqual(env["data"]?["running"], .bool(true))
        XCTAssertEqual(env["data"]?["debug"], .null)
        XCTAssertEqual(env["data"]?["debug_error"]?.stringValue,
                       "The engine answered 500 for /api/debug/engine.")
        XCTAssertNil(env["data"]?["engine"])
    }

    func testSessionsPassesTheIdAndTheFullQuery() async {
        let world = FakeWorld()
        world.serve("/api/debug/sessions/ab12", 200, #"{"sid":"ab12","tracks":2}"#)
        world.serve("/api/debug/sessions/ab12?full=1", 200, #"{"sid":"ab12","geometry":[[0,1]]}"#)

        var (env, failure) = await Catalog.call("sessions", world.runtime(), ["sid": .string("ab12")])
        XCTAssertNil(failure)
        XCTAssertEqual(env["data"]?["tracks"]?.intValue, 2)
        XCTAssertNil(env["data"]?["geometry"])

        (env, failure) = await Catalog.call("sessions", world.runtime(),
                                            ["sid": .string("ab12"), "full": .bool(true)])
        XCTAssertNil(failure)
        XCTAssertNotNil(env["data"]?["geometry"])
        XCTAssertNil(env["data"]?["tracks"])

        let asked = world.requests.map(\.absoluteString)
        XCTAssertEqual(asked.count, 2)
        XCTAssertTrue(asked.first?.hasSuffix("/api/debug/sessions/ab12") ?? false)
        XCTAssertTrue(asked.last?.hasSuffix("/api/debug/sessions/ab12?full=1") ?? false)
    }

    func testAFullwidthIdIsRefused() async {
        // Character.isHexDigit is true for the fullwidth letters, and they are not ASCII
        let world = FakeWorld()
        let (_, failure) = await Catalog.call("sessions", world.runtime(), ["sid": .string("ａｂ")])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertEqual(world.requests, [])
    }

    func testFullWithoutASessionIdIsRefused() async {
        let world = FakeWorld()
        world.serve("/api/debug/sessions", 200, "[]")
        let (_, failure) = await Catalog.call("sessions", world.runtime(), ["full": .bool(true)])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertEqual(failure?.message, "full needs a session id.")
        XCTAssertEqual(world.requests, [])
    }

    func testRegionsJoinsPlatesWithReadinessAndSurvivesA503Readyz() async {
        let world = FakeWorld()
        world.serve("/api/regions", 200, #"[{"id":"lassen_ca"},{"id":"rifle_aspen"}]"#)
        world.serve("/readyz", 503,
                    #"{"ready":false,"regions":[{"id":"lassen_ca","ready":false},{"id":"rifle_aspen","ready":true}]}"#)
        let (env, failure) = await Catalog.call("regions", world.runtime(), [:])
        XCTAssertNil(failure)
        XCTAssertEqual(env["data"]?["regions"]?.arrayValue?.count, 2)
        XCTAssertEqual(env["data"]?["regions"]?.arrayValue?.first?["id"]?.stringValue, "lassen_ca")
        XCTAssertEqual(env["data"]?["ready"], .bool(false))
        XCTAssertEqual(env["data"]?["readiness"]?.arrayValue?.count, 2)
        XCTAssertEqual(env["data"]?["readiness"]?.arrayValue?.first?["ready"], .bool(false))
    }

    func testAnUnknownArgumentIsRefused() async {
        // an MCP caller that writes "session" for "sid" must not get every session
        let world = FakeWorld()
        world.serve("/api/debug/sessions", 200, "[]")
        var (env, failure) = await Catalog.call("sessions", world.runtime(), ["session": .string("ab12")])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertEqual(failure?.message, "Unknown argument for sessions: session")
        XCTAssertTrue(failure?.hint?.contains("sid, full") ?? false)
        XCTAssertEqual(env["ok"], .bool(false))
        XCTAssertEqual(world.requests, [])

        (env, failure) = await Catalog.call("logs", world.runtime(), ["line": .int(5)])
        XCTAssertEqual(failure?.message, "Unknown argument for logs: line")

        (env, failure) = await Catalog.call("jobs", world.runtime(), ["sid": .string("ab12")])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertEqual(failure?.hint, "This command takes no arguments.")
        XCTAssertEqual(world.requests, [])
    }

    func testAWrongArgumentKindIsRefused() async {
        let world = FakeWorld()
        world.serve("/api/debug/sessions", 200, "[]")
        let wrong: [(String, String, JSONValue, String)] = [
            ("logs", "lines", .string("ten"), "lines must be an integer."),
            ("logs", "lines", .double(1.5), "lines must be an integer."),
            ("logs", "grep", .int(5), "grep must be a string."),
            ("sessions", "sid", .int(12), "sid must be a string."),
            ("sessions", "full", .string("yes"), "full must be a boolean."),
            ("regions_verify", "regions", .string("lassen_ca"), "regions must be a list of strings."),
            ("regions_verify", "regions", .array([.string("lassen_ca"), .int(1)]),
             "regions must be a list of strings."),
        ]
        for (name, key, value, message) in wrong {
            let (_, failure) = await Catalog.call(name, world.runtime(), [key: value])
            XCTAssertEqual(failure?.kind, .usage, message)
            XCTAssertEqual(failure?.message, message)
        }
        XCTAssertEqual(world.requests, [])
        XCTAssertEqual(world.commands, [])

        // the kinds each command of the CLI sends, and a whole number written as a double
        let right: [(String, [String: JSONValue])] = [
            ("logs", ["lines": .int(5), "grep": .string("x"), "since": .string("2h")]),
            ("logs", ["lines": .double(5)]),
            ("sessions", ["sid": .string("ab12"), "full": .bool(true)]),
            ("regions_verify", ["regions": .array([.string("lassen_ca")])]),
        ]
        for (name, arguments) in right {
            let (_, failure) = await Catalog.call(name, world.runtime(), arguments)
            XCTAssertNotEqual(failure?.kind, .usage, name)
        }
    }

    func testANullArgumentIsDropped() async {
        let world = FakeWorld()
        world.serve("/api/debug/sessions", 200, #"[{"sid":"ab12"}]"#)
        var (env, failure) = await Catalog.call("sessions", world.runtime(),
                                                ["sid": .null, "full": .null])
        XCTAssertNil(failure)
        XCTAssertEqual(env["data"]?.arrayValue?.count, 1)

        (env, failure) = await Catalog.call("logs", world.runtime(home: "/no/such/home"),
                                            ["lines": .null, "grep": .null, "since": .null])
        XCTAssertNil(failure)
        XCTAssertEqual(env["data"]?["exists"], .bool(false))
    }
}
