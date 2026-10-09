import Foundation

/// The two places the tool touches the machine. A test replaces both.
public protocol HTTPFetching: Sendable {
    /// Any HTTP answer returns. No answer throws.
    func get(_ url: URL, timeout: TimeInterval) async throws -> (status: Int, body: Data)
}

public struct ProcessResult: Equatable, Sendable {
    public let exitCode: Int32
    public let stdout: String
    public let stderr: String

    public init(exitCode: Int32, stdout: String, stderr: String) {
        self.exitCode = exitCode
        self.stdout = stdout
        self.stderr = stderr
    }
}

public protocol ProcessRunning: Sendable {
    func run(_ executable: String, _ arguments: [String], cwd: String?) throws -> ProcessResult
}

public struct URLSessionFetcher: HTTPFetching {
    public init() {}

    public func get(_ url: URL, timeout: TimeInterval) async throws -> (status: Int, body: Data) {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = timeout
        config.timeoutIntervalForResource = timeout
        let session = URLSession(configuration: config)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(from: url)
        return ((response as? HTTPURLResponse)?.statusCode ?? 0, data)
    }
}

public struct SystemProcessRunner: ProcessRunning {
    public init() {}

    public func run(_ executable: String, _ arguments: [String], cwd: String?) throws -> ProcessResult {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        if let cwd { process.currentDirectoryURL = URL(fileURLWithPath: cwd) }
        let out = Pipe()
        let err = Pipe()
        process.standardOutput = out
        process.standardError = err
        // Never the tool's own stdin or stdout: under `tecopa mcp` those carry the
        // protocol, and a child that wrote to them would corrupt it.
        process.standardInput = FileHandle.nullDevice
        try process.run()

        // Drain both pipes while the child runs. A child that fills one pipe while
        // the tool waits on the other would block for ever.
        var errData = Data()
        let group = DispatchGroup()
        group.enter()
        DispatchQueue.global().async {
            errData = err.fileHandleForReading.readDataToEndOfFile()
            group.leave()
        }
        let outData = out.fileHandleForReading.readDataToEndOfFile()
        group.wait()
        process.waitUntilExit()
        return ProcessResult(exitCode: process.terminationStatus,
                             stdout: String(decoding: outData, as: UTF8.self),
                             stderr: String(decoding: errData, as: UTF8.self))
    }
}
