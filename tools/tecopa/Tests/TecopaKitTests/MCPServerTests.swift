import XCTest
@testable import TecopaKit

/// These tests start the built binary and speak the protocol as raw lines, so they
/// test what a real client sees and depend on no client library.
final class MCPServerTests: XCTestCase {
    private let readOnly: Set<String> = [
        "doctor", "engine_status", "logs", "regions", "regions_verify", "jobs", "sessions", "caches",
        "reprint_inspect", "studio_state", "studio_errors", "runs", "runs_show",
        "plate_plan", "plate_check", "order_status"]
    /// Not read-only: the entries that control the engine, the ones that write a
    /// file, and the ones that start or run a script that writes.
    private let writes: Set<String> = [
        "engine_start", "engine_stop", "engine_restart",
        "render_proof", "render_final", "render_wallpaper", "render_film", "render_fetch",
        "reprint", "continue", "runs_cancel",
        "plate_build", "plate_labels", "plate_playa", "plate_pack", "plate_install",
        "order_new", "order_prepare", "order_preview"]

    private var binary: URL {
        // the test bundle sits beside the products of the same build
        Bundle(for: MCPServerTests.self).bundleURL
            .deletingLastPathComponent().appendingPathComponent("tecopa")
    }

    /// Collects stdout as it arrives, split into lines. The handler runs on a
    /// background queue, so the state sits behind a lock.
    private final class LineCollector: @unchecked Sendable {
        private let lock = NSLock()
        private var pending = Data()
        private var lines: [String] = []

        /// Add bytes. Returns the complete lines that arrived with them.
        func append(_ data: Data) -> [String] {
            lock.lock(); defer { lock.unlock() }
            pending.append(data)
            var fresh: [String] = []
            while let newline = pending.firstIndex(of: 0x0A) {
                let line = String(decoding: pending[pending.startIndex..<newline], as: UTF8.self)
                pending.removeSubrange(pending.startIndex...newline)
                if !line.isEmpty { fresh.append(line) }
            }
            lines.append(contentsOf: fresh)
            return fresh
        }

        var all: [String] {
            lock.lock(); defer { lock.unlock() }
            return lines
        }
    }

    /// Send the handshake and the requests, wait until the last request is answered,
    /// close stdin, and return every line the server wrote. The last request must
    /// carry an `id`.
    private func converse(_ requests: [String], lastId: Int) throws -> [JSONValue] {
        let process = Process()
        process.executableURL = binary
        process.arguments = ["mcp"]
        let input = Pipe()
        let output = Pipe()
        process.standardInput = input
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice

        let collector = LineCollector()
        let answered = DispatchSemaphore(value: 0)
        output.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty {                         // end of file
                handle.readabilityHandler = nil
                return
            }
            for line in collector.append(data) {
                if let value = try? JSONValue.parse(Data(line.utf8)),
                   value["id"]?.intValue == lastId {
                    answered.signal()
                }
            }
        }

        try process.run()
        let lines = [
            #"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}"#,
            #"{"jsonrpc":"2.0","method":"notifications/initialized"}"#,
        ] + requests
        input.fileHandleForWriting.write(Data((lines.joined(separator: "\n") + "\n").utf8))

        let gotLast = answered.wait(timeout: .now() + 15) == .success
        XCTAssertTrue(gotLast, "no reply with id \(lastId) within 15 seconds")

