import XCTest
@testable import TecopaKit

/// The real seams: the process runner with programs that every Mac has, the HTTP
/// client against a listener on 127.0.0.1, and the file calls in a temporary folder.
/// No test here goes past this machine.
final class SeamsTests: XCTestCase {
    func testBothPipesDrainPast64K() throws {
        // a pipe holds 64 KB: a runner that reads one pipe at a time blocks for ever
        let result = try SystemProcessRunner().run(
            "/bin/sh", ["-c", "head -c 200000 /dev/zero; head -c 200000 /dev/zero >&2"], cwd: nil)
        XCTAssertEqual(result.exitCode, 0)
        XCTAssertEqual(result.stdout.utf8.count, 200_000)
        XCTAssertEqual(result.stderr.utf8.count, 200_000)
    }

    func testStdinIsTheNullDevice() throws {
        // with the tool's own stdin, cat would wait for the terminal or the MCP client
        let result = try SystemProcessRunner(timeout: 5).run("/bin/cat", [], cwd: nil)
        XCTAssertEqual(result, ProcessResult(exitCode: 0, stdout: "", stderr: ""))
    }

    func testAMissingExecutableIsAnEnvironmentFailure() {
        XCTAssertThrowsError(try Runtime().exec("/no/such/program", [])) { error in
            let failure = error as? TecopaFailure
            XCTAssertEqual(failure?.kind, .environment)
            XCTAssertTrue(failure?.message.contains("/no/such/program") ?? false)
        }
    }

    func testAChildPastTheDeadlineIsTerminated() {
        let start = Date()
        XCTAssertThrowsError(try SystemProcessRunner(timeout: 0.5).run("/bin/sleep", ["30"], cwd: nil)) { error in
            let failure = error as? TecopaFailure
            XCTAssertEqual(failure?.kind, .environment)
            XCTAssertEqual(failure?.message, "sleep did not finish within 0.5 seconds.")
        }
        XCTAssertLessThan(Date().timeIntervalSince(start), 2)
    }

    func testAChildThatIgnoresTheTerminationSignalIsKilled() {
        let start = Date()
        XCTAssertThrowsError(try SystemProcessRunner(timeout: 0.5).run(
            "/bin/sh", ["-c", "trap '' TERM; while :; do sleep 1; done"], cwd: nil)) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
        XCTAssertLessThan(Date().timeIntervalSince(start), 6)
    }

    func testAChildEndedByASignalReports128PlusTheSignal() throws {
        // SIGTERM is 15. A plain 15 would read as the child's own exit code.
        let result = try SystemProcessRunner().run("/bin/sh", ["-c", "kill -TERM $$"], cwd: nil)
        XCTAssertEqual(result.exitCode, 143)
        let plain = try SystemProcessRunner().run("/bin/sh", ["-c", "exit 15"], cwd: nil)
        XCTAssertEqual(plain.exitCode, 15)
    }

    func testTheDeadlineMessageHasNoTrailingZero() {
        XCTAssertEqual(secondsText(300), "300")
        XCTAssertEqual(secondsText(0.5), "0.5")
    }

    // MARK: The HTTP client

    func testGetReturnsARedirectAndDoesNotFollowIt() async throws {
        let server = try LoopbackServer()
        defer { server.stop() }
        let reply = try await URLSessionFetcher().get(server.url("/redirect/302"), timeout: 5)
        XCTAssertEqual(reply.status, 302)
        // a followed redirect would be a second line, "GET /followed HTTP/1.1"
        XCTAssertEqual(server.requestLines, ["GET /redirect/302 HTTP/1.1"])
    }

    func testSendReturnsARedirectAndDoesNotFollowIt() async throws {
        // a 307 and a 308 would carry the POST and its body to the new address
        let table = [("GET", 301), ("GET", 302), ("GET", 307), ("POST", 301), ("POST", 302),
                     ("POST", 303), ("POST", 307), ("POST", 308)]
        for (method, status) in table {
            let server = try LoopbackServer()
            defer { server.stop() }
            var request = URLRequest(url: server.url("/redirect/\(status)"))
            request.httpMethod = method
            if method == "POST" { request.httpBody = Data("the form".utf8) }
            let reply = try await URLSessionFetcher().send(request, timeout: 5)
            XCTAssertEqual(reply.status, status, "\(method) \(status)")
            XCTAssertEqual(server.requestLines, ["\(method) /redirect/\(status) HTTP/1.1"])
        }
    }

