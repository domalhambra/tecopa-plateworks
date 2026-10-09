import Foundation

/// The entries that only read the engine over HTTP.
enum EngineEntries {
    static let all: [CatalogEntry] = [engineStatus, regions, jobs, sessions, caches]

    static let engineStatus = CatalogEntry(
        name: "engine_status",
        summary: "Report if the engine answers, each plate's readiness, and the debug gate.",
        readOnly: true
    ) { runtime, _ in
        let ready: EngineClient.Reply
        do {
            ready = try await runtime.client.raw("/readyz", timeout: 3)
        } catch let failure as TecopaFailure where failure.kind == .engineUnreachable {
            // a stopped engine is a normal state, so it is data and not a failure
            return .object(["running": .bool(false), "port": .int(Int64(runtime.port))])
        }
        guard let isReady = ready.json["ready"], let plates = ready.json["regions"] else {
            throw TecopaFailure(
                .environment, "Port \(runtime.port) answers, but it is not Tecopa Plateworks.",
                hint: "Quit the other program on that port.")
        }
        var out: [String: JSONValue] = [
            "running": .bool(true), "port": .int(Int64(runtime.port)),
            "ready": isReady, "regions": plates,
        ]
        if let engine = try? await runtime.client.debug("/engine") {
            out["debug"] = .bool(true)
            out["engine"] = engine
        } else {
            out["debug"] = .bool(false)
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
        guard let sid = arguments["sid"]?.stringValue, !sid.isEmpty else {
            return try await runtime.client.debug("/sessions")
        }
        // the id goes into the URL path, and a real id is uuid4().hex
        guard sid.allSatisfy({ $0.isHexDigit }) else {
            throw TecopaFailure(.usage, "A session id is hexadecimal: \(sid)")
        }
        let full = arguments["full"]?.boolValue ?? false
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
