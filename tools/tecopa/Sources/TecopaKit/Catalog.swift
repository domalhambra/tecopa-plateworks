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
    public static let all: [CatalogEntry] = EngineEntries.all + Launcher.entries + [LogReader.entry, ScriptRunner.verifyEntry]

    public static func named(_ name: String) -> CatalogEntry? {
        all.first { $0.name == name }
    }

    /// Run one entry. Never throws: a failure comes back as its envelope.
    public static func call(_ name: String, _ runtime: Runtime,
                            _ arguments: [String: JSONValue]) async -> (envelope: JSONValue, failure: TecopaFailure?) {
        guard let entry = named(name) else {
            let failure = TecopaFailure(.usage, "Unknown command: \(name)")
            return (failure.json, failure)
        }
        do {
            return (envelope(try await entry.run(runtime, arguments)), nil)
        } catch let failure as TecopaFailure {
            return (failure.json, failure)
        } catch {
            let failure = TecopaFailure(.environment, "\(error)")
            return (failure.json, failure)
        }
    }
}
