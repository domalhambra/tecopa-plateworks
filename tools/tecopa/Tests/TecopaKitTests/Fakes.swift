import Foundation
@testable import TecopaKit

/// One fake machine for a test: an engine that answers some paths, a process runner
/// that records each command, and a few files. `onRun` lets a test change the engine
/// when a command runs, which is how "the launcher starts the engine" is modelled.
final class FakeWorld: HTTPFetching, ProcessRunning, @unchecked Sendable {
    private let lock = NSLock()
    private var routes: [String: (Int, String)] = [:]
    private var results: [String: ProcessResult] = [:]
    private var timeouts: Set<String> = []
    private var files: [String: String] = [:]
    private var launcherProcess: Bool?
    private(set) var commands: [[String]] = []
    /// The working directory of each command, in the order of `commands`.
    private(set) var workingDirectories: [String?] = []
    /// Every URL a test asked for, served or not.
    private(set) var requests: [URL] = []
    var onRun: ((FakeWorld, [String]) -> Void)?

    /// `path` includes the query, for example "/api/debug/sessions/ab?full=1".
    func serve(_ path: String, _ status: Int, _ body: String) {
        lock.lock(); routes[path] = (status, body); lock.unlock()
    }

    /// After this, a request for `path` gets no answer in time: an engine that
    /// listens and is busy.
    func timeOut(_ path: String) {
        lock.lock(); timeouts.insert(path); lock.unlock()
    }

    func stopServing() {
        lock.lock(); routes.removeAll(); timeouts.removeAll(); lock.unlock()
    }

    /// The result for any command whose executable ends with `name`.
    func result(for name: String, _ result: ProcessResult) {
        lock.lock(); results[name] = result; lock.unlock()
    }

    /// Does the launcher process exist? When this is set, `pgrep` exits 0 or 1 to
    /// match it, unless a test gave pgrep its own `result(for:)`. nil, the default,
    /// does not model the process: pgrep then exits 0 like any other command.
    var launcherRunning: Bool? {
        get { lock.withLock { launcherProcess } }
        set { lock.withLock { launcherProcess = newValue } }
    }

    /// The text `Runtime.readFile` returns for `path`. Any other path reads as nil.
    func file(_ path: String, _ contents: String) {
        lock.lock(); files[path] = contents; lock.unlock()
    }

    func get(_ url: URL, timeout: TimeInterval) async throws -> (status: Int, body: Data) {
        let key = url.path + (url.query.map { "?" + $0 } ?? "")
        let (slow, route) = lock.withLock {
            requests.append(url)
            return (timeouts.contains(key), routes[key])
        }
        if slow { throw URLError(.timedOut) }
        guard let route else { throw URLError(.cannotConnectToHost) }
        return (route.0, Data(route.1.utf8))
    }

    func run(_ executable: String, _ arguments: [String], cwd: String?) throws -> ProcessResult {
        let command = [executable] + arguments
        lock.lock()
        commands.append(command)
        workingDirectories.append(cwd)
        let name = (executable as NSString).lastPathComponent
        var result = results[name] ?? ProcessResult(exitCode: 0, stdout: "", stderr: "")
        if name == "pgrep", results[name] == nil, let launcherProcess {
            result = ProcessResult(exitCode: launcherProcess ? 0 : 1, stdout: "", stderr: "")
        }
        lock.unlock()
        onRun?(self, command)
        return result
    }

    static let readyBody = #"{"ready":true,"regions":[{"id":"lassen_ca","ready":true}]}"#

    func runtime(port: Int = 8848, repo: String? = "/repo", home: String = "/home") -> Runtime {
        Runtime(repoFlag: repo, port: port, environment: [:], home: home,
                http: self, runner: self,
                fileExists: { _ in true },
                sleep: { _ in },
                readFile: { path in self.lock.withLock { self.files[path] } })
    }
}
