import XCTest
@testable import TecopaKit

/// The `order` entries on the fake machine: Prepare and the size preview as
/// tracked runs, and the order's own state file read back whole.
final class OrdersTests: XCTestCase {
    private let runs = "/home/Library/Application Support/TecopaPlateworks/runs"
    /// The id of a start at the fake's default clock and digits.
    private let run = "20261010-185515-a1b2c3"
    private let order = "/Users/dom/Tecopa Orders/2026-10-001-smith"

    private func call(_ name: String, _ world: FakeWorld,
                      _ arguments: [String: JSONValue] = [:]) async -> (data: JSONValue?, failure: TecopaFailure?) {
        let (envelope, failure) = await Catalog.call(name, world.runtime(), arguments)
        return (envelope["data"], failure)
    }

    /// Nothing ran, nothing started, nothing was written and the engine was not asked.
    private func assertNothingHappened(_ world: FakeWorld, _ message: String = "",
                                       file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(world.commands, [], message, file: file, line: line)
        XCTAssertEqual(world.detached, [], message, file: file, line: line)
        XCTAssertEqual(world.written, [], message, file: file, line: line)
        XCTAssertEqual(world.madeFolders, [], message, file: file, line: line)
        XCTAssertEqual(world.calls, [], message, file: file, line: line)
    }

    /// A state file as Prepare writes it, with keys that the tool does not know.
    private let state = """
        {
          "inputs_hash": "9f8e7d6c",
          "epsg": 32610,
          "print_in": [11, 17],
          "frame": [612000.0, 4470000.5, 640000.0, 4513272.7],
          "frame_from_manual": null,
          "fill": 0.612,
          "need_m": 6.482,
          "plate": {"id": "o_2026_10_001_smith", "root": "/Users/dom/Tecopa Orders/2026-10-001-smith/work/plate",
                    "kind": "built", "grid_m": 10, "layer_m": null, "upsample": 1.0,
                    "hole_fill": {"filled_share": 0.021, "layer_m": 30}, "nan_share": 0.0},
          "warnings": ["Upsampling 1.54x", "The frame was widened."],
          "landcover_rebuilds": 0,
          "manual": {"frame": [1, 2, 3, 4], "note": "a key of the studio"},
          "a_key_of_next_year": {"deep": [true, false, null, {"deeper": "é"}]}
        }
        """

    private let report = """
        Order: Smith, Lassen 2026
        Print: 11 x 17 in
        Plate: o_2026_10_001_smith (built), 10 m grid
        Warnings:
        - Upsampling 1.54x

        """

    // MARK: The script table

    func testTheOrderScriptRunsInTheAppVenv() {
        // the script starts its own .venv-prep subprocesses: the tool does not
        XCTAssertEqual(ScriptRunner.table["scripts/order.py"], .script(.app))
    }

    // MARK: order new

    private let python = "/repo/.venv/bin/python"

    func testOrderNewRunsTheScriptInTheCallWithTheNumber() async {
        let world = FakeWorld()
        let said = "Order: TP-26-001, \"Smith home ground\"\nCopied 2 files:\n- Tracks (2): a.gpx, b.gpx\n"
        world.result(for: "python", ProcessResult(exitCode: 0, stdout: said, stderr: ""))
        var runtime = world.runtime()
        runtime.environment = ["TECOPA_INTAKE_DIR": "/Users/dom/Dropbox/Apps/Plateworks Lab/Tecopa"]
        let (envelope, failure) = await Catalog.call("order_new", runtime, ["number": .string("TP-26-001")])
        XCTAssertNil(failure)
        XCTAssertEqual(envelope["data"], .object(["output": .string(said.trimmingCharacters(in: .newlines))]))
        // the number is one argument, and the script runs in the app venv, in the call
        XCTAssertEqual(world.commands, [[python, "scripts/order.py", "new", "TP-26-001"]])
        XCTAssertEqual(world.workingDirectories, ["/repo"])
        // the script reads TECOPA_INTAKE_DIR: the tool's own environment goes through
        XCTAssertEqual(world.environments.first??["TECOPA_INTAKE_DIR"], "/Users/dom/Dropbox/Apps/Plateworks Lab/Tecopa")
        XCTAssertEqual(world.detached, [])
        XCTAssertEqual(world.written, [])
        XCTAssertEqual(Catalog.named("order_new")?.text?(envelope["data"] ?? .null),
                       said.trimmingCharacters(in: .newlines))
    }

