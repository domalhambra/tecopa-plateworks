import ArgumentParser
import Foundation
import MCP
import TecopaKit

/// The catalog over stdio. This file holds no operation: it turns a CatalogEntry into
/// a Tool and a tool call into Catalog.call, the same call the CLI makes.
///
/// Under `tecopa mcp` stdout carries the protocol, so nothing here prints.
enum MCPBridge {
    static func schema(for entry: CatalogEntry) -> Value {
        var properties: [String: Value] = [
            // every tool can address a development engine
            "port": .object([
                "type": .string("integer"),
                "description": .string(
                    "The engine port. Default \(Runtime.defaultPort), the launcher's engine."),
            ])
        ]
        for parameter in entry.parameters {
            var property: [String: Value] = ["description": .string(parameter.summary)]
            switch parameter.kind {
            case .string: property["type"] = .string("string")
            case .integer: property["type"] = .string("integer")
            case .boolean: property["type"] = .string("boolean")
            case .stringArray:
                property["type"] = .string("array")
                property["items"] = .object(["type": .string("string")])
            }
            properties[parameter.name] = .object(property)
        }
        return .object(["type": .string("object"), "properties": .object(properties)])
    }

    /// An MCP Value as the tool's own JSON type, through its Codable form.
    static func convert(_ value: Value) -> JSONValue {
        guard let data = try? JSONEncoder().encode(value),
              let json = try? JSONValue.parse(data) else { return .null }
        return json
    }

    /// One tool call. `port` is the bridge's own argument, so it comes out before the
    /// catalog validates the rest. A `port` that is not an integer is refused, never
    /// replaced by the default.
    static func call(_ params: CallTool.Parameters) async -> CallTool.Result {
        var arguments: [String: JSONValue] = [:]
        for (key, value) in params.arguments ?? [:] { arguments[key] = convert(value) }

        var port = Runtime.defaultPort
        if let given = arguments.removeValue(forKey: "port"), given != .null {
            guard let number = given.intValue else {
                return reply(TecopaFailure(.usage, "port must be an integer.").json, isError: true)
            }
            port = number
        }

        let (result, failure) = await Catalog.call(params.name, Runtime(port: port), arguments)
        return reply(result, isError: failure != nil)
    }

    static func reply(_ envelope: JSONValue, isError: Bool) -> CallTool.Result {
        .init(content: [.text(text: envelope.text(pretty: false), annotations: nil, _meta: nil)],
              isError: isError)
    }

    static func serve() async throws {
        let server = Server(
            name: "tecopa", version: bakedVersion,
            capabilities: .init(tools: .init(listChanged: false)))

        await server.withMethodHandler(ListTools.self) { _ in
            .init(tools: Catalog.all.map { entry in
                Tool(name: entry.name, description: entry.summary,
                     inputSchema: schema(for: entry),
                     annotations: .init(readOnlyHint: entry.readOnly))
            })
        }

        await server.withMethodHandler(CallTool.self) { params in
            await call(params)
        }

        try await server.start(transport: StdioTransport())
        await server.waitUntilCompleted()
    }
}

struct MCPCommand: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "mcp",
        abstract: "Serve every command as an MCP tool on stdio.")

    func run() async throws { try await MCPBridge.serve() }
}
