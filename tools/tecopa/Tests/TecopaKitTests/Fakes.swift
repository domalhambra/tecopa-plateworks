import Foundation
@testable import TecopaKit

/// One fake machine for a test: an engine that answers some paths, a process runner
/// that records each command, a few files, and a clock that counts each sleep.
/// `onRun` lets a test change the engine when a command runs, which is how "the
/// launcher starts the engine" is modelled.
final class FakeWorld: HTTPFetching, ProcessRunning, @unchecked Sendable {
    /// One multipart POST, as an engine would read it from the request's bytes.
    struct Post: Equatable {
        struct Field: Equatable {
            let name: String
            let value: String
        }

        struct File: Equatable {
            let name: String
            let filename: String
            let bytes: Int
        }

        /// The path with its query.
        let path: String
        /// In the order sent.
        let fields: [Field]
        /// In the order sent.
        let files: [File]

        /// The fields as "name=value", in the order sent.
        var pairs: [String] { fields.map { $0.name + "=" + $0.value } }
    }

    /// One call of `Runtime.writeNew`.
    struct Written: Equatable {
        let path: String
        let data: Data
    }

    private struct Route {
        let status: Int
        /// nil is a reply with no Content-Type header.
        let contentType: String?
        let body: Data
    }

    /// One step of `serveSteps`: what one request finds.
    enum Step {
        /// A JSON answer with this status.
        case answer(Int, String)
        /// No answer in time: the engine listens and is busy.
        case timedOut
        /// Nothing listens: the engine stopped.
        case noAnswer
    }

    private enum Outcome {
        case route(Route)
        case timedOut
        case noAnswer
    }

    private let lock = NSLock()
    private var routes: [String: Route] = [:]
    private var sequences: [String: [Outcome]] = [:]
    private var results: [String: ProcessResult] = [:]
    private var timeouts: Set<String> = []
    private var files: [String: String] = [:]
    private var binaries: [String: Data] = [:]
    private var taken: Set<String> = []
    private var folders: Set<String> = []
    private var launcherProcess: Bool?
    private(set) var commands: [[String]] = []
    /// The working directory of each command, in the order of `commands`.
    private(set) var workingDirectories: [String?] = []
    /// Every URL a test asked for, served or not.
    private(set) var requests: [URL] = []
    /// Every request as "METHOD path", in order, served or not: "POST /api/upload".
    private(set) var calls: [String] = []
    /// Every POST, in order, served or not.
    private(set) var posts: [Post] = []
    /// Every file that `Runtime.writeNew` wrote, in order.
    private(set) var written: [Written] = []
    /// The seconds of each `Runtime.sleep`, in order. No time passes in a test.
    private(set) var slept: [Double] = []
    /// The fake clock: the sum of every sleep, in seconds.
    var clock: Double { lock.withLock { slept.reduce(0, +) } }
    var onRun: ((FakeWorld, [String]) -> Void)?

    /// `path` includes the query, for example "/api/debug/sessions/ab?full=1". A
    /// bare path, or "GET " and a path, answers a GET. "POST /api/upload" answers a
    /// POST. `send` reports the body as JSON when it is JSON, and as text when not.
    func serve(_ path: String, _ status: Int, _ body: String) {
        let data = Data(body.utf8)
        let isJSON = (try? JSONValue.parse(data)) != nil
        serveData(path, status, isJSON ? "application/json" : "text/plain; charset=utf-8", data)
    }

    /// An answer that is bytes: a proof PNG, or a finished job's file. `key` is
    /// "GET /path" or "POST /path". A nil content type is a reply without the header.
    func serveData(_ key: String, _ status: Int, _ contentType: String?, _ data: Data) {
        lock.lock()
        routes[key] = Route(status: status, contentType: contentType, body: data)
        lock.unlock()
    }

    /// Answers that change with each request: a job that runs and then ends. Each
    /// request takes the next answer, and the last one repeats. The keys are those
    /// of `serve`, and a sequence answers before a fixed route of the same key.
    func serveSequence(_ key: String, _ answers: [(status: Int, body: String)]) {
        serveSteps(key, answers.map { .answer($0.status, $0.body) })
    }

    /// A sequence in which a request can also get no answer: a poll that times out
    /// while the engine paints, or an engine that stops while a job runs. The rules
    /// are those of `serveSequence`.
    func serveSteps(_ key: String, _ steps: [Step]) {
        let list: [Outcome] = steps.map {
            switch $0 {
            case .answer(let status, let body):
                return .route(Route(status: status, contentType: "application/json", body: Data(body.utf8)))
            case .timedOut: return .timedOut
            case .noAnswer: return .noAnswer
            }
        }
        lock.lock(); sequences[key] = list; lock.unlock()
    }

    /// After this, a request for `path` gets no answer in time: an engine that
    /// listens and is busy. The keys are those of `serve`.
    func timeOut(_ path: String) {
        lock.lock(); timeouts.insert(path); lock.unlock()
    }

