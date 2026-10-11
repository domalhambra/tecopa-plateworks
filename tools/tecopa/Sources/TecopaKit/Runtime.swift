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
    /// The bytes of one file, or nil when it cannot be read.
    public var readData: @Sendable (String) -> Data?
    /// Write the bytes to a path that holds no file. A file at the path is a usage
    /// failure: the tool never overwrites.
    public var writeNew: @Sendable (String, Data) throws -> Void

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
        },
        readData: @escaping @Sendable (String) -> Data? = {
            try? Data(contentsOf: URL(fileURLWithPath: $0))
        },
        writeNew: @escaping @Sendable (String, Data) throws -> Void = {
            try Runtime.writeNewFile($0, $1)
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
        self.readData = readData
        self.writeNew = writeNew
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

/// The failure for a path that already holds a file. The real write and a test's
/// fake machine both throw this one value.
func fileAlreadyThere(_ path: String) -> TecopaFailure {
    TecopaFailure(.usage, "A file is already at \(path).")
}

extension Runtime {
    /// The real `writeNew`: create the file at `path` and write all the bytes to it.
    public static func writeNewFile(_ path: String, _ data: Data) throws {
        try TecopaKit.writeNewFile(path, data, write: { Darwin.write($0, $1, $2) })
    }
}

/// Create the file and write all the bytes to it.
///
/// `O_EXCL` makes the create fail when anything is at the path, a link included, so
/// the check and the create are one step and no other program can come between
/// them. There is no temporary file and no rename, because a rename replaces what
/// is at its target. If the write fails, the part-written file is removed: it is the
/// tool's own, made a moment before.
///
/// `write` is the system call. A test gives another to model a full disk.
func writeNewFile(_ path: String, _ data: Data,
                  write: (Int32, UnsafeRawPointer?, Int) -> Int) throws {
    let fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0o644)
    guard fd >= 0 else {
        let code = errno
        let folder = (path as NSString).deletingLastPathComponent
        switch code {
        case EEXIST:
            throw fileAlreadyThere(path)
        case ENOENT:
            throw TecopaFailure(.usage, "The folder \(folder) does not exist.")
        case ENOTDIR:
            throw TecopaFailure(.usage, "\(folder) is not a folder.")
        default:
            throw TecopaFailure(.environment,
                                "Could not create \(path): \(String(cString: strerror(code)))")
        }
    }

    // One call can take fewer bytes than it was given, so write until none is left.
    var failed: Int32?
    data.withUnsafeBytes { bytes in
        var offset = 0
        while offset < bytes.count {
            let count = write(fd, bytes.baseAddress.map { $0 + offset }, bytes.count - offset)
            if count < 0 {
                if errno == EINTR { continue }
                failed = errno
                return
            }
            offset += count
        }
    }
    // A close can report a write that the system held back.
    if close(fd) != 0, failed == nil, errno != EINTR { failed = errno }
    if let failed {
        unlink(path)
        throw TecopaFailure(.environment,
                            "Could not write \(path): \(String(cString: strerror(failed)))")
    }
}
