import Foundation

/// The entries that only read the engine over HTTP.
enum EngineEntries {
    static let all: [CatalogEntry] = [engineStatus, regions, jobs, sessions, caches]

    static let engineStatus = CatalogEntry(
        name: "engine_status",
        summary: "Report if the engine answers, each plate's readiness, and the debug gate.",
        readOnly: true
    ) { runtime, _ in
        // `probe` cannot throw, so it reports an address the tool refuses as no
        // answer. Check the address first: a port out of range is a usage failure,
        // not a stopped engine.
        _ = try runtime.client.address("/readyz")
        let ready: EngineClient.Reply
        switch await runtime.client.probe("/readyz", timeout: 3) {
        case .reply(let reply):
            ready = reply
        case .noAnswer:
            // a stopped engine is a normal state, so it is data and not a failure
            return .object(["running": .bool(false), "port": .int(Int64(runtime.port))])
        case .timedOut:
            // an engine that is busy with a render is not a stopped engine
            throw runtime.client.timedOutFailure(3)
        }
        guard EngineClient.isTecopa(ready) else {
            throw TecopaFailure(
                .environment, runtime.client.notTecopaMessage,
                hint: "Quit the other program on that port.")
        }
        var out: [String: JSONValue] = [
            "running": .bool(true), "port": .int(Int64(runtime.port)),
            "ready": ready.json["ready"] ?? .null, "regions": ready.json["regions"] ?? .null,
        ]
        do {
            out["engine"] = try await runtime.client.debug("/engine")
            out["debug"] = .bool(true)
        } catch let failure as TecopaFailure where EngineClient.isGateOff(failure) {
            out["debug"] = .bool(false)
        } catch {
            // the gate's state is not known, so it is not reported as off
            out["debug"] = .null
            out["debug_error"] = .string((error as? TecopaFailure)?.message ?? "\(error)")
        }
        return .object(out)
    }

    static let regions = CatalogEntry(
        name: "regions",
        summary: "List the plates the engine serves, with the readiness report for each.",
        readOnly: true
    ) { runtime, _ in
        let plates = try await runtime.client.get("/api/regions")
        let ready = try await runtime.client.raw("/readyz")
        return .object([
            "regions": plates,
            "ready": ready.json["ready"] ?? .null,
            "readiness": ready.json["regions"] ?? .null,
        ])
    }

    static let jobs = CatalogEntry(
        name: "jobs",
        summary: "List every job in the render, build and proof queues, newest first.",
        readOnly: true
    ) { runtime, _ in
        try await runtime.client.debug("/jobs")
    }

    static let sessions = CatalogEntry(
        name: "sessions",
        summary: "List the engine's sessions, or show one session's spec and tracks.",
        readOnly: true,
        parameters: [
            EntryParameter("sid", .string, "A session id. Without it, every session is listed."),
            EntryParameter("full", .boolean, "With sid: include the track geometry."),
        ]
    ) { runtime, arguments in
        let full = arguments["full"]?.boolValue ?? false
        guard let sid = arguments["sid"]?.stringValue, !sid.isEmpty else {
            guard !full else { throw TecopaFailure(.usage, "full needs a session id.") }
            return try await runtime.client.debug("/sessions")
        }
        // the id goes into the URL path, and a real id is uuid4().hex. isHexDigit
        // alone is also true for the fullwidth forms, which are not ASCII.
        guard sid.allSatisfy({ $0.isASCII && $0.isHexDigit }) else {
            throw TecopaFailure(.usage, "A session id is hexadecimal: \(sid)")
        }
        return try await runtime.client.debug("/sessions/" + sid + (full ? "?full=1" : ""))
    }

    static let caches = CatalogEntry(
        name: "caches",
        summary: "Report the terrain cache and the route-ink cache: entries, bytes, hits, misses.",
        readOnly: true
    ) { runtime, _ in
        try await runtime.client.debug("/caches")
    }
}
