import Foundation

/// One argument of one entry. The CLI declares it as an option and the MCP server
/// puts it in the tool's input schema.
public struct EntryParameter: Sendable {
    public enum Kind: String, Sendable { case string, integer, boolean, stringArray }

    public let name: String
    public let kind: Kind
    public let summary: String

    public init(_ name: String, _ kind: Kind, _ summary: String) {
        self.name = name
        self.kind = kind
        self.summary = summary
    }
}

extension EntryParameter.Kind {
    /// True if a JSON value is this kind. An integer may arrive as a double with a
    /// whole value, because a JSON writer may print 50 as 50.0.
    func accepts(_ value: JSONValue) -> Bool {
        switch (self, value) {
        case (.string, .string), (.integer, .int), (.boolean, .bool):
            return true
        case (.integer, .double(let number)):
            return Int64(exactly: number) != nil
        case (.stringArray, .array(let items)):
            return items.allSatisfy { $0.stringValue != nil }
        default:
            return false
        }
    }

    /// The kind with its article, for "<name> must be <phrase>."
    var phrase: String {
        switch self {
        case .string: return "a string"
        case .integer: return "an integer"
        case .boolean: return "a boolean"
        case .stringArray: return "a list of strings"
        }
    }
}

/// One operation. `name` is the MCP tool name, and the CLI command is the same words
/// with a space for each underscore.
public struct CatalogEntry: Sendable {
    public let name: String
    public let summary: String
    public let readOnly: Bool
    public let parameters: [EntryParameter]
    public let run: @Sendable (Runtime, [String: JSONValue]) async throws -> JSONValue
    /// How the CLI prints the data without --json. nil means pretty JSON.
    public let text: (@Sendable (JSONValue) -> String)?

    public init(name: String, summary: String, readOnly: Bool,
                parameters: [EntryParameter] = [],
                text: (@Sendable (JSONValue) -> String)? = nil,
                run: @escaping @Sendable (Runtime, [String: JSONValue]) async throws -> JSONValue) {
        self.name = name
        self.summary = summary
        self.readOnly = readOnly
        self.parameters = parameters
        self.text = text
        self.run = run
    }
}

/// Every operation the tool has. The CLI and the MCP server both call `call`, so a
/// command and its tool cannot differ.
public enum Catalog {
    public static let all: [CatalogEntry] =
        [Doctor.entry] + EngineEntries.all + Launcher.entries
        + [LogReader.entry, ScriptRunner.verifyEntry] + Render.entries

    public static func named(_ name: String) -> CatalogEntry? {
        all.first { $0.name == name }
    }

    /// Check the arguments against the entry's parameters. This is on the one shared
    /// path, so the CLI and an MCP caller get the same answer: a misspelled name or a
    /// wrong kind is refused, never ignored. A null value means "not given".
    static func validated(_ arguments: [String: JSONValue],
                          for entry: CatalogEntry) throws -> [String: JSONValue] {
        var cleaned: [String: JSONValue] = [:]
        for key in arguments.keys.sorted() {
            guard let value = arguments[key] else { continue }
            guard let parameter = entry.parameters.first(where: { $0.name == key }) else {
                let names = entry.parameters.map(\.name).joined(separator: ", ")
                throw TecopaFailure(
                    .usage, "Unknown argument for \(entry.name): \(key)",
                    hint: names.isEmpty ? "This command takes no arguments."
                                        : "The arguments are: \(names).")
            }
            if value == .null { continue }
            guard parameter.kind.accepts(value) else {
                throw TecopaFailure(.usage, "\(key) must be \(parameter.kind.phrase).")
            }
            cleaned[key] = value
        }
        return cleaned
    }

    /// Run one entry. Never throws: a failure comes back as its envelope.
    public static func call(_ name: String, _ runtime: Runtime,
                            _ arguments: [String: JSONValue]) async -> (envelope: JSONValue, failure: TecopaFailure?) {
        guard let entry = named(name) else {
            let failure = TecopaFailure(.usage, "Unknown command: \(name)")
            return (failure.json, failure)
        }
        do {
            let cleaned = try validated(arguments, for: entry)
            return (envelope(try await entry.run(runtime, cleaned)), nil)
        } catch let failure as TecopaFailure {
            return (failure.json, failure)
        } catch {
            let failure = TecopaFailure(.environment, "\(error)")
            return (failure.json, failure)
        }
    }
}