    func testSendCarriesTheBodyAndReturnsTheContentType() async throws {
        let server = try LoopbackServer()
        defer { server.stop() }
        var form = Multipart(boundary: "XX")
        try form.field("title", "Lassen")
        try form.file("files", filename: "a.gpx", Data(repeating: 0x41, count: 100_000))
        var request = URLRequest(url: server.url("/api/upload"))
        request.httpMethod = "POST"
        request.setValue(form.contentType, forHTTPHeaderField: "Content-Type")
        request.httpBody = form.body()

        let reply = try await URLSessionFetcher().send(request, timeout: 5)
        XCTAssertEqual(reply.status, 200)
        XCTAssertEqual(reply.contentType, "text/plain; charset=utf-8")
        // the listener answers with what it read
        XCTAssertEqual(String(decoding: reply.body, as: UTF8.self),
                       "POST /api/upload \(form.body().count) multipart/form-data; boundary=XX")

        let fetched = try await URLSessionFetcher().get(server.url("/readyz"), timeout: 5)
        XCTAssertEqual(fetched.status, 200)
        XCTAssertEqual(String(decoding: fetched.body, as: UTF8.self), "GET /readyz 0 ")
    }

    func testSendTimesOutAtItsOwnDeadline() async throws {
        // a listener that takes the request and never answers: an engine that is busy
        let server = try LoopbackServer()
        defer { server.stop() }
        // This test cannot hang. If the deadline does not hold, the listener closes
        // the connection after 5 seconds, and that error is not a timeout.
        DispatchQueue.global().asyncAfter(deadline: .now() + 5) { server.stop() }
        let start = Date()
        do {
            _ = try await URLSessionFetcher().send(URLRequest(url: server.url("/silent")), timeout: 0.5)
            XCTFail("expected a timeout")
        } catch {
            XCTAssertEqual((error as? URLError)?.code, .timedOut, "\(error)")
        }
        XCTAssertLessThan(Date().timeIntervalSince(start), 3)
        XCTAssertEqual(server.requestLines, ["GET /silent HTTP/1.1"])
    }

    func testTheRequestCarriesTheDeadlineAsItsOwnTimeout() throws {
        // a URLRequest has a timeout of its own, 60 seconds when it is not set, and
        // a render waits 300
        var request = URLRequest(url: URL(string: "http://127.0.0.1:8848/api/proof")!)
        request.httpMethod = "POST"
        request.httpBody = Data("the form".utf8)
        request.setValue("multipart/form-data; boundary=XX", forHTTPHeaderField: "Content-Type")
        XCTAssertEqual(request.timeoutInterval, 60)

        let sent = URLSessionFetcher.request(request, timeout: 300)
        XCTAssertEqual(sent.timeoutInterval, 300)
        XCTAssertEqual(URLSessionFetcher.request(request, timeout: 0.5).timeoutInterval, 0.5)
        // nothing else changes, and the caller's request is not touched
        XCTAssertEqual(sent.url, request.url)
        XCTAssertEqual(sent.httpMethod, "POST")
        XCTAssertEqual(sent.httpBody, Data("the form".utf8))
        XCTAssertEqual(sent.value(forHTTPHeaderField: "Content-Type"), "multipart/form-data; boundary=XX")
        XCTAssertEqual(request.timeoutInterval, 60)
    }

    func testNoAnswerThrows() async throws {
        // the port of a listener that is gone
        let server = try LoopbackServer()
        let url = server.url("/readyz")
        server.stop()
        server.waitUntilClosed()
        do {
            _ = try await URLSessionFetcher().send(URLRequest(url: url), timeout: 5)
            XCTFail("expected no answer")
        } catch {
            XCTAssertNotEqual((error as? URLError)?.code, .timedOut)
        }
    }

    func testEverySessionUsesNoProxyAndTheGivenTimeout() {
        // `get` and `send` have this one configuration and no other
        let config = URLSessionFetcher.configuration(timeout: 7)
        XCTAssertEqual(config.connectionProxyDictionary?.isEmpty, true)
        XCTAssertEqual(config.timeoutIntervalForRequest, 7)
        XCTAssertEqual(config.timeoutIntervalForResource, 7)
    }

    // MARK: Files

