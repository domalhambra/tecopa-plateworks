import Foundation

/// One HTTP answer: the status, the Content-Type header if the answer has one, and
/// the bytes. A render route answers with JSON or with the image itself, and the
/// content type says which.
public struct HTTPReply: Equatable, Sendable {
    public let status: Int
    public let contentType: String?
    public let body: Data

    public init(status: Int, contentType: String?, body: Data) {
        self.status = status
        self.contentType = contentType
        self.body = body
    }
}

/// The two places the tool touches the machine. A test replaces both.
public protocol HTTPFetching: Sendable {
    /// Any HTTP answer returns. No answer throws.
    func get(_ url: URL, timeout: TimeInterval) async throws -> (status: Int, body: Data)
    /// One request with its own method, headers and body. Any HTTP answer returns,
    /// a 3xx included. No answer throws.
    func send(_ request: URLRequest, timeout: TimeInterval) async throws -> HTTPReply
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
    /// Run one program and wait for it. `environment` is all of the program's
    /// environment, and nil gives it the tool's own.
    func run(_ executable: String, _ arguments: [String], cwd: String?,
             environment: [String: String]?) throws -> ProcessResult

    /// Start one program and return its process id at once. The tool does not wait
    /// for it. The program is the leader of a new session, so it outlives the tool
    /// and a closed terminal, and its process group has its own process id.
    /// `environment` is all of the program's environment.
    func startDetached(_ executable: String, _ arguments: [String], cwd: String?,
                       environment: [String: String]) throws -> Int32

    /// Send one signal to every process of one process group.
    func signalGroup(_ group: Int32, _ signal: Int32) throws
}

extension ProcessRunning {
    /// Run one program with the tool's own environment.
    public func run(_ executable: String, _ arguments: [String], cwd: String?) throws -> ProcessResult {
        try run(executable, arguments, cwd: cwd, environment: nil)
    }
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

    /// The rules of every session: nothing kept on disk, one deadline, and no proxy.
    static func configuration(timeout: TimeInterval) -> URLSessionConfiguration {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = timeout
        config.timeoutIntervalForResource = timeout
        // An empty dictionary, so a system proxy never carries a request to the engine.
        config.connectionProxyDictionary = [:]
        return config
    }

    /// The one place a session is made, so `get` and `send` cannot have different
    /// rules: the configuration above, and every redirect refused.
    private static func session(timeout: TimeInterval) -> URLSession {
        URLSession(configuration: configuration(timeout: timeout),
                   delegate: RedirectRefuser(), delegateQueue: nil)
    }

    /// A copy of the request with the deadline as its own timeout. A URLRequest has
    /// a timeout of its own, 60 seconds when nobody sets it, and it could end a
    /// render of 300 seconds early whatever the session says.
    static func request(_ request: URLRequest, timeout: TimeInterval) -> URLRequest {
        var copy = request
        copy.timeoutInterval = timeout
        return copy
    }

    public func get(_ url: URL, timeout: TimeInterval) async throws -> (status: Int, body: Data) {
        let reply = try await send(URLRequest(url: url), timeout: timeout)
        return (reply.status, reply.body)
    }