        try input.fileHandleForWriting.close()
        let exited = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in exited.signal() }
        if !process.isRunning { exited.signal() }
        if exited.wait(timeout: .now() + 10) != .success {
            process.terminate()
            XCTFail("the server did not exit after stdin closed")
        }
        output.fileHandleForReading.readabilityHandler = nil
        _ = collector.append(output.fileHandleForReading.readDataToEndOfFile())

        // Nothing but protocol lines may reach stdout.
        var replies: [JSONValue] = []
        for line in collector.all {
            if let value = try? JSONValue.parse(Data(line.utf8)) {
                replies.append(value)
            } else {
                XCTFail("stdout carried a line that is not JSON: \(line)")
            }
        }
        return replies
    }

    private func reply(_ replies: [JSONValue], id: Int) -> JSONValue? {
        replies.first { $0["id"]?.intValue == id }
    }

    func testToolsListIsTheCatalogWithTheCorrectAnnotation() throws {
        let replies = try converse([#"{"jsonrpc":"2.0","id":2,"method":"tools/list"}"#], lastId: 2)
        let tools = reply(replies, id: 2)?["result"]?["tools"]?.arrayValue ?? []
        let names = Set(tools.compactMap { $0["name"]?.stringValue })
        XCTAssertEqual(tools.count, 35)
        XCTAssertEqual(names, readOnly.union(writes))
        XCTAssertEqual(names, Set(Catalog.all.map { $0.name }))
        for tool in tools {
            let name = tool["name"]?.stringValue ?? ""
            XCTAssertEqual(tool["annotations"]?["readOnlyHint"]?.boolValue, readOnly.contains(name), name)
            XCTAssertEqual(tool["inputSchema"]?["type"]?.stringValue, "object", name)
            XCTAssertNotNil(tool["inputSchema"]?["properties"]?["port"], "\(name) has no port")
        }
        let sessions = tools.first { $0["name"]?.stringValue == "sessions" }
        XCTAssertNotNil(sessions?["inputSchema"]?["properties"]?["sid"])
        XCTAssertNotNil(sessions?["inputSchema"]?["properties"]?["full"])
        let verify = tools.first { $0["name"]?.stringValue == "regions_verify" }
        XCTAssertEqual(verify?["inputSchema"]?["properties"]?["regions"]?["type"]?.stringValue, "array")
        for name in ["engine_stop", "engine_restart"] {
            let tool = tools.first { $0["name"]?.stringValue == name }
            XCTAssertEqual(tool?["inputSchema"]?["properties"]?["force"]?["type"]?.stringValue,
                           "boolean", name)
        }
        let start = tools.first { $0["name"]?.stringValue == "engine_start" }
        XCTAssertNil(start?["inputSchema"]?["properties"]?["force"])
        // a render's lists are arrays of strings, and its flag is a boolean
        let final = tools.first { $0["name"]?.stringValue == "render_final" }
        for name in ["tracks", "set", "opt"] {
            XCTAssertEqual(final?["inputSchema"]?["properties"]?[name]?["type"]?.stringValue, "array", name)
        }
        XCTAssertEqual(final?["inputSchema"]?["properties"]?["no_wait"]?["type"]?.stringValue, "boolean")
        let proof = tools.first { $0["name"]?.stringValue == "render_proof" }
        XCTAssertNil(proof?["inputSchema"]?["properties"]?["opt"])
        XCTAssertNil(proof?["inputSchema"]?["properties"]?["no_wait"])
        // the plate flag is a boolean of the two entries that render a file, and of no other
        for tool in tools {
            let name = tool["name"]?.stringValue ?? ""
            XCTAssertEqual(tool["inputSchema"]?["properties"]?["allow_plate_mismatch"]?["type"]?.stringValue,
                           ["reprint", "continue"].contains(name) ? "boolean" : nil, name)
        }
        // the two filters of `studio errors` are strings, and `studio state` has none
        let errors = tools.first { $0["name"]?.stringValue == "studio_errors" }
        for name in ["tab", "kind"] {
            XCTAssertEqual(errors?["inputSchema"]?["properties"]?[name]?["type"]?.stringValue, "string", name)
        }
        let state = tools.first { $0["name"]?.stringValue == "studio_state" }
        XCTAssertNil(state?["inputSchema"]?["properties"]?["tab"])
        // a run is named by a string, and only `runs show` takes a number of lines
        for name in ["runs_show", "runs_cancel"] {
            let tool = tools.first { $0["name"]?.stringValue == name }
            XCTAssertEqual(tool?["inputSchema"]?["properties"]?["run"]?["type"]?.stringValue, "string", name)
        }
        let show = tools.first { $0["name"]?.stringValue == "runs_show" }
        XCTAssertEqual(show?["inputSchema"]?["properties"]?["lines"]?["type"]?.stringValue, "integer")
        let cancel = tools.first { $0["name"]?.stringValue == "runs_cancel" }
        XCTAssertNil(cancel?["inputSchema"]?["properties"]?["lines"])
        let inspect = tools.first { $0["name"]?.stringValue == "reprint_inspect" }
        XCTAssertEqual(inspect?["inputSchema"]?["properties"]?["file"]?["type"]?.stringValue, "string")
        // a plate build: the four bbox numbers are strings in a list, and the EPSG code is an integer
        let build = tools.first { $0["name"]?.stringValue == "plate_build" }
        XCTAssertEqual(build?["inputSchema"]?["properties"]?["bbox"]?["type"]?.stringValue, "array")
        XCTAssertEqual(build?["inputSchema"]?["properties"]?["bbox"]?["items"]?["type"]?.stringValue, "string")
        XCTAssertEqual(build?["inputSchema"]?["properties"]?["epsg"]?["type"]?.stringValue, "integer")
        for name in ["id", "name", "resolution"] {
            XCTAssertEqual(build?["inputSchema"]?["properties"]?[name]?["type"]?.stringValue, "string", name)
        }
        // a new order is named by its number, and by nothing more
        let new = tools.first { $0["name"]?.stringValue == "order_new" }
        XCTAssertEqual(new?["inputSchema"]?["properties"]?["number"]?["type"]?.stringValue, "string")
        if case .object(let properties)? = new?["inputSchema"]?["properties"] {
            XCTAssertEqual(Set(properties.keys), ["number", "port"])
        } else {
            XCTFail("order_new has no properties")
        }
        // an order is named by its folder, and by nothing more
        for name in ["order_prepare", "order_preview", "order_status"] {
            let tool = tools.first { $0["name"]?.stringValue == name }
            XCTAssertEqual(tool?["inputSchema"]?["properties"]?["folder"]?["type"]?.stringValue, "string", name)
            guard case .object(let properties)? = tool?["inputSchema"]?["properties"] else {
                XCTFail("\(name) has no properties")
                continue
            }
            XCTAssertEqual(Set(properties.keys), ["folder", "port"], name)
        }
        // only `plate pack` has the resync flag, and no plate or order tool has a flag that replaces or moves a folder
        for tool in tools where ["plate_", "order_"].contains(where: (tool["name"]?.stringValue ?? "").hasPrefix) {
            let name = tool["name"]?.stringValue ?? ""
            XCTAssertEqual(tool["inputSchema"]?["properties"]?["resync"]?["type"]?.stringValue,
                           name == "plate_pack" ? "boolean" : nil, name)
            for flag in ["replace", "root", "out_root", "regions_root", "out"] {
                XCTAssertNil(tool["inputSchema"]?["properties"]?[flag], "\(name) \(flag)")
            }
        }
    }

    func testEveryToolHasACommandOfTheSameWords() throws {
        for entry in Catalog.all {
            let process = Process()
            process.executableURL = binary
            process.arguments = entry.name.split(separator: "_").map(String.init) + ["--help"]
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            try process.run()
            process.waitUntilExit()
            XCTAssertEqual(process.terminationStatus, 0, "tecopa \(entry.name) --help")
        }
    }

    func testAFailedCallReturnsTheEnvelopeWithTheErrorFlag() throws {
        // port 9 answers nothing, so the engine is unreachable whatever runs on 8848
        let call = #"{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"jobs","arguments":{"port":9}}}"#
        let replies = try converse([call], lastId: 3)
        let result = reply(replies, id: 3)?["result"]
        XCTAssertEqual(result?["isError"], .bool(true))
        let text = result?["content"]?.arrayValue?.first?["text"]?.stringValue ?? ""
        let envelope = try JSONValue.parse(Data(text.utf8))
        XCTAssertEqual(envelope["ok"], .bool(false))
        XCTAssertEqual(envelope["error"]?["kind"]?.stringValue, "engine_unreachable")
    }

    func testAMisspelledArgumentIsRefusedThroughMCP() throws {
        let call = #"{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"sessions","arguments":{"sidd":"ab","port":9}}}"#
        let replies = try converse([call], lastId: 4)
        let result = reply(replies, id: 4)?["result"]
        XCTAssertEqual(result?["isError"], .bool(true))
        let text = result?["content"]?.arrayValue?.first?["text"]?.stringValue ?? ""
        let envelope = try JSONValue.parse(Data(text.utf8))
        XCTAssertEqual(envelope["error"]?["kind"]?.stringValue, "usage")
    }

    func testAPortThatIsNotAnIntegerIsRefusedNotIgnored() throws {
        let call = #"{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"jobs","arguments":{"port":"nine"}}}"#
        let replies = try converse([call], lastId: 5)
        let result = reply(replies, id: 5)?["result"]
        XCTAssertEqual(result?["isError"], .bool(true))
        let text = result?["content"]?.arrayValue?.first?["text"]?.stringValue ?? ""
        let envelope = try JSONValue.parse(Data(text.utf8))
        XCTAssertEqual(envelope["error"]?["kind"]?.stringValue, "usage")
    }

    func testJobsJSONOnAStoppedEnginePrintsTheEnvelopeAndExits3() throws {
        let process = Process()
        process.executableURL = binary
        process.arguments = ["jobs", "--json", "--port", "9"]
        let output = Pipe()
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        XCTAssertEqual(process.terminationStatus, 3)
        let envelope = try JSONValue.parse(data)
        XCTAssertEqual(envelope["ok"], .bool(false))
        XCTAssertEqual(envelope["error"]?["kind"]?.stringValue, "engine_unreachable")
    }
}