    /// A new folder in the system's temporary folder. The test removes it at its end.
    private func temporaryFolder() throws -> String {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("tecopa-seams-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url.path
    }

    func testWriteNewWritesTheBytesOfANewFile() throws {
        let path = try temporaryFolder() + "/proof.png"
        let bytes = Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x00, 0xFF])
        try Runtime().writeNew(path, bytes)
        XCTAssertEqual(FileManager.default.contents(atPath: path), bytes)
        XCTAssertEqual(Runtime().readData(path), bytes)

        // no bytes is still a file
        let empty = (path as NSString).deletingLastPathComponent + "/empty.bin"
        try Runtime().writeNew(empty, Data())
        XCTAssertEqual(FileManager.default.contents(atPath: empty), Data())
    }

    func testWriteNewNeverOverwrites() throws {
        let path = try temporaryFolder() + "/poster.png"
        let first = Data("the first poster".utf8)
        try first.write(to: URL(fileURLWithPath: path))
        XCTAssertThrowsError(try Runtime().writeNew(path, Data("another".utf8))) { error in
            let failure = error as? TecopaFailure
            XCTAssertEqual(failure?.kind, .usage)
            XCTAssertEqual(failure?.message, "A file is already at \(path).")
        }
        XCTAssertEqual(FileManager.default.contents(atPath: path), first)
        // the same for a second call of the tool itself
        let own = (path as NSString).deletingLastPathComponent + "/own.png"
        try Runtime().writeNew(own, first)
        XCTAssertThrowsError(try Runtime().writeNew(own, Data()))
        XCTAssertEqual(FileManager.default.contents(atPath: own), first)
    }

    func testWriteNewDoesNotWriteThroughALink() throws {
        // a link at the path is a file at the path, even when it points at nothing
        let folder = try temporaryFolder()
        let target = folder + "/target.png"
        let link = folder + "/link.png"
        try FileManager.default.createSymbolicLink(atPath: link, withDestinationPath: target)
        XCTAssertThrowsError(try Runtime().writeNew(link, Data([1, 2, 3]))) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .usage)
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: target))
    }

    func testWriteNewNamesAMissingFolder() throws {
        let folder = try temporaryFolder() + "/none"
        XCTAssertThrowsError(try Runtime().writeNew(folder + "/proof.png", Data([1]))) { error in
            let failure = error as? TecopaFailure
            XCTAssertEqual(failure?.kind, .usage)
            XCTAssertEqual(failure?.message, "The folder \(folder) does not exist.")
        }
        // the tool makes no folder
        XCTAssertFalse(FileManager.default.fileExists(atPath: folder))
    }

    func testAFailedWriteLeavesNoFile() throws {
        let path = try temporaryFolder() + "/final.png"
        XCTAssertThrowsError(try writeExclusive(path, Data([1, 2, 3]), write: { _, _, _ in
            errno = ENOSPC
            return -1
        })) { error in
            let failure = error as? TecopaFailure
            XCTAssertEqual(failure?.kind, .environment)
            XCTAssertTrue(failure?.message.hasPrefix("Could not write \(path): ") ?? false,
                          failure?.message ?? "")
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: path))
    }

    func testAShortWriteIsContinued() throws {
        // the system may take fewer bytes than it was given
        let path = try temporaryFolder() + "/film.mp4"
        let bytes = Data((0..<1000).map { UInt8($0 % 251) })
        try writeExclusive(path, bytes, write: { fd, pointer, count in
            Darwin.write(fd, pointer, min(count, 7))
        })
        XCTAssertEqual(FileManager.default.contents(atPath: path), bytes)
    }

    func testAWriteThatTakesNoBytesIsAnErrorAndNotALoop() throws {
        // a call that returns 0 for ever would keep the tool in the loop for ever
        let path = try temporaryFolder() + "/final.png"
        var calls = 0
        XCTAssertThrowsError(try writeExclusive(path, Data([1, 2, 3]), write: { _, _, _ in
            calls += 1
            return 0
        })) { error in
            let failure = error as? TecopaFailure
            XCTAssertEqual(failure?.kind, .environment)
            XCTAssertEqual(failure?.message,
                           "Could not write \(path): \(String(cString: strerror(EIO)))")
        }
        XCTAssertEqual(calls, 1)
        XCTAssertFalse(FileManager.default.fileExists(atPath: path))
    }

    func testTheNewFileIsClosedInAChildProcess() throws {
        // the tool starts scripts, and a child must not get a file that is part-written
        let path = try temporaryFolder() + "/proof.png"
        var flags: Int32 = 0
        try writeExclusive(path, Data([1, 2, 3]), write: { fd, pointer, count in
            flags = fcntl(fd, F_GETFD)
            return Darwin.write(fd, pointer, count)
        })
        XCTAssertNotEqual(flags & FD_CLOEXEC, 0)
    }

    func testReadDataIsNilForAPathThatCannotBeRead() throws {
        let folder = try temporaryFolder()
        XCTAssertNil(Runtime().readData(folder + "/none.gpx"))
        XCTAssertNil(Runtime().readData(folder))
    }

    func testReadTailReadsTheEndOfAFile() throws {
        let folder = try temporaryFolder()
        let file = folder + "/run.log"
        try Data("0123456789".utf8).write(to: URL(fileURLWithPath: file))
        XCTAssertEqual(Runtime().readTail(file, 4), Data("6789".utf8))
        XCTAssertEqual(Runtime().readTail(file, 10), Data("0123456789".utf8))
        XCTAssertEqual(Runtime().readTail(file, 11), Data("0123456789".utf8))
        XCTAssertEqual(Runtime().readTail(file, 1 << 30), Data("0123456789".utf8))
        XCTAssertEqual(Runtime().readTail(file, 0), Data())
        XCTAssertEqual(Runtime().readTail(file, -3), Data())
        // an empty file is a file, and a missing file or a folder is not
        try Runtime().writeNew(folder + "/empty.log", Data())
        XCTAssertEqual(Runtime().readTail(folder + "/empty.log", 4), Data())
        XCTAssertNil(Runtime().readTail(folder + "/none.log", 4))
        XCTAssertNil(Runtime().readTail(folder, 4))

        // 3 MB, of which only the end is read
        let big = folder + "/big.log"
        let line = Data((String(repeating: "x", count: 1023) + "\n").utf8)
        var bytes = Data()
        for _ in 0..<(3 * 1024) { bytes.append(line) }
        bytes.append(Data("the end\n".utf8))
        try bytes.write(to: URL(fileURLWithPath: big))
        let tail = try XCTUnwrap(Runtime().readTail(big, 1 << 20))
        XCTAssertEqual(tail.count, 1 << 20)
        XCTAssertEqual(tail, bytes.suffix(1 << 20))
    }

    func testAProgramGetsTheEnvironmentItIsGivenOrTheToolsOwn() throws {
        let given = try SystemProcessRunner().run("/usr/bin/env", [], cwd: nil,
                                                  environment: ["TECOPA_TEST_VALUE": "given", "A": "1"])
        XCTAssertEqual(Set(given.stdout.split(separator: "\n").map(String.init)), ["TECOPA_TEST_VALUE=given", "A=1"])
        // with none given, the program has the variables of this process
        setenv("TECOPA_TEST_INHERITED", "from the tool", 1)
        defer { unsetenv("TECOPA_TEST_INHERITED") }
        let own = try SystemProcessRunner().run("/usr/bin/env", [], cwd: nil)
        XCTAssertTrue(own.stdout.contains("TECOPA_TEST_INHERITED=from the tool\n"), own.stdout)
        let viaRuntime = try Runtime().exec("/usr/bin/env", [], environment: ["B": "2"])
        XCTAssertEqual(viaRuntime.stdout, "B=2\n")
    }

    func testACCopyThatCannotBeMadeFailsTheStart() throws {
        // a nil in the list is the list's end: the program would get fewer arguments
        var asked: [String] = []
        XCTAssertThrowsError(try SystemProcessRunner.cStrings(["/bin/sh", "-c", "exit 0", "x"], copy: { text in
            asked.append(text)
            return text == "exit 0" ? nil : strdup(text)
        })) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .environment)
        }
        // it stops at the first copy that fails
        XCTAssertEqual(asked, ["/bin/sh", "-c", "exit 0"])

        let copies = try SystemProcessRunner.cStrings(["/bin/sh", "a b", ""])
        defer { copies.forEach { free($0) } }
        XCTAssertEqual(copies.map { $0.map { String(cString: $0) } }, ["/bin/sh", "a b", ""])
        XCTAssertEqual(try SystemProcessRunner.cStrings([]).count, 0)
    }

    func testTheFakeKeepsBinaryFilesAndRecordsEachWrite() throws {
        let world = FakeWorld()
        world.binary("/tracks/a.kmz", Data([0x50, 0x4B, 0x00, 0xFF]))
        world.file("/tracks/b.gpx", "<gpx/>")
        world.existingFile("/out/old.png")
        let runtime = world.runtime()
        XCTAssertEqual(runtime.readData("/tracks/a.kmz"), Data([0x50, 0x4B, 0x00, 0xFF]))
        XCTAssertEqual(runtime.readData("/tracks/b.gpx"), Data("<gpx/>".utf8))
        XCTAssertNil(runtime.readData("/tracks/none.gpx"))

        try runtime.writeNew("/out/proof.png", Data([9, 8]))
        // the fake refuses with the real failure
        for path in ["/out/proof.png", "/out/old.png"] {
            XCTAssertThrowsError(try runtime.writeNew(path, Data([7]))) { error in
                XCTAssertEqual(error as? TecopaFailure,
                               TecopaFailure(.usage, "A file is already at \(path)."))
            }
        }
        XCTAssertEqual(world.written, [FakeWorld.Written(path: "/out/proof.png", data: Data([9, 8]))])
    }

    func testPathKindTellsAFileAFolderAndNothing() throws {
        let folder = try temporaryFolder()
        let file = folder + "/poster.png"
        try Data([1]).write(to: URL(fileURLWithPath: file))
        XCTAssertEqual(Runtime().pathKind(folder), .folder)
        XCTAssertEqual(Runtime().pathKind(file), .file)
        XCTAssertNil(Runtime().pathKind(folder + "/none.png"))
        XCTAssertNil(Runtime().pathKind(file + "/under-a-file.png"))
    }

    func testPathKindSeesALinkAsWriteNewDoes() throws {
        // `writeNew` refuses a link that points at nothing, so the early look must
        // report it. A link to a folder is a folder: a file can be made in it.
        let folder = try temporaryFolder()
        let dangling = folder + "/dangling.png"
        try FileManager.default.createSymbolicLink(atPath: dangling,
                                                   withDestinationPath: folder + "/none.png")
        XCTAssertEqual(Runtime().pathKind(dangling), .file)
        XCTAssertThrowsError(try Runtime().writeNew(dangling, Data([1])))

        let alias = folder + "/alias"
        try FileManager.default.createSymbolicLink(atPath: alias, withDestinationPath: folder)
        XCTAssertEqual(Runtime().pathKind(alias), .folder)
        try Runtime().writeNew(alias + "/proof.png", Data([1]))
    }

    func testTheFakeAnswersPathKindForEachPath() throws {
        let world = FakeWorld()
        world.folder("/out")
        world.existingFile("/out/old.png")
        let runtime = world.runtime()
        XCTAssertEqual(runtime.pathKind("/out"), .folder)
        XCTAssertEqual(runtime.pathKind("/out/old.png"), .file)
        XCTAssertNil(runtime.pathKind("/out/new.png"))
        XCTAssertNil(runtime.pathKind("/none"))
        // a write makes a file, and the phase 1 seam still says yes to every path
        try runtime.writeNew("/out/new.png", Data([1]))
        XCTAssertEqual(runtime.pathKind("/out/new.png"), .file)
        XCTAssertTrue(runtime.fileExists("/none"))
    }

    func testTheFakeAnswersASequenceAndCountsEachSleep() async throws {
        let world = FakeWorld()
        world.serve("/api/jobs/ab", 200, #"{"state":"fixed"}"#)
        world.serveSequence("GET /api/jobs/ab", [
            (200, #"{"state":"queued"}"#), (200, #"{"state":"running"}"#), (200, #"{"state":"done"}"#),
        ])
        let runtime = world.runtime()
        var states: [String] = []
        for _ in 0..<5 {
            states.append(try await runtime.client.get("/api/jobs/ab")["state"]?.stringValue ?? "")
            await runtime.sleep(1.5)
        }
        // the last answer repeats, and the sequence answers before the fixed route
        XCTAssertEqual(states, ["queued", "running", "done", "done", "done"])
        XCTAssertEqual(world.slept, [1.5, 1.5, 1.5, 1.5, 1.5])
        XCTAssertEqual(world.clock, 7.5)
    }
}

/// One listener on 127.0.0.1, on a port that the system picks. `/redirect/<status>`
/// answers that status with a Location on this same listener, so a followed redirect
/// shows as a second request line. `/silent` reads the request and never answers:
/// the connection stays open until `stop()`. Any other path answers 200 with what
/// was read: the method, the path, the count of body bytes and the content type.
private final class LoopbackServer: @unchecked Sendable {
    let port: Int
    private let listener: Int32
    private let lock = NSLock()
    private var lines: [String] = []
    private var stopped = false
    private let closed = DispatchSemaphore(value: 0)

    init() throws {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { throw POSIXError(.EIO) }
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = 0                                  // the system picks
        address.sin_addr.s_addr = inet_addr("127.0.0.1")      // never another interface
        var size = socklen_t(MemoryLayout<sockaddr_in>.size)
        let bound = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(fd, $0, size) }
        }
        let named = withUnsafeMutablePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(fd, $0, &size) }
        }
        guard bound == 0, named == 0, listen(fd, 8) == 0 else {
            close(fd)
            throw POSIXError(.EADDRNOTAVAIL)
        }
        listener = fd
        port = Int(UInt16(bigEndian: address.sin_port))
        Thread.detachNewThread { [self] in serve() }
    }

    func url(_ path: String) -> URL { URL(string: "http://127.0.0.1:\(port)\(path)")! }

    var requestLines: [String] { lock.withLock { lines } }

    func stop() { lock.withLock { stopped = true } }

    /// Returns when the port is free again.
    func waitUntilClosed() { closed.wait() }

    private func serve() {
        // the connections of `/silent`, open until the listener stops
        var silent: [Int32] = []
        while !lock.withLock({ stopped }) {
            var waiting = pollfd(fd: listener, events: Int16(POLLIN), revents: 0)
            guard poll(&waiting, 1, 20) > 0 else { continue }
            let client = accept(listener, nil, nil)
            guard client >= 0 else { continue }
            if answer(client) {
                close(client)
            } else {
                silent.append(client)
            }
        }
        for client in silent { close(client) }
        close(listener)
        closed.signal()
    }

    /// Read one request and answer it. False means no answer: the caller keeps the
    /// connection open.
    private func answer(_ client: Int32) -> Bool {
        var on: Int32 = 1
        setsockopt(client, SOL_SOCKET, SO_NOSIGPIPE, &on, socklen_t(MemoryLayout<Int32>.size))
        var limit = timeval(tv_sec: 5, tv_usec: 0)
        setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &limit, socklen_t(MemoryLayout<timeval>.size))

        // Read the head, then the body that Content-Length names.
        var received = Data()
        var buffer = [UInt8](repeating: 0, count: 65536)
        var head: String?
        var bodyStart = 0
        var bodyLength = 0
        while head == nil || received.count - bodyStart < bodyLength {
            let count = recv(client, &buffer, buffer.count, 0)
            guard count > 0 else { break }
            received.append(buffer, count: count)
            if head == nil, let gap = received.range(of: Data("\r\n\r\n".utf8)) {
                let text = String(decoding: received[..<gap.lowerBound], as: UTF8.self)
                head = text
                bodyStart = gap.upperBound
                bodyLength = Int(Self.header("content-length", in: text)) ?? 0
            }
        }
        guard let head else { return true }
        let line = head.components(separatedBy: "\r\n").first ?? ""
        lock.withLock { lines.append(line) }

        let words = line.components(separatedBy: " ")
        let (method, path) = (words.first ?? "", words.count > 1 ? words[1] : "")
        if path == "/silent" { return false }
        var reply: String
        if path.hasPrefix("/redirect/"), let status = Int(path.dropFirst("/redirect/".count)) {
            reply = "HTTP/1.1 \(status) Redirect\r\nLocation: http://127.0.0.1:\(port)/followed\r\n"
                + "Content-Length: 0\r\nConnection: close\r\n\r\n"
        } else {
            let body = "\(method) \(path) \(received.count - bodyStart) \(Self.header("content-type", in: head))"
            reply = "HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\n"
                + "Content-Length: \(body.utf8.count)\r\nConnection: close\r\n\r\n" + body
        }
        var bytes = Array(reply.utf8)
        while !bytes.isEmpty {
            let sent = Darwin.send(client, bytes, bytes.count, 0)
            guard sent > 0 else { return true }
            bytes.removeFirst(sent)
        }
        return true
    }

    /// The value of one request header, or "" when the head has none.
    private static func header(_ name: String, in head: String) -> String {
        for line in head.components(separatedBy: "\r\n").dropFirst() {
            let parts = line.split(separator: ":", maxSplits: 1).map(String.init)
            if parts.count == 2, parts[0].lowercased() == name {
                return parts[1].trimmingCharacters(in: .whitespaces)
            }
        }
        return ""
    }
}