    func stopServing() {
        lock.lock(); routes.removeAll(); sequences.removeAll(); timeouts.removeAll(); lock.unlock()
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

    /// The bytes `Runtime.readData` returns for `path`: a track or a poster.
    func binary(_ path: String, _ data: Data) {
        lock.lock(); binaries[path] = data; lock.unlock()
    }

    /// After this, `Runtime.writeNew` refuses `path`: a file is already there.
    /// `Runtime.pathKind` reports it as a file.
    func existingFile(_ path: String) {
        lock.lock(); taken.insert(path); lock.unlock()
    }

    /// After this, `Runtime.pathKind` reports `path` as a folder. A path that is
    /// not a folder and holds no file reads as nothing, so a test names each folder
    /// that a command writes into.
    func folder(_ path: String) {
        lock.lock(); folders.insert(path); lock.unlock()
    }

    func get(_ url: URL, timeout: TimeInterval) async throws -> (status: Int, body: Data) {
        let route = try answer("GET", url, post: nil)
        return (route.status, route.body)
    }

    func send(_ request: URLRequest, timeout: TimeInterval) async throws -> HTTPReply {
        guard let url = request.url else { throw URLError(.badURL) }
        let method = request.httpMethod ?? "GET"
        let post = method == "POST" ? Self.read(request, path: Self.key(url)) : nil
        let route = try answer(method, url, post: post)
        return HTTPReply(status: route.status, contentType: route.contentType, body: route.body)
    }

    private static func key(_ url: URL) -> String {
        url.path + (url.query.map { "?" + $0 } ?? "")
    }

    /// Record one request and find its route. A GET reads "GET /path" and then the
    /// bare path, so the phase 1 keys still answer. Any other method reads its own key.
    private func answer(_ method: String, _ url: URL, post: Post?) throws -> Route {
        let path = Self.key(url)
        let keys = method == "GET" ? ["GET " + path, path] : [method + " " + path]
        let outcome: Outcome = lock.withLock {
            requests.append(url)
            calls.append(method + " " + path)
            if let post { posts.append(post) }
            return keys.contains(where: timeouts.contains) ? .timedOut : next(keys)
        }
        switch outcome {
        case .route(let route): return route
        case .timedOut: throw URLError(.timedOut)
        case .noAnswer: throw URLError(.cannotConnectToHost)
        }
    }

    /// The answer for the first key that has one, or no answer when none has. A
    /// sequence gives its next step and keeps its last. The caller holds the lock.
    private func next(_ keys: [String]) -> Outcome {
        for key in keys {
            if let list = sequences[key], let first = list.first {
                if list.count > 1 { sequences[key] = Array(list.dropFirst()) }
                return first
            }
            if let route = routes[key] { return .route(route) }
        }
        return .noAnswer
    }

    /// Read a multipart body back into its parts. The fake has its own reader, so a
    /// test sees what an engine would read, not what the encoder was given.
    private static func read(_ request: URLRequest, path: String) -> Post {
        var fields: [Post.Field] = []
        var files: [Post.File] = []
        if let type = request.value(forHTTPHeaderField: "Content-Type"),
           let mark = type.range(of: "boundary="), let body = request.httpBody {
            // Each part starts after "CRLF--boundary". A CRLF in front of the body
            // makes the first part the same as the others.
            let divider = Data(("\r\n--" + type[mark.upperBound...]).utf8)
            let blankLine = Data("\r\n\r\n".utf8)
            let data = Data("\r\n".utf8) + body
            var cursor = data.range(of: divider)?.upperBound ?? data.endIndex
            while let next = data.range(of: divider, in: cursor..<data.endIndex) {
                let part = data[cursor..<next.lowerBound]
                cursor = next.upperBound
                guard let gap = part.range(of: blankLine) else { continue }
                let named = parameters(String(decoding: part[..<gap.lowerBound], as: UTF8.self))
                let content = part[gap.upperBound...]
                if let filename = named["filename"] {
                    files.append(Post.File(name: named["name"] ?? "", filename: filename,
                                           bytes: content.count))
                } else {
                    fields.append(Post.Field(name: named["name"] ?? "",
                                             value: String(decoding: content, as: UTF8.self)))
                }
            }
        }
        return Post(path: path, fields: fields, files: files)
    }

    /// The quoted parameters of a part's Content-Disposition header: `name`, and
    /// `filename` for a file.
    private static func parameters(_ head: String) -> [String: String] {
        let line = head.components(separatedBy: "\r\n")
            .first { $0.lowercased().hasPrefix("content-disposition:") } ?? ""
        var found: [String: String] = [:]
        var rest = Substring(line)
        while let equals = rest.range(of: "=\"") {
            let key = rest[..<equals.lowerBound].split(separator: ";").last
                .map { $0.trimmingCharacters(in: .whitespaces) } ?? ""
            let after = rest[equals.upperBound...]
            guard let close = after.firstIndex(of: "\"") else { break }
            found[key] = String(after[..<close])
            rest = after[after.index(after: close)...]
        }
        return found
    }

    /// The fake `Runtime.writeNew`. It keeps the real rule: a path holds one file,
    /// and the second write to it is refused.
    private func write(_ path: String, _ data: Data) throws {
        try lock.withLock {
            guard !taken.contains(path) else { throw fileAlreadyThere(path) }
            taken.insert(path)
            written.append(Written(path: path, data: data))
        }
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
                sleep: { seconds in self.lock.withLock { self.slept.append(seconds) } },
                readFile: { path in self.lock.withLock { self.files[path] } },
                readData: { path in
                    self.lock.withLock { self.binaries[path] ?? self.files[path].map { Data($0.utf8) } }
                },
                writeNew: { path, data in try self.write(path, data) },
                pathKind: { path in
                    self.lock.withLock {
                        self.taken.contains(path) ? .file : self.folders.contains(path) ? .folder : nil
                    }
                })
    }
}
