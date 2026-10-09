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

/// Refuses every redirect, so the 3xx itself comes back as the reply. A program on
/// the port that is not the engine could answer `302 Location: http://elsewhere/`,
/// and the tool talks only to 127.0.0.1.
private final class RedirectRefuser: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

public struct URLSessionFetcher: HTTPFetching {
    public init() {}

    public func get(_ url: URL, timeout: TimeInterval) async throws -> (status: Int, body: Data) {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = timeout
        config.timeoutIntervalForResource = timeout
        // An empty dictionary, so a system proxy never carries a request to the engine.
        config.connectionProxyDictionary = [:]
        let session = URLSession(configuration: config, delegate: RedirectRefuser(), delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(from: url)
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        return (http.statusCode, data)
    }
}

/// The bytes of one pipe. One thread writes them and another reads them, so a lock
/// guards the value.
private final class DataBox: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()

    func set(_ new: Data) { lock.withLock { data = new } }
    func get() -> Data { lock.withLock { data } }
}

public struct SystemProcessRunner: ProcessRunning {
    /// The longest time a child may run, in seconds.
    public let timeout: TimeInterval
    /// After the deadline: the time a child has to end after each signal.
    static let grace: TimeInterval = 2

    public init(timeout: TimeInterval = 300) {
        self.timeout = timeout
    }

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

        // Three things must end: the child, and the read of each pipe.
        let done = DispatchGroup()
        done.enter()
        process.terminationHandler = { _ in done.leave() }
        do {
            try process.run()
        } catch {
            done.leave()
            throw error
        }

        // Drain both pipes while the child runs. A child that fills one pipe while
        // the tool waits on the other would block for ever.
        let outBox = DataBox()
        let errBox = DataBox()
        for (handle, box) in [(out.fileHandleForReading, outBox), (err.fileHandleForReading, errBox)] {
            done.enter()
            DispatchQueue.global().async {
                box.set(handle.readDataToEndOfFile())
                done.leave()
            }
        }

        if done.wait(timeout: .now() + timeout) == .timedOut {
            if process.isRunning {
                process.terminate()
                // A child that ignores SIGTERM gets SIGKILL, or the deadline would
                // not be a deadline. The waits are bounded because a grandchild can
                // hold a pipe open after the child ends.
                if done.wait(timeout: .now() + Self.grace) == .timedOut, process.isRunning {
                    kill(process.processIdentifier, SIGKILL)
                    _ = done.wait(timeout: .now() + Self.grace)
                }
            }
            let name = (executable as NSString).lastPathComponent
            throw TecopaFailure(
                .environment, "\(name) did not finish within \(secondsText(timeout)) seconds.")
        }

        // A signal number is not an exit code. The shell convention keeps them apart.
        let status = process.terminationStatus
        let exitCode = process.terminationReason == .uncaughtSignal ? 128 + status : status
        return ProcessResult(exitCode: exitCode,
                             stdout: String(decoding: outBox.get(), as: UTF8.self),
                             stderr: String(decoding: errBox.get(), as: UTF8.self))
    }
}
