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

/// A path as a person writes it on the command line, made absolute: a leading `~`
/// is the home folder, and a relative path is under the current directory. A
/// catalog entry takes an absolute path only, because under `tecopa mcp` the
/// working directory is the MCP client's and not the caller's.
///
/// The text is joined and not resolved: the system reads `..` and each link. An
/// empty path stays empty, so the entry says which argument is missing.
///
/// A working directory that was deleted reads as an empty text. With no absolute
/// directory, a relative path stays as it is and the entry refuses it: "/" and the
/// path would name a file in the root folder, which the caller did not write.
func absolutePath(_ path: String, home: String = NSHomeDirectory(),
                  directory: String = FileManager.default.currentDirectoryPath) -> String {
    if path.isEmpty || path.hasPrefix("/") { return path }
    if path == "~" { return home }
    if path.hasPrefix("~/") { return home + path.dropFirst() }
    guard directory.hasPrefix("/") else { return path }
    return (directory.hasSuffix("/") ? directory : directory + "/") + path
}