    func testOrderNewTakesAnOrderNumberAndNothingElse() async {
        let world = FakeWorld()
        let refused: [(String?, String)] = [
            (nil, "number is required: an order number like TP-26-001."),
            ("", "number is required: an order number like TP-26-001."),
            ("26-001", "Not an order number: 26-001. It is like TP-26-001."),
            ("tp-26-001", "Not an order number: tp-26-001. It is like TP-26-001."),
            ("TP-26-1", "Not an order number: TP-26-1. It is like TP-26-001."),
            ("TP-26-001234", "Not an order number: TP-26-001234. It is like TP-26-001."),
            ("TP-26-001 ", "Not an order number: TP-26-001 . It is like TP-26-001."),
            ("--help", "Not an order number: --help. It is like TP-26-001."),
            ("TP-26-001/../x", "Not an order number: TP-26-001/../x. It is like TP-26-001."),
            ("TP-٢٦-001", "Not an order number: TP-٢٦-001. It is like TP-26-001."),
            ("/Users/dom/Tecopa Orders/TP-26-001-smith",
             "Not an order number: /Users/dom/Tecopa Orders/TP-26-001-smith. It is like TP-26-001."),
        ]
        for (number, said) in refused {
            let (data, failure) = await call("order_new", world, number.map { ["number": .string($0)] } ?? [:])
            XCTAssertNil(data, said)
            XCTAssertEqual(failure, TecopaFailure(.usage, said))
        }
        // the entry has no folder argument and no flag that moves or replaces a file
        for name in ["folder", "replace", "move"] {
            let (_, failure) = await call("order_new", world, ["number": .string("TP-26-001"), name: .bool(true)])
            XCTAssertTrue(failure?.message.hasPrefix("Unknown argument for order_new") ?? false, name)
        }
        assertNothingHappened(world)
        XCTAssertTrue(Orders.isOrderNumber("TP-26-001") && Orders.isOrderNumber("TP-27-12345"))
    }

    func testOrderNewExit1IsRefusedWithTheScriptsOwnWords() async {
        let world = FakeWorld()
        let said = "new stopped: cloud.gpx is not on this Mac yet: Dropbox lists 5,000 bytes and has not downloaded them."
        world.result(for: "python", ProcessResult(exitCode: 1, stdout: "", stderr: said + "\n"))
        let (data, failure) = await call("order_new", world, ["number": .string("TP-26-001")])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(failure?.message, "order.py new refused: " + said)
        // a crash is not a refusal
        world.result(for: "python", ProcessResult(
            exitCode: 1, stdout: "", stderr: "Traceback (most recent call last):\n  File x\nKeyError: 'title'\n"))
        let (_, crashed) = await call("order_new", world, ["number": .string("TP-26-001")])
        XCTAssertEqual(crashed?.kind, .environment)
        XCTAssertEqual(crashed?.message, "order.py new crashed: KeyError: 'title'")
    }

    // MARK: order prepare