    public func send(_ request: URLRequest, timeout: TimeInterval) async throws -> HTTPReply {
        let session = Self.session(timeout: timeout)
        defer { session.finishTasksAndInvalidate() }
        let (data, response) = try await session.data(for: Self.request(request, timeout: timeout))
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        return HTTPReply(status: http.statusCode,
                         contentType: http.value(forHTTPHeaderField: "Content-Type"),
                         body: data)
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

    public func run(_ executable: String, _ arguments: [String], cwd: String?,
                    environment: [String: String]?) throws -> ProcessResult {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        if let cwd { process.currentDirectoryURL = URL(fileURLWithPath: cwd) }
        // nil keeps the default of `Process`: the tool's own environment
        if let environment { process.environment = environment }
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

    /// A C copy of each text, for `posix_spawn`. The caller frees each copy.
    ///
    /// A copy that cannot be made fails the call, and the copies made before it
    /// are freed. A nil in the list would be the list's end for `posix_spawn`: the
    /// program would start with fewer arguments, or with a part of its environment.
    ///
    /// `copy` is `strdup`. A test gives another to model a machine with no memory left.
    static func cStrings(
        _ texts: [String], copy: (String) -> UnsafeMutablePointer<CChar>? = { strdup($0) }
    ) throws -> [UnsafeMutablePointer<CChar>?] {
        var copies: [UnsafeMutablePointer<CChar>?] = []
        for text in texts {
            guard let pointer = copy(text) else {
                copies.forEach { free($0) }
                throw TecopaFailure(.environment,
                                    "Could not start a program: no memory for its arguments or its environment.")
            }
            copies.append(pointer)
        }
        return copies
    }

    /// The real detached start, with `posix_spawn`. `Process` cannot make a new
    /// session, and a run must have one.
    ///
    /// - `POSIX_SPAWN_SETSID`: the child is the leader of a new session and of a
    ///   new process group. A closed terminal sends it no hang-up, and one signal
    ///   to the group reaches the child and each process under it.
    /// - `POSIX_SPAWN_CLOEXEC_DEFAULT`: the child gets descriptors 0, 1 and 2 and
    ///   no other, with or without a close-on-exec flag. Under `tecopa mcp` the
    ///   tool's own descriptors carry the protocol.
    /// - All three are the null device. The caller's command sends its output
    ///   where it must go.
    /// - The signal mask is empty and each signal has its default action, so a
    ///   signal that the tool's parent ignored still ends the child.
    public func startDetached(_ executable: String, _ arguments: [String], cwd: String?,
                              environment: [String: String]) throws -> Int32 {
        // A C string ends at its first NUL byte, so the child would get another text.
        let texts = [executable] + arguments + environment.map { $0.key + "=" + $0.value } + [cwd ?? ""]
        guard !texts.contains(where: { $0.utf8.contains(0) }) else {
            throw TecopaFailure(.usage, "A command, an argument or an environment value cannot hold a NUL byte.")
        }
        func failure(_ code: Int32) -> TecopaFailure {
            TecopaFailure(.environment, "Could not start \(executable): \(String(cString: strerror(code)))")
        }
        // `posix_spawn` reports a working directory that is missing with the same
        // code as a program that is missing. The look here gives the true cause.
        if let cwd {
            switch Runtime.kindOfPath(cwd) {
            case .folder?: break
            case .file?: throw TecopaFailure(.environment, "The working directory \(cwd) is not a folder.")
            case nil: throw TecopaFailure(.environment, "The working directory \(cwd) does not exist.")
            }
        }

        var actions: posix_spawn_file_actions_t?
        var code = posix_spawn_file_actions_init(&actions)
        guard code == 0 else { throw failure(code) }
        defer { posix_spawn_file_actions_destroy(&actions) }
        var attributes: posix_spawnattr_t?
        code = posix_spawnattr_init(&attributes)
        guard code == 0 else { throw failure(code) }
        defer { posix_spawnattr_destroy(&attributes) }

        code = posix_spawn_file_actions_addopen(&actions, 0, "/dev/null", O_RDONLY, 0)
        if code == 0 { code = posix_spawn_file_actions_addopen(&actions, 1, "/dev/null", O_WRONLY, 0) }
        if code == 0 { code = posix_spawn_file_actions_addopen(&actions, 2, "/dev/null", O_WRONLY, 0) }
        if code == 0, let cwd { code = posix_spawn_file_actions_addchdir_np(&actions, cwd) }
        var none = sigset_t()
        sigemptyset(&none)
        if code == 0 { code = posix_spawnattr_setsigmask(&attributes, &none) }
        var every = sigset_t()
        sigfillset(&every)
        if code == 0 { code = posix_spawnattr_setsigdefault(&attributes, &every) }
        let flags = POSIX_SPAWN_SETSID | POSIX_SPAWN_CLOEXEC_DEFAULT | POSIX_SPAWN_SETSIGMASK
            | POSIX_SPAWN_SETSIGDEF
        if code == 0 { code = posix_spawnattr_setflags(&attributes, Int16(flags)) }
        guard code == 0 else { throw failure(code) }

        var argv = try Self.cStrings([executable] + arguments)
        defer { argv.forEach { free($0) } }
        var envp = try Self.cStrings(environment.map { $0.key + "=" + $0.value })
        defer { envp.forEach { free($0) } }
        argv.append(nil)
        envp.append(nil)
        var pid: pid_t = 0
        // no search of PATH: the caller names the program by its path
        code = posix_spawn(&pid, executable, &actions, &attributes, argv, envp)
        guard code == 0 else { throw failure(code) }

        // The child is the tool's own until the tool ends. A child that ends first
        // stays in the process table until its parent reads its status, and under
        // `tecopa mcp` the tool can live for days. One thread waits for the child
        // and does nothing more. When the tool ends first, launchd takes the child.
        Thread.detachNewThread {
            var status: Int32 = 0
            while waitpid(pid, &status, 0) == -1, errno == EINTR {}
        }
        return pid
    }

    /// The real signal: `kill` with a negative id, which names a process group.
    ///
    /// Group 1 and group 0 are refused. `kill(-1)` signals every process of the
    /// user, and `kill(0)` signals the tool's own group.
    public func signalGroup(_ group: Int32, _ signal: Int32) throws {
        guard group > 1 else {
            throw TecopaFailure(.environment, "\(group) is not the process group of a run.")
        }
        guard kill(-group, signal) == 0 else {
            throw TecopaFailure(
                .environment,
                "Could not signal the process group \(group): \(String(cString: strerror(errno)))")
        }
    }
}
