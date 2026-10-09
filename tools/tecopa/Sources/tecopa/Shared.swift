import ArgumentParser
import Foundation
import TecopaKit

/// The three options every command takes.
struct GlobalOptions: ParsableArguments {
    @Flag(name: .long, help: "Print the result envelope as JSON.")
    var json = false

    @Option(name: .long, help: "The repository path. Default: TECOPA_REPO, then the baked path.")
    var repo: String?

    @Option(name: .long, help: "The engine port.")
    var port: Int = Runtime.defaultPort
}

/// Run one catalog entry and print it. The one place the CLI prints and exits, so
/// every command has the same output and the same exit codes.
@discardableResult
func execute(_ name: String, _ global: GlobalOptions,
             _ arguments: [String: JSONValue] = [:]) async throws -> JSONValue {
    let runtime = Runtime(repoFlag: global.repo, port: global.port)
    let (result, failure) = await Catalog.call(name, runtime, arguments)
    let data = result["data"] ?? .null

    if global.json {
        print(result.text())
    } else if let failure {
        var lines = ["error: \(failure.message)"]
        if let hint = failure.hint { lines.append("hint: \(hint)") }
        if let body = failure.body { lines.append(body.text()) }
        FileHandle.standardError.write(Data((lines.joined(separator: "\n") + "\n").utf8))
    } else {
        print(Catalog.named(name)?.text?(data) ?? data.text())
    }

    if let failure { throw ExitCode(failure.exitCode) }
    return data
}
