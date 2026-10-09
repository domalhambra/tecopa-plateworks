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

    /// What one request found. "Nothing listens" and "it listens and is slow" are
    /// different states: the second is an engine that is busy, not one that is stopped.
    public enum Probe: Equatable, Sendable {
        case reply(Reply)
        case noAnswer
        case timedOut
    }

    /// The start of the message `debug(_:)` throws when the gate is off. `isGateOff`
    /// reads the same constant, so the two cannot drift.
    static let gateOffMessage = "The debug routes are off on port "

    /// True only for the failure `debug(_:)` throws when the gate is off.
    public static func isGateOff(_ failure: TecopaFailure) -> Bool {
        failure.kind == .refused && failure.status == 404
            && failure.message.hasPrefix(gateOffMessage)
    }

    /// True when a reply is the engine's own /readyz: the JSON has both keys. This
    /// is the launcher app's rule too, and the one definition in the tool, so
    /// `engine status`, engine control and `doctor` cannot disagree on who owns a port.
    public static func isTecopa(_ reply: Reply) -> Bool {
        reply.json["ready"] != nil && reply.json["regions"] != nil
    }

    /// The URL of one engine path. The host is 127.0.0.1 and the port is this
    /// client's port, or the address is refused: a path such as "@host/x" would move
    /// the request to another machine.
    func address(_ path: String) throws -> URL {
        guard path.hasPrefix("/") else {
            throw TecopaFailure(.usage, "An engine path starts with a slash: \(path)")
        }
        guard (1...65535).contains(port),
              let url = URL(string: "http://127.0.0.1:\(port)" + path),
              url.host == "127.0.0.1", url.port == port else {
            throw TecopaFailure(.usage, "Not a valid engine address: port \(port), path \(path)")
        }
        return url
    }

    func noAnswerFailure() -> TecopaFailure {
        TecopaFailure(.engineUnreachable, "No engine answers on port \(port).",
                      hint: "Run `tecopa doctor`.")
    }

    func timedOutFailure(_ timeout: TimeInterval) -> TecopaFailure {
        TecopaFailure(
            .engineUnreachable,
            "The engine on port \(port) did not answer within \(secondsText(timeout)) seconds.",
            hint: "It may be busy with a render. Run `tecopa logs`.")
    }

    /// Ask one path. Never throws: any HTTP answer is `.reply`, a 503 included.
    public func probe(_ path: String, timeout: TimeInterval = 10) async -> Probe {
        // `probe` cannot throw, and an address the tool refuses is never asked, so
        // nothing answers from it. `raw` checks the address first and reports the
        // usage failure.
        guard let url = try? address(path) else { return .noAnswer }
        let fetched: (status: Int, body: Data)
        do {
            fetched = try await http.get(url, timeout: timeout)
        } catch let error as URLError where error.code == .timedOut {
            return .timedOut
        } catch {
            return .noAnswer
        }
        let json = (try? JSONValue.parse(fetched.body))
            ?? .string(String(decoding: fetched.body, as: UTF8.self))
        return .reply(Reply(status: fetched.status, json: json))
    }

    /// Any HTTP answer is a Reply, a 503 included. No answer is `engine_unreachable`,
    /// and its message says if nothing listens or if the engine did not answer in time.
    public func raw(_ path: String, timeout: TimeInterval = 10) async throws -> Reply {
        _ = try address(path)
        switch await probe(path, timeout: timeout) {
        case .reply(let reply): return reply
        case .noAnswer: throw noAnswerFailure()
        case .timedOut: throw timedOutFailure(timeout)
        }
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
                .refused, Self.gateOffMessage + "\(port).",
                hint: "Start the engine with TECOPA_DEBUG=1. The launcher sets it.",
                status: 404, body: failure.body)
        }
    }
}
