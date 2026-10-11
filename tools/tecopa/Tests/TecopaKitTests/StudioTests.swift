import XCTest
@testable import TecopaKit

final class StudioTests: XCTestCase {
    /// The engine's answer for GET /api/debug/studio: two tabs and four errors,
    /// each list newest first. The second tab sent errors and no state yet.
    private let report = """
        {"tabs": [
           {"tab": "k3j9x0aa11", "received": 1791655445.25,
            "state": {"session": "ab12", "target": "print", "view": "crop", "region": "lassen_ca",
                      "output": "poster", "edition": 2, "has_spec": true, "proof_stale": false}},
           {"tab": "zz00zz00", "received": 1791655383, "state": null}],
         "errors": [
           {"tab": "k3j9x0aa11", "received": 1791655445.25, "kind": "toast",
            "message": "The crop is past the zoom cap.", "source": null, "line": null, "stack": null},
           {"tab": "zz00zz00", "received": 1791655383, "kind": "error",
            "message": "TypeError: x is undefined", "source": "http://127.0.0.1:8848/static/app.js",
            "line": 412, "stack": "TypeError: x is undefined\\n    at paint (app.js:412:9)\\n    at tick (app.js:90:3)"},
           {"tab": "k3j9x0aa11", "received": 1791655300.9, "kind": "rejection",
            "message": "ApiError: 503", "source": null, "line": null, "stack": "ApiError: 503"},
           {"tab": "k3j9x0aa11", "received": 1791655300.9, "kind": "error",
            "message": "ReferenceError: y", "source": "app.js", "line": null, "stack": null}]}
        """

    private func engine() -> FakeWorld {
        let world = FakeWorld()
        world.serve("/api/debug/studio", 200, report)
        return world
    }

    private func call(_ name: String, _ world: FakeWorld,
                      _ arguments: [String: JSONValue] = [:]) async -> (data: JSONValue?, failure: TecopaFailure?) {
        let (envelope, failure) = await Catalog.call(name, world.runtime(), arguments)
        return (envelope["data"], failure)
    }

    private var parsed: JSONValue { (try? JSONValue.parse(Data(report.utf8))) ?? .null }

    /// The message of each error in a result, in order.
    private func messages(_ data: JSONValue?) -> [String] {
        (data?["errors"]?.arrayValue ?? []).compactMap { $0["message"]?.stringValue }
    }

    // MARK: The two entries

