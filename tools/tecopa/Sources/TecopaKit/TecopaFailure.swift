import Foundation

/// The one error the tool reports. It says what the engine or the machine said and
/// adds a hint. It never decides to retry.
public struct TecopaFailure: Error, Equatable, Sendable {
    public enum Kind: String, Sendable {
        case refused                              // the engine or a script said no
        case usage                                // the tool found a bad argument
        case engineUnreachable = "engine_unreachable"
        case environment                          // a missing repo, venv, script or launcher
    }

    public let kind: Kind
    public let message: String
    public let hint: String?
    public let status: Int?
    public let body: JSONValue?

    public init(_ kind: Kind, _ message: String, hint: String? = nil,
                status: Int? = nil, body: JSONValue? = nil) {
        self.kind = kind
        self.message = message
        self.hint = hint
        self.status = status
        self.body = body
    }

    public var exitCode: Int32 {
        switch kind {
        case .refused: return 1
        case .usage: return 2
        case .engineUnreachable: return 3
        case .environment: return 4
        }
    }

    /// The failure envelope. The engine's own body rides in it unchanged.
    public var json: JSONValue {
        var error: [String: JSONValue] = [
            "kind": .string(kind.rawValue), "message": .string(message)]
        if let hint { error["hint"] = .string(hint) }
        if let status { error["status"] = .int(Int64(status)) }
        if let body { error["body"] = body }
        return .object(["ok": .bool(false), "error": .object(error)])
    }
}

/// The success envelope.
public func envelope(_ data: JSONValue) -> JSONValue {
    .object(["ok": .bool(true), "data": data])
}

/// A number of seconds for a message: "3" and "0.5", never "3.0".
func secondsText(_ seconds: TimeInterval) -> String {
    if let whole = Int(exactly: seconds) { return String(whole) }
    return String(seconds)
}
