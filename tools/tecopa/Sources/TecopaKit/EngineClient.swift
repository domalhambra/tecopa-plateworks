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

    /// The message for a port that another program holds. `engine status`, engine
    /// control, `doctor` and `debug(_:)` all say it with this one text.
    var notTecopaMessage: String {
        "Port \(port) answers, but it is not Tecopa Plateworks."
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
        return .reply(Reply(status: fetched.status, json: Self.value(of: fetched.body)))
    }

    /// A body as the tool reports it: the JSON, or the text as a JSON string when
    /// the body is not JSON. Each call that reads a body uses this one rule.
    static func value(of body: Data) -> JSONValue {
        (try? JSONValue.parse(body)) ?? .string(String(decoding: body, as: UTF8.self))
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
            throw refusedFailure(reply.status, path, reply.json)
        }
        return reply.json
    }

    func refusedFailure(_ status: Int, _ path: String, _ body: JSONValue) -> TecopaFailure {
        TecopaFailure(.refused, "The engine answered \(status) for \(path).",
                      status: status, body: body)
    }

    /// POST one multipart form. Any HTTP answer returns, a 422 included: a render
    /// route answers with JSON or with the image itself, so the caller reads the
    /// reply. The default deadline is long because a proof can take minutes.
    public func post(_ path: String, _ form: Multipart,
                     timeout: TimeInterval = 300) async throws -> HTTPReply {
        var request = URLRequest(url: try address(path))
        request.httpMethod = "POST"
        request.setValue(form.contentType, forHTTPHeaderField: "Content-Type")
        request.httpBody = form.body()
        return try await send(request, timeout: timeout)
    }

    /// GET one path and keep the bytes and the content type: a finished job's file.
    public func download(_ path: String, timeout: TimeInterval = 300) async throws -> HTTPReply {
        try await send(URLRequest(url: try address(path)), timeout: timeout)
    }

    /// One request. No answer is `engine_unreachable`, with the same two messages
    /// as `raw`.
    private func send(_ request: URLRequest, timeout: TimeInterval) async throws -> HTTPReply {
        do {
            return try await http.send(request, timeout: timeout)
        } catch let error as URLError where error.code == .timedOut {
            throw timedOutFailure(timeout)
        } catch {
            throw noAnswerFailure()
        }
    }

    /// The JSON of a 2xx reply. Any other status is `refused`, with the engine's own
    /// body: the same rule as `get`.
    public func json(_ reply: HTTPReply, for path: String) throws -> JSONValue {
        let json = Self.value(of: reply.body)
        guard (200..<300).contains(reply.status) else {
            throw refusedFailure(reply.status, path, json)
        }
        return json
    }

    /// A debug route. With the gate off the router does not exist, and the static
    /// mount answers 404 "Not Found". A debug route's own 404 has another detail.
    ///
    /// Any FastAPI program answers that same 404 for a path it does not have, so one
    /// look at /readyz says who holds the port. A program that is not the engine is
    /// an environment fault. An engine, and a port that gives /readyz no answer, is
    /// the closed gate.
    public func debug(_ path: String) async throws -> JSONValue {
        do {
            return try await get("/api/debug" + path)
        } catch let failure as TecopaFailure
            where failure.status == 404 && failure.body?["detail"]?.stringValue == "Not Found" {
            if case .reply(let ready) = await probe("/readyz", timeout: 2), !Self.isTecopa(ready) {
                throw TecopaFailure(
                    .environment, notTecopaMessage,
                    hint: "Quit the other program on that port, or pass the engine's port.")
            }
            throw TecopaFailure(
                .refused, Self.gateOffMessage + "\(port).",
                hint: "Start the engine with TECOPA_DEBUG=1. The launcher sets it.",
                status: 404, body: failure.body)
        }
    }
}