    func testOrderPrepareStartsTheScriptInTheAppVenvAsATrackedRun() async throws {
        let world = FakeWorld()
        world.folder(order)
        var runtime = world.runtime()
        runtime.environment = ["TECOPA_ORDERS_DIR": "/Users/dom/Tecopa Orders", "PATH": "/usr/bin:/bin"]
        let (envelope, failure) = await Catalog.call("order_prepare", runtime, ["folder": .string(order)])
        XCTAssertNil(failure)
        // the folder is one argument, with its space
        XCTAssertEqual(world.detached.map { Array($0.arguments.dropFirst(5)) },
                       [["/repo/.venv/bin/python", "scripts/order.py", "prepare", order]])
        XCTAssertEqual(world.detached.first?.executable, "/bin/sh")
        XCTAssertEqual(world.detached.first?.cwd, "/repo")
        // the script reads TECOPA_ORDERS_DIR: the tool's own environment goes through
        XCTAssertEqual(world.detached.first?.environment, [
            "TECOPA_ORDERS_DIR": "/Users/dom/Tecopa Orders", "PATH": "/usr/bin:/bin", "PYTHONUNBUFFERED": "1"])
        let written = try JSONValue.parse(
            try XCTUnwrap(world.written.first { $0.path.hasSuffix(".json") }).data)
        XCTAssertEqual(written["command"]?.stringValue, "order_prepare")
        XCTAssertEqual(written["cwd"]?.stringValue, "/repo")
        XCTAssertEqual(written["failure_text"], .null)
        XCTAssertEqual(written["argv"], .array([
            .string("/repo/.venv/bin/python"), .string("scripts/order.py"), .string("prepare"), .string(order)]))
        XCTAssertEqual(envelope["data"], .object([
            "run": .string(run), "pid": .int(4001), "log": .string("\(runs)/\(run).log"),
            "hint": .string("Run `tecopa runs show \(run)`.")]))
        // the call returns at once: the tool waits for nothing and runs nothing in the call
        XCTAssertEqual(world.commands, [])
        XCTAssertEqual(world.slept, [])
        // and the two files it writes are the run's empty log and the run's record,
        // never a file under the order
        XCTAssertEqual(world.written.map(\.path), ["\(runs)/\(run).log", "\(runs)/\(run).json"])
    }

    func testOrderPrepareNeedsAnAbsolutePathToAFolderThatExists() async {
        let world = FakeWorld()
        world.folder(order)
        world.existingFile("/Users/dom/Tecopa Orders/order.toml")
        let refused: [(String?, String)] = [
            (nil, "folder is required: the path of an order folder."),
            ("", "folder is required: the path of an order folder."),
            // a relative folder is the MCP client's, not the caller's
            ("2026-10-001-smith", "folder must be an absolute path: 2026-10-001-smith"),
            ("~/Tecopa Orders/2026-10-001-smith", "folder must be an absolute path: ~/Tecopa Orders/2026-10-001-smith"),
            ("--out", "folder must be an absolute path: --out"),
            ("/Users/dom/Tecopa Orders/none", "The folder /Users/dom/Tecopa Orders/none does not exist."),
            // a file is not a folder
            ("/Users/dom/Tecopa Orders/order.toml", "/Users/dom/Tecopa Orders/order.toml is not a folder."),
        ]
        for name in ["order_prepare", "order_preview", "order_status"] {
            for (folder, said) in refused {
                let (data, failure) = await call(name, world, folder.map { ["folder": .string($0)] } ?? [:])
                XCTAssertNil(data, "\(name) \(said)")
                XCTAssertEqual(failure, TecopaFailure(.usage, said), name)
            }
        }
        assertNothingHappened(world)
    }