    func testStudioStateReturnsTheTabsUnchanged() async {
        let world = engine()
        let (data, failure) = await call("studio_state", world)
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, ["GET /api/debug/studio"])
        XCTAssertNotNil(parsed["tabs"])
        XCTAssertEqual(data, .object(["tabs": parsed["tabs"] ?? .null]))
    }

    func testStudioErrorsReturnsTheErrorsUnchanged() async {
        let world = engine()
        let (data, failure) = await call("studio_errors", world)
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, ["GET /api/debug/studio"])
        XCTAssertNotNil(parsed["errors"])
        XCTAssertEqual(data, .object(["errors": parsed["errors"] ?? .null]))
        // the engine's order, newest first
        XCTAssertEqual(messages(data), ["The crop is past the zoom cap.", "TypeError: x is undefined",
                                        "ApiError: 503", "ReferenceError: y"])
    }

    func testBothEntriesAreReadOnly() {
        XCTAssertEqual(Catalog.named("studio_state")?.readOnly, true)
        XCTAssertEqual(Catalog.named("studio_errors")?.readOnly, true)
        XCTAssertEqual(Catalog.named("studio_state")?.parameters.map(\.name), [])
        XCTAssertEqual(Catalog.named("studio_errors")?.parameters.map(\.name), ["tab", "kind"])
    }

    // MARK: The filters

    func testTheTabFilterKeepsOnlyThatTabsErrors() async {
        let world = engine()
        var (data, failure) = await call("studio_errors", world, ["tab": .string("zz00zz00")])
        XCTAssertNil(failure)
        XCTAssertEqual(messages(data), ["TypeError: x is undefined"])

        (data, failure) = await call("studio_errors", world, ["tab": .string("k3j9x0aa11")])
        XCTAssertNil(failure)
        XCTAssertEqual(messages(data), ["The crop is past the zoom cap.", "ApiError: 503", "ReferenceError: y"])
        // the engine has no filter: the tool asks for the whole report each time
        XCTAssertEqual(world.calls, ["GET /api/debug/studio", "GET /api/debug/studio"])
    }

    func testTheKindFilterKeepsOnlyThatKind() async {
        let world = engine()
        let expected = [
            "error": ["TypeError: x is undefined", "ReferenceError: y"],
            "rejection": ["ApiError: 503"],
            "toast": ["The crop is past the zoom cap."],
        ]
        for (kind, kept) in expected {
            let (data, failure) = await call("studio_errors", world, ["kind": .string(kind)])
            XCTAssertNil(failure, kind)
            XCTAssertEqual(messages(data), kept, kind)
        }
    }

    func testTheTwoFiltersTogetherAndAFilterThatKeepsNothing() async {
        let world = engine()
        var (data, failure) = await call("studio_errors", world, [
            "tab": .string("k3j9x0aa11"), "kind": .string("error")])
        XCTAssertNil(failure)
        XCTAssertEqual(messages(data), ["ReferenceError: y"])

        // a tab that never reported is not a failure: it has no errors
        (data, failure) = await call("studio_errors", world, ["tab": .string("neverseen0")])
        XCTAssertNil(failure)
        XCTAssertEqual(data, .object(["errors": .array([])]))

        (data, failure) = await call("studio_errors", world, [
            "tab": .string("zz00zz00"), "kind": .string("toast")])
        XCTAssertNil(failure)
        XCTAssertEqual(data, .object(["errors": .array([])]))
    }

    // MARK: The arguments

    func testATabThatIsNotATabIdIsAUsageFailureWithNoRequest() async {
        let world = engine()
        let bad = ["", "short12", String(repeating: "a", count: 33), "K3J9X0AA11", "k3j9 x0aa11",
                   "../engine", "k3j9x0aa-1", "ｋ３ｊ９ｘ０ａａ", "k3j9x0aa\n"]
        for tab in bad {
            let (data, failure) = await call("studio_errors", world, ["tab": .string(tab)])
            XCTAssertNil(data, tab)
            XCTAssertEqual(failure?.kind, .usage, tab)
            XCTAssertTrue(failure?.message.contains("tab") ?? false, tab)
        }
        XCTAssertEqual(world.calls, [])

        // the two ends of the range are tab ids
        for tab in [String(repeating: "a", count: 8), String(repeating: "9", count: 32)] {
            let (_, failure) = await call("studio_errors", world, ["tab": .string(tab)])
            XCTAssertNil(failure, tab)
        }
    }

    func testAKindThatIsNotOneOfTheThreeIsAUsageFailureWithNoRequest() async {
        let world = engine()
        for kind in ["", "warning", "Error", "errors", "error ", "toast,error"] {
            let (data, failure) = await call("studio_errors", world, ["kind": .string(kind)])
            XCTAssertNil(data, kind)
            XCTAssertEqual(failure?.kind, .usage, kind)
            XCTAssertTrue(failure?.message.contains("error, rejection, toast") ?? false, kind)
        }
        XCTAssertEqual(world.calls, [])

        // `studio state` takes no argument
        let (_, failure) = await call("studio_state", world, ["tab": .string("k3j9x0aa11")])
        XCTAssertEqual(failure?.message, "Unknown argument for studio_state: tab")
        XCTAssertEqual(world.calls, [])
    }

    // MARK: What the engine says

    func testAnEmptyBufferIsTwoEmptyLists() async {
        let world = FakeWorld()
        world.serve("/api/debug/studio", 200, #"{"tabs": [], "errors": []}"#)
        let (tabs, stateFailure) = await call("studio_state", world)
        XCTAssertNil(stateFailure)
        XCTAssertEqual(tabs, .object(["tabs": .array([])]))
        XCTAssertEqual(Catalog.named("studio_state")?.text?(tabs ?? .null), "No studio tab has reported.")

        let (errors, errorsFailure) = await call("studio_errors", world)
        XCTAssertNil(errorsFailure)
        XCTAssertEqual(errors, .object(["errors": .array([])]))
        XCTAssertEqual(Catalog.named("studio_errors")?.text?(errors ?? .null), "No errors reported.")
    }

    func testWithTheGateOffEachEntryGivesTheGateOffFailure() async {
        let world = FakeWorld()
        world.serve("/readyz", 200, FakeWorld.readyBody)
        world.serve("/api/debug/studio", 404, #"{"detail":"Not Found"}"#)
        for name in ["studio_state", "studio_errors"] {
            let (data, failure) = await call(name, world)
            XCTAssertNil(data, name)
            XCTAssertTrue(failure.map(EngineClient.isGateOff) ?? false, name)
            XCTAssertEqual(failure?.message, "The debug routes are off on port 8848.", name)
            XCTAssertTrue(failure?.hint?.contains("TECOPA_DEBUG=1") ?? false, name)
        }
    }

    func testWithNoEngineEachEntryIsUnreachable() async {
        for name in ["studio_state", "studio_errors"] {
            let (_, failure) = await call(name, FakeWorld())
            XCTAssertEqual(failure?.kind, .engineUnreachable, name)
        }
    }

    func testAnAnswerWithoutTheListIsAnEnvironmentFailure() async {
        // an engine that has the gate and not this route's shape is not an empty buffer
        let world = FakeWorld()
        for body in [#"{"tabs": [], "errors": {}}"#, #"{"tabs": "none"}"#, "[]"] {
            world.serve("/api/debug/studio", 200, body)
            let (data, failure) = await call("studio_errors", world)
            XCTAssertNil(data, body)
            XCTAssertEqual(failure?.kind, .environment, body)
        }
        world.serve("/api/debug/studio", 200, #"{"errors": []}"#)
        let (data, failure) = await call("studio_state", world)
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .environment)
    }

    // MARK: The text

    func testTheTextOfStudioStateIsOneLineForEachTab() async {
        let (data, _) = await call("studio_state", engine())
        // a tab whose state is null has a line too, and it does not stop the printer
        XCTAssertEqual(Catalog.named("studio_state")?.text?(data ?? .null), """
            k3j9x0aa11  2026-10-10T18:04:05Z  target=print  view=crop  session=ab12  region=lassen_ca  \
            has_spec=true  proof_stale=false
            zz00zz00  2026-10-10T18:03:03Z  no state
            """)
    }

    func testAStateValueThatIsNullOrMissingPrintsAsADash() {
        let tabs: JSONValue = .object(["tabs": .array([
            // a page with no session yet: the hook sends null for what it does not have
            .object(["tab": .string("k3j9x0aa11"), "received": .int(1791655383), "state": .object([
                "session": .null, "target": .string("print"), "view": .string("setup"),
                "region": .null, "has_spec": .bool(false), "proof_stale": .null])]),
            .object(["tab": .string("zz00zz00"), "received": .null, "state": .object([:])]),
            // a row with no state key at all, and one that is not an object
            .object(["tab": .string("aa11aa11"), "received": .double(1791655300.9)]),
            .string("not a row"),
        ])])
        XCTAssertEqual(Catalog.named("studio_state")?.text?(tabs), """
            k3j9x0aa11  2026-10-10T18:03:03Z  target=print  view=setup  session=-  region=-  \
            has_spec=false  proof_stale=-
            zz00zz00  -  target=-  view=-  session=-  region=-  has_spec=-  proof_stale=-
            aa11aa11  2026-10-10T18:01:40Z  no state
            -  -  no state
            """)
    }

    func testTheTextOfStudioErrorsIsAHeaderTheMessageTheSourceAndTheStack() async {
        let (data, _) = await call("studio_errors", engine())
        XCTAssertEqual(Catalog.named("studio_errors")?.text?(data ?? .null), """
            2026-10-10T18:04:05Z  k3j9x0aa11  toast
            The crop is past the zoom cap.

            2026-10-10T18:03:03Z  zz00zz00  error
            TypeError: x is undefined
            http://127.0.0.1:8848/static/app.js:412
                TypeError: x is undefined
                    at paint (app.js:412:9)
                    at tick (app.js:90:3)

            2026-10-10T18:01:40Z  k3j9x0aa11  rejection
            ApiError: 503
                ApiError: 503

            2026-10-10T18:01:40Z  k3j9x0aa11  error
            ReferenceError: y
            app.js
            """)
    }

    func testTheTextOfAnErrorAddsNothingToTheMessage() {
        // the engine has removed the control characters: the tool prints what is left
        let message = "  two lines\n\tand a tab, a quote \" and a backslash \\  "
        let errors: JSONValue = .object(["errors": .array([.object([
            "tab": .string("k3j9x0aa11"), "received": .int(1791655383), "kind": .string("toast"),
            "message": .string(message), "source": .null, "line": .int(7), "stack": .null])])])
        // a line with no source names no place
        XCTAssertEqual(Catalog.named("studio_errors")?.text?(errors),
                       "2026-10-10T18:03:03Z  k3j9x0aa11  toast\n" + message)
    }
}
