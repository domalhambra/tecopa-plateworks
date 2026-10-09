import Foundation

/// HTTP to the engine, on 127.0.0.1 only. It reports what the engine said. It never
/// retries, and it never sends a flag that the caller did not give.
public struct EngineClient: Sendable {
    public let port: Int
    public let http: any HTTPFetching

    public init(port: Int, http: any HTTPFetching) {
        self.port = port
        self.http = http
    }

    public struct Reply: Equatable, Sendable {
        public let status: Int
        public let json: JSONValue
    }

    /// Any HTTP answer is a Reply, a 503 included. No answer is `engine_unreachable`.
    public func raw(_ path: String, timeout: TimeInterval = 10) async throws -> Reply {
        guard let url = URL(string: "http://127.0.0.1:\(port)" + path) else {
            throw TecopaFailure(.usage, "Not a valid path: \(path)")
        }
        let fetched: (status: Int, body: Data)
        do {
            fetched = try await http.get(url, timeout: timeout)
        } catch {
            throw TecopaFailure(.engineUnreachable, "No engine answers on port \(port).",
                                hint: "Run `tecopa doctor`.")
        }
        let json = (try? JSONValue.parse(fetched.body))
            ?? .string(String(decoding: fetched.body, as: UTF8.self))
        return Reply(status: fetched.status, json: json)
    }

    /// A 2xx body. Any other status is `refused`, with the engine's own body.
    public func get(_ path: String) async throws -> JSONValue {
        let reply = try await raw(path)
        guard (200..<300).contains(reply.status) else {
            throw TecopaFailure(.refused, "The engine answered \(reply.status) for \(path).",
                                status: reply.status, body: reply.json)
        }
        return reply.json
    }

    /// A debug route. With the gate off the router does not exist, and the static
    /// mount answers 404 "Not Found". A debug route's own 404 has another detail.
    public func debug(_ path: String) async throws -> JSONValue {
        do {
            return try await get("/api/debug" + path)
        } catch let failure as TecopaFailure
            where failure.status == 404 && failure.body?["detail"]?.stringValue == "Not Found" {
            throw TecopaFailure(
                .refused, "The debug routes are off on port \(port).",
                hint: "Start the engine with TECOPA_DEBUG=1. The launcher sets it.",
                status: 404, body: failure.body)
        }
    }
}
