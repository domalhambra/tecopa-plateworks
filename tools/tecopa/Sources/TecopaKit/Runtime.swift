import Foundation

/// What one call needs. The CLI and the MCP server each build one, and a test builds
/// one over a fake machine.
public struct Runtime: Sendable {
    /// The launcher's engine port, and the default for every command.
    public static let defaultPort = 8848

    public var repoFlag: String?
    public var port: Int
    public var environment: [String: String]
    public var home: String
    public var http: any HTTPFetching
    public var runner: any ProcessRunning
    public var fileExists: @Sendable (String) -> Bool
    public var sleep: @Sendable (Double) async -> Void
    /// The text of one file, or nil when it cannot be read.
    public var readFile: @Sendable (String) -> String?

    public init(
        repoFlag: String? = nil,
        port: Int = Runtime.defaultPort,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        home: String = NSHomeDirectory(),
        http: any HTTPFetching = URLSessionFetcher(),
        runner: any ProcessRunning = SystemProcessRunner(),
        fileExists: @escaping @Sendable (String) -> Bool = { FileManager.default.fileExists(atPath: $0) },
        sleep: @escaping @Sendable (Double) async -> Void = {
            try? await Task.sleep(nanoseconds: UInt64($0 * 1_000_000_000))
        },
        readFile: @escaping @Sendable (String) -> String? = {
            try? String(contentsOfFile: $0, encoding: .utf8)
        }
    ) {
        self.repoFlag = repoFlag
        self.port = port
        self.environment = environment
        self.home = home
        self.http = http
        self.runner = runner
        self.fileExists = fileExists
        self.sleep = sleep
        self.readFile = readFile
    }

    public var client: EngineClient { EngineClient(port: port, http: http) }

    public func repo() throws -> String {
        try RepoLocator.resolve(flag: repoFlag, env: environment, baked: bakedRepoPath,
                                fileExists: fileExists)
    }

    /// The launcher's log. The launcher and its engine both write here.
    public var logPath: String { home + "/Library/Logs/TecopaPlateworks.log" }

    /// Run one program. A program that cannot start is an environment fault.
    public func exec(_ executable: String, _ arguments: [String], cwd: String? = nil) throws -> ProcessResult {
        do {
            return try runner.run(executable, arguments, cwd: cwd)
        } catch let failure as TecopaFailure {
            throw failure
        } catch {
            throw TecopaFailure(.environment,
                                "Could not start \(executable): \(error.localizedDescription)")
        }
    }
}