    func testOrderPrepareLeavesAFolderInsideTheRepoToTheScript() async {
        // the script refuses it, with exit 1 and its reason in the run's log
        let world = FakeWorld()
        world.folder("/repo/orders/2026-10-001-smith")
        let (_, failure) = await call("order_prepare", world, ["folder": .string("/repo/orders/2026-10-001-smith")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.detached.first?.arguments.last, "/repo/orders/2026-10-001-smith")
    }

    // MARK: order preview

    func testOrderPreviewStartsTheScriptAsATrackedRun() async throws {
        let world = FakeWorld()
        world.folder(order)
        let runtime = world.runtime()
        let (envelope, failure) = await Catalog.call("order_preview", runtime, ["folder": .string(order)])
        XCTAssertNil(failure)
        // the same script as Prepare, with its other command, and the folder as one argument
        XCTAssertEqual(world.detached.map { Array($0.arguments.dropFirst(5)) },
                       [["/repo/.venv/bin/python", "scripts/order.py", "preview", order]])
        XCTAssertEqual(world.detached.first?.cwd, "/repo")
        let written = try JSONValue.parse(
            try XCTUnwrap(world.written.first { $0.path.hasSuffix(".json") }).data)
        XCTAssertEqual(written["command"]?.stringValue, "order_preview")
        XCTAssertEqual(written["failure_text"], .null)
        XCTAssertEqual(written["argv"], .array([
            .string("/repo/.venv/bin/python"), .string("scripts/order.py"), .string("preview"), .string(order)]))
        XCTAssertEqual(envelope["data"], .object([
            "run": .string(run), "pid": .int(4001), "log": .string("\(runs)/\(run).log"),
            "hint": .string("Run `tecopa runs show \(run)`.")]))
        // the call returns at once, and it writes only the run's own two files
        XCTAssertEqual(world.commands, [])
        XCTAssertEqual(world.slept, [])
        XCTAssertEqual(world.calls, [])
        XCTAssertEqual(world.written.map(\.path), ["\(runs)/\(run).log", "\(runs)/\(run).json"])
    }

    // MARK: order status

    func testOrderStatusReturnsEveryKeyOfTheStateAndTheReport() async throws {
        let world = FakeWorld()
        world.folder(order)
        world.file(order + "/work/state.json", state)
        world.file(order + "/work/report.txt", report)
        let (data, failure) = await call("order_status", world, ["folder": .string(order)])
        XCTAssertNil(failure)
        let whole = try JSONValue.parse(Data(state.utf8))
        XCTAssertEqual(data, .object(["prepared": .bool(true), "state": whole, "report": .string(report)]))
        // nothing is left out: the keys the tool does not know, a null and a nested value
        guard case .object(let keys)? = data?["state"] else { return XCTFail("no state object") }
        XCTAssertEqual(Set(keys.keys), [
            "inputs_hash", "epsg", "print_in", "frame", "frame_from_manual", "fill", "need_m", "plate",
            "warnings", "landcover_rebuilds", "manual", "a_key_of_next_year"])
        XCTAssertEqual(data?["state"]?["frame_from_manual"], .null)
        XCTAssertEqual(data?["state"]?["a_key_of_next_year"]?["deep"]?.arrayValue?.last?["deeper"]?.stringValue, "é")
        XCTAssertEqual(data?["state"]?["manual"]?["note"]?.stringValue, "a key of the studio")
        XCTAssertEqual(data?["state"]?["plate"]?["hole_fill"]?["layer_m"]?.intValue, 30)
        // it reads two files and does nothing more
        assertNothingHappened(world)
    }

    func testOrderStatusWithNoReportHasANullReport() async {
        let world = FakeWorld()
        world.folder(order)
        world.file(order + "/work/state.json", #"{"manual": {"frame": [1, 2, 3, 4]}}"#)
        let (data, failure) = await call("order_status", world, ["folder": .string(order)])
        XCTAssertNil(failure)
        XCTAssertEqual(data, .object([
            "prepared": .bool(true), "report": .null,
            "state": .object(["manual": .object(["frame": .array([.int(1), .int(2), .int(3), .int(4)])])]),
        ]))
    }

    func testOrderStatusOfAnOrderWithNoStateFileIsNotPrepared() async {
        let world = FakeWorld()
        world.folder(order)
        world.folder(order + "/in")
        world.existingFile(order + "/order.toml")
        var (data, failure) = await call("order_status", world, ["folder": .string(order)])
        XCTAssertNil(failure)
        XCTAssertEqual(data, .object(["prepared": .bool(false)]))
        // a report with no state is not a prepared order, and the tool does not show it
        world.file(order + "/work/report.txt", report)
        (data, failure) = await call("order_status", world, ["folder": .string(order)])
        XCTAssertNil(failure)
        XCTAssertEqual(data, .object(["prepared": .bool(false)]))
        assertNothingHappened(world)
    }

    func testOrderStatusRefusesAStateFileThatIsNotAJSONObject() async {
        let path = order + "/work/state.json"
        for text in ["", "not json", #"{"plate": {"id": "#, "[]", "7", "null", #""state""#, "{} {}"] {
            let world = FakeWorld()
            world.folder(order)
            world.file(path, text)
            world.file(order + "/work/report.txt", report)
            let (data, failure) = await call("order_status", world, ["folder": .string(order)])
            XCTAssertNil(data, text)
            XCTAssertEqual(failure?.kind, .refused, text)
            XCTAssertEqual(failure?.message, "The file \(path) is not a JSON object.", text)
            assertNothingHappened(world, text)
        }
        // a file that is there and gives no bytes is not "not prepared"
        let world = FakeWorld()
        world.folder(order)
        world.existingFile(path)
        let (data, failure) = await call("order_status", world, ["folder": .string(order)])
        XCTAssertNil(data)
        XCTAssertEqual(failure, TecopaFailure(.refused, "The file \(path) cannot be read."))
    }

    // MARK: The catalog

    func testOrderStatusIsReadOnlyAndOrderPrepareIsNot() {
        XCTAssertEqual(Catalog.all.map(\.name).filter { $0.hasPrefix("order_") },
                       ["order_new", "order_prepare", "order_preview", "order_status"])
        XCTAssertEqual(Catalog.named("order_new")?.readOnly, false)
        XCTAssertEqual((Catalog.named("order_new")?.parameters ?? []).map { "\($0.name):\($0.kind.rawValue)" },
                       ["number:string"])
        XCTAssertEqual(Catalog.named("order_prepare")?.readOnly, false)
        XCTAssertEqual(Catalog.named("order_preview")?.readOnly, false)
        XCTAssertEqual(Catalog.named("order_status")?.readOnly, true)
        for name in ["order_prepare", "order_preview", "order_status"] {
            XCTAssertEqual((Catalog.named(name)?.parameters ?? []).map { "\($0.name):\($0.kind.rawValue)" },
                           ["folder:string"], name)
        }
    }

    // MARK: The text

    func testTheTextOfOrderStatusIsTheReportOrAShortSummary() throws {
        let text = try XCTUnwrap(Catalog.named("order_status")?.text)
        let whole = try JSONValue.parse(Data(state.utf8))
        // the report, as the script wrote it
        XCTAssertEqual(text(.object(["prepared": .bool(true), "state": whole, "report": .string(report)])),
                       report.trimmingCharacters(in: .newlines))
        // without one: the plate and the number of warnings, from the state
        XCTAssertEqual(text(.object(["prepared": .bool(true), "state": whole, "report": .null])), """
            Prepared. The order has no work/report.txt.
            Plate: o_2026_10_001_smith (built)
            Warnings: 2
            """)
        XCTAssertEqual(text(.object(["prepared": .bool(true), "state": whole, "report": .string("")])), """
            Prepared. The order has no work/report.txt.
            Plate: o_2026_10_001_smith (built)
            Warnings: 2
            """)
        // a state that holds only the studio's key has neither line
        XCTAssertEqual(text(.object(["prepared": .bool(true), "state": .object(["manual": .object([:])]),
                                     "report": .null])),
                       "Prepared. The order has no work/report.txt.")
        XCTAssertEqual(text(.object(["prepared": .bool(false)])),
                       "Not prepared: the order has no work/state.json. Run `tecopa order prepare`.")
    }

    func testTheTextOfATrackedOrderCommandNamesTheRunAndTheNextCommand() {
        let data: JSONValue = .object([
            "run": .string(run), "pid": .int(4001), "log": .string("\(runs)/\(run).log"),
            "hint": .string("Run `tecopa runs show \(run)`.")])
        for name in ["order_prepare", "order_preview"] {
            XCTAssertEqual(Catalog.named(name)?.text?(data), """
                run: \(run)
                pid: 4001
                log: \(runs)/\(run).log
                Run `tecopa runs show \(run)`.
                """, name)
        }
    }
}
