import XCTest
@testable import TecopaKit

final class RenderTests: XCTestCase {
    /// The proof the fake engine answers. Its SHA-256 is the standard test vector.
    private let png = Data("abc".utf8)
    private let pngSHA = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    /// The file of the finished job "cd34".
    private let poster = Data([0x89, 0x50, 0x4E, 0x47, 0x00, 0xFF, 0x0D, 0x0A, 0x1A])

    private let running = #"{"state":"running","error":null}"#
    private let done = #"{"state":"done","error":null,"result":"/api/jobs/cd34/result"}"#

    /// An engine with the gate open. An upload gives the session "ab12", each
    /// submit gives the job "cd34", and the job is done. The upload's answer has
    /// track geometry, which no result may hold.
    private func engine() -> FakeWorld {
        let world = FakeWorld()
        world.folder("/out")
        world.binary("/tracks/a.gpx", Data("<gpx>a</gpx>".utf8))
        world.binary("/tracks/b.kml", Data("<kml>bb</kml>".utf8))
        world.serve("POST /api/upload", 200,
                    #"{"session":"ab12","region":"lassen_ca","starter_crop":[10,20.5,110,150],"#
                        + #""tracks":[{"track_id":"t1","px":[[1,2],[3,4]]}]}"#)
        world.serveData("POST /api/proof", 200, "image/png", png)
        world.serve("POST /api/final/submit", 200, #"{"job":"cd34"}"#)
        world.serve("POST /api/wallpapers/submit", 200,
                    #"{"job":"cd34","count":1,"skipped":[{"preset":"watch","reason":"too small"}],"#
                        + #""fitted":[{"preset":"iphone","crop_growth":1.2}]}"#)
        world.serve("POST /api/timelapse/submit", 200, #"{"job":"cd34","frames":48}"#)
        world.serve("GET /api/jobs/cd34", 200, done)
        world.serveData("GET /api/jobs/cd34/result", 200, "image/png", poster)
        world.serve("/api/debug/engine", 200,
                    #"{"engine":"tecopa-plateworks","engine_version":"1.20.0","pid":7}"#)
        world.serve("/api/debug/forms", 200, """
            {"proof": ["session_id", "x0", "y0", "x1", "y1", "print_w", "print_h", "title",
                       "contours", "track_width_pt", "soft_light", "custom_px_w"],
             "final_submit": ["session_id", "format", "embed_spec"],
             "wallpapers_submit": ["session_id", "presets", "embed_spec"],
             "timelapse_submit": ["session_id", "max_frames", "step_ms", "format"]}
            """)
        world.serve("/api/debug/sessions/ab12/proof_form", 200, """
            {"proof_form": {"title": "Old", "print_w": 17, "print_h": 22, "contours": true,
                            "soft_light": 0.25},
             "crop": [5, 6.5, 70, 80]}
            """)
        return world
    }

    private func list(_ items: String...) -> JSONValue {
        .array(items.map { .string($0) })
    }

    private func call(_ name: String, _ world: FakeWorld,
                      _ arguments: [String: JSONValue]) async -> (data: JSONValue?, failure: TecopaFailure?) {
        let (envelope, failure) = await Catalog.call(name, world.runtime(), arguments)
        return (envelope["data"], failure)
    }

    private let tracks: JSONValue = .array([.string("/tracks/a.gpx"), .string("/tracks/b.kml")])

    // MARK: Each command, with its requests in order

    func testRenderProofUploadsProofsAndWritesThePNG() async {
        let world = engine()
        let (data, failure) = await call("render_proof", world, [
            "tracks": tracks, "region": .string("lassen_ca"),
            "set": list("title=Lassen", "contours=true"), "out": .string("/out/p.png"),
        ])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, ["GET /api/debug/forms", "POST /api/upload", "POST /api/proof",
                                     "GET /api/debug/engine"])
        XCTAssertEqual(world.posts.first?.files, [
            .init(name: "files", filename: "a.gpx", bytes: 12),
            .init(name: "files", filename: "b.kml", bytes: 13),
        ])
        XCTAssertEqual(world.posts.first?.pairs, ["region_id=lassen_ca"])
        XCTAssertEqual(world.posts.last?.pairs, [
            "session_id=ab12", "x0=10", "y0=20.5", "x1=110", "y1=150", "title=Lassen", "contours=true"])
        XCTAssertEqual(world.posts.last?.files, [])
        XCTAssertEqual(world.written, [.init(path: "/out/p.png", data: png)])
        XCTAssertEqual(data, .object([
            "out": .string("/out/p.png"), "bytes": .int(3), "sha256": .string(pngSHA),
            "session": .string("ab12"), "region": .string("lassen_ca"),
            "engine_version": .string("1.20.0"),
        ]))
    }

    func testRenderFinalSubmitsPollsAndWritesTheResult() async {
        let world = engine()
        world.serveSequence("GET /api/jobs/cd34", [(200, running), (200, running), (200, done)])
        let (data, failure) = await call("render_final", world, [
            "tracks": tracks, "opt": list("format=tiff", "embed_spec=false"),
            "out": .string("/out/final.tiff"),
        ])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, [
            "GET /api/debug/forms", "POST /api/upload", "POST /api/proof", "POST /api/final/submit",
            "GET /api/jobs/cd34", "GET /api/jobs/cd34", "GET /api/jobs/cd34",
            "GET /api/jobs/cd34/result", "GET /api/debug/engine",
        ])
        // no region was given, so none is sent, and the proof has only the crop
        XCTAssertEqual(world.posts.map(\.pairs), [
            [], ["session_id=ab12", "x0=10", "y0=20.5", "x1=110", "y1=150"],
            ["session_id=ab12", "format=tiff", "embed_spec=false"],
        ])
        // one second between polls, and none after the job is done
        XCTAssertEqual(world.slept, [1, 1])
        // the proof is not the output: only the job's file is written
        XCTAssertEqual(world.written, [.init(path: "/out/final.tiff", data: poster)])
        XCTAssertEqual(data?["out"]?.stringValue, "/out/final.tiff")
        XCTAssertEqual(data?["bytes"]?.intValue, 9)
        XCTAssertEqual(data?["sha256"]?.stringValue?.count, 64)
        XCTAssertEqual(data?["session"]?.stringValue, "ab12")
        XCTAssertEqual(data?["job"]?.stringValue, "cd34")
        XCTAssertEqual(data?["region"]?.stringValue, "lassen_ca")
        XCTAssertEqual(data?["engine_version"]?.stringValue, "1.20.0")
        XCTAssertNil(data?["skipped"])
        XCTAssertNil(data?["frames"])
    }

    func testRenderWallpaperJoinsThePresetsAndReturnsSkipped() async {
        let world = engine()
        let (data, failure) = await call("render_wallpaper", world, [
            "tracks": tracks, "presets": list("iphone", "watch"), "opt": list("embed_spec=false"),
            "out": .string("/out/wallpapers.zip"),
        ])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, [
            "GET /api/debug/forms", "POST /api/upload", "POST /api/proof", "POST /api/wallpapers/submit",
            "GET /api/jobs/cd34", "GET /api/jobs/cd34/result", "GET /api/debug/engine",
        ])
        XCTAssertEqual(world.posts.last?.path, "/api/wallpapers/submit")
        XCTAssertEqual(world.posts.last?.pairs,
                       ["session_id=ab12", "presets=iphone,watch", "embed_spec=false"])
        XCTAssertEqual(world.written, [.init(path: "/out/wallpapers.zip", data: poster)])
        XCTAssertEqual(data?["skipped"], .array([
            .object(["preset": .string("watch"), "reason": .string("too small")])]))
        XCTAssertEqual(data?["job"]?.stringValue, "cd34")
        // the engine never hides how far a device's frame grew, so the tool does not
        XCTAssertEqual(data?["fitted"], .array([
            .object(["preset": .string("iphone"), "crop_growth": .double(1.2)])]))
        XCTAssertEqual(data?["count"]?.intValue, 1)
    }

    func testRenderFilmSendsThePacingAndReturnsFrames() async {
        let world = engine()
        let (data, failure) = await call("render_film", world, [
            "session": .string("ab12"), "opt": list("max_frames=48", "format=webp"),
            "out": .string("/out/film.webp"),
        ])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, [
            "GET /api/debug/forms", "POST /api/timelapse/submit", "GET /api/jobs/cd34",
            "GET /api/jobs/cd34/result", "GET /api/debug/engine",
        ])
        XCTAssertEqual(world.posts.map(\.pairs), [["session_id=ab12", "max_frames=48", "format=webp"]])
        XCTAssertEqual(world.written, [.init(path: "/out/film.webp", data: poster)])
        XCTAssertEqual(data?["frames"]?.intValue, 48)
        XCTAssertEqual(data?["session"]?.stringValue, "ab12")
        // a session was given, so no upload named a region
        XCTAssertNil(data?["region"])
    }

    func testRenderFetchWritesTheFileOfAFinishedJob() async {
        let world = engine()
        let (data, failure) = await call("render_fetch", world, [
            "job": .string("cd34"), "out": .string("/out/late.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, ["GET /api/jobs/cd34/result", "GET /api/debug/engine"])
        XCTAssertEqual(world.written, [.init(path: "/out/late.png", data: poster)])
        XCTAssertEqual(data?["out"]?.stringValue, "/out/late.png")
        XCTAssertEqual(data?["bytes"]?.intValue, 9)
        XCTAssertEqual(data?["sha256"]?.stringValue?.count, 64)
        XCTAssertEqual(data?["job"]?.stringValue, "cd34")
        XCTAssertEqual(data?["engine_version"]?.stringValue, "1.20.0")
        XCTAssertNil(data?["session"])
    }

    func testAZipOfPanelsIsWrittenToOutUnchanged() async {
        // a set comes back as one zip; the tool has no format logic, so the bytes
        // and the path are the caller's
        let zip = Data([0x50, 0x4B, 0x03, 0x04, 0x00, 0xFF, 0x0A])
        let world = engine()
        world.serveData("GET /api/jobs/cd34/result", 200, "application/zip", zip)
        let (data, failure) = await call("render_final", world, [
            "session": .string("ab12"), "out": .string("/out/set.zip")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.written, [.init(path: "/out/set.zip", data: zip)])
        XCTAssertEqual(data?["out"]?.stringValue, "/out/set.zip")
        XCTAssertEqual(data?["bytes"]?.intValue, 7)

        let later = engine()
        later.serveData("GET /api/jobs/cd34/result", 200, "application/zip", zip)
        let (fetched, fetchFailure) = await call("render_fetch", later, [
            "job": .string("cd34"), "out": .string("/out/late.zip")])
        XCTAssertNil(fetchFailure)
        XCTAssertEqual(later.written, [.init(path: "/out/late.zip", data: zip)])
        XCTAssertEqual(fetched?["out"]?.stringValue, "/out/late.zip")
        XCTAssertEqual(fetched?["bytes"]?.intValue, 7)

        // the tool gives the file no name of its own: a path with another ending,
        // or with none, holds the same bytes
        for out in ["/out/set.png", "/out/set"] {
            let named = engine()
            named.serveData("GET /api/jobs/cd34/result", 200, "application/zip", zip)
            let (_, namedFailure) = await call("render_fetch", named, [
                "job": .string("cd34"), "out": .string(out)])
            XCTAssertNil(namedFailure, out)
            XCTAssertEqual(named.written, [.init(path: out, data: zip)], out)
        }
    }

    func testAnExistingZipOfPanelsIsRefusedBeforeAnyRequest() async {
        let world = engine()
        world.serveData("GET /api/jobs/cd34/result", 200, "application/zip", Data([0x50, 0x4B, 0x03, 0x04]))
        world.existingFile("/out/set.zip")
        let commands: [(String, [String: JSONValue])] = [
            ("render_final", ["session": .string("ab12")]),
            ("render_final", ["tracks": tracks, "set": list("panels=2", "panel_gap=2")]),
            ("render_fetch", ["job": .string("cd34")]),
        ]
        for (name, arguments) in commands {
            var arguments = arguments
            arguments["out"] = .string("/out/set.zip")
            let (data, failure) = await call(name, world, arguments)
            XCTAssertNil(data, name)
            XCTAssertEqual(failure, TecopaFailure(.usage, "A file is already at /out/set.zip."), name)
        }
        XCTAssertEqual(world.calls, [])
        XCTAssertEqual(world.written, [])
    }

    func testTheSummariesOfAFinalAndAFetchSayThatASetIsAZip() {
        // a caller reads the summary to choose `out`: the tool does not name the file
        for name in ["render_final", "render_fetch"] {
            let summary = Catalog.named(name)?.summary ?? ""
            XCTAssertTrue(summary.contains("set of panels"), name)
            XCTAssertTrue(summary.contains("zip"), name)
        }
    }

    func testRenderFetchOnARunningJobPassesThe409ThroughAndWritesNothing() async {
        let world = engine()
        world.serve("GET /api/jobs/cd34/result", 409, #"{"detail":"job is running"}"#)
        let (data, failure) = await call("render_fetch", world, [
            "job": .string("cd34"), "out": .string("/out/late.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(failure?.status, 409)
        XCTAssertEqual(failure?.body, .object(["detail": .string("job is running")]))
        XCTAssertEqual(world.calls, ["GET /api/jobs/cd34/result"])
        XCTAssertEqual(world.written, [])
    }

    // MARK: The output path

    func testAnExistingOutFailsBeforeAnyRequest() async {
        let world = engine()
        world.existingFile("/out/old.png")
        let commands: [(String, [String: JSONValue])] = [
            ("render_proof", ["tracks": tracks, "set": list("title=Lassen")]),
            ("render_final", ["tracks": tracks]),
            ("render_wallpaper", ["session": .string("ab12"), "presets": list("iphone")]),
            ("render_film", ["session": .string("ab12")]),
            ("render_fetch", ["job": .string("cd34")]),
        ]
        for (name, arguments) in commands {
            var arguments = arguments
            arguments["out"] = .string("/out/old.png")
            let (_, failure) = await call(name, world, arguments)
            XCTAssertEqual(failure, TecopaFailure(.usage, "A file is already at /out/old.png."), name)
        }
        XCTAssertEqual(world.calls, [])
        XCTAssertEqual(world.written, [])
    }

    func testAMissingFolderFailsBeforeAnyRequest() async {
        let world = engine()
        world.existingFile("/out/old.png")
        var (_, failure) = await call("render_final", world, [
            "tracks": tracks, "out": .string("/none/final.png")])
        XCTAssertEqual(failure, TecopaFailure(.usage, "The folder /none does not exist."))

        (_, failure) = await call("render_fetch", world, [
            "job": .string("cd34"), "out": .string("/out/old.png/final.png")])
        XCTAssertEqual(failure, TecopaFailure(.usage, "/out/old.png is not a folder."))
        XCTAssertEqual(world.calls, [])
    }

    func testOutIsRequiredAndNoWaitTakesNone() async {
        let world = engine()
        let commands: [(String, [String: JSONValue])] = [
            ("render_proof", ["session": .string("ab12")]),
            ("render_final", ["session": .string("ab12")]),
            ("render_fetch", ["job": .string("cd34")]),
        ]
        for (name, arguments) in commands {
            let (_, failure) = await call(name, world, arguments)
            XCTAssertEqual(failure?.kind, .usage, name)
            XCTAssertTrue(failure?.message.contains("out") ?? false, name)
        }
        // with no_wait no file is written, so a path would be a promise the tool breaks
        let (_, failure) = await call("render_final", world, [
            "session": .string("ab12"), "no_wait": .bool(true), "out": .string("/out/final.png")])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertTrue(failure?.message.contains("no_wait") ?? false)
        XCTAssertEqual(world.calls, [])
    }

    // MARK: Paths

    func testARelativePathIsRefusedBeforeAnyRequest() async {
        // Under `tecopa mcp` the working directory is the MCP client's, so a
        // relative path would name a file in a folder that the caller cannot see.
        let world = engine()
        // each of these paths can be read or written, so only the rule refuses it
        for folder in [".", "out", "~", "~/out"] { world.folder(folder) }
        for track in ["a.gpx", "tracks/a.gpx", "./a.gpx", "~/a.gpx"] {
            world.binary(track, Data("<gpx/>".utf8))
        }
        world.file("look.json", "{}")
        world.file("~/look.json", "{}")
        let out: JSONValue = .string("/out/p.png")

        for track in ["a.gpx", "tracks/a.gpx", "./a.gpx", "~/a.gpx", ""] {
            let (_, failure) = await call("render_proof", world, [
                "tracks": list("/tracks/a.gpx", track), "out": out])
            XCTAssertEqual(failure, TecopaFailure(.usage, "tracks must be an absolute path: \(track)"))
        }
        for spec in ["look.json", "~/look.json"] {
            let (_, failure) = await call("render_final", world, [
                "tracks": tracks, "spec": .string(spec), "out": out])
            XCTAssertEqual(failure, TecopaFailure(.usage, "spec must be an absolute path: \(spec)"))
        }
        let commands: [(String, [String: JSONValue])] = [
            ("render_proof", ["tracks": tracks]),
            ("render_final", ["tracks": tracks]),
            ("render_wallpaper", ["session": .string("ab12"), "presets": list("iphone")]),
            ("render_film", ["session": .string("ab12")]),
            ("render_fetch", ["job": .string("cd34")]),
        ]
        for (name, arguments) in commands {
            for path in ["p.png", "out/p.png", "./p.png", "~/p.png", "~/out/p.png"] {
                var arguments = arguments
                arguments["out"] = .string(path)
                let (_, failure) = await call(name, world, arguments)
                XCTAssertEqual(failure, TecopaFailure(.usage, "out must be an absolute path: \(path)"),
                               "\(name) \(path)")
            }
        }
        XCTAssertEqual(world.calls, [])
        XCTAssertEqual(world.written, [])
    }

    func testATrackNameThatCannotGoIntoAHeaderIsRefusedBeforeAnyRequest() async {
        // the name goes between quotes into a part's header. With a `set`, the
        // forms route was asked before the upload found the name.
        let world = engine()
        for name in ["day \"one\".gpx", "day\\one.gpx", "day\rone.gpx", "day\none.gpx", "day\r\none.gpx"] {
            world.binary("/tracks/" + name, Data("<gpx/>".utf8))
            let (data, failure) = await call("render_proof", world, [
                "tracks": list("/tracks/a.gpx", "/tracks/" + name), "set": list("title=Lassen"),
                "out": .string("/out/p.png")])
            XCTAssertNil(data, name.debugDescription)
            XCTAssertEqual(failure?.kind, .usage, name.debugDescription)
            XCTAssertTrue(failure?.message.hasPrefix("A file name cannot contain") ?? false,
                          failure?.message ?? "")
        }
        XCTAssertEqual(world.calls, [])
        XCTAssertEqual(world.written, [])
    }

    // MARK: Field names

    func testAnUnknownSetNameFailsBeforeTheUploadAndListsTheEngineNames() async {
        let world = engine()
        let (_, failure) = await call("render_proof", world, [
            "tracks": tracks, "set": list("title=Lassen", "titel=Lassen"), "out": .string("/out/p.png")])
        XCTAssertEqual(failure?.kind, .usage)
        let message = failure?.message ?? ""
        XCTAssertTrue(message.contains("titel"), message)
        // the engine's names, without the ones the tool sends from its own arguments
        XCTAssertTrue(message.contains(
            "print_w, print_h, title, contours, track_width_pt, soft_light, custom_px_w"), message)
        XCTAssertFalse(message.contains("session_id"), message)
        XCTAssertEqual(world.calls, ["GET /api/debug/forms"])
        XCTAssertEqual(world.written, [])
    }

    func testAnOptNameIsCheckedAgainstItsOwnRoute() async {
        let world = engine()
        // `format` is a field of the final and of the film, and not of the proof
        var (_, failure) = await call("render_final", world, [
            "tracks": tracks, "set": list("format=tiff"), "out": .string("/out/a.png")])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertTrue(failure?.message.contains("format") ?? false)

        // `max_frames` is a field of the film only
        (_, failure) = await call("render_final", world, [
            "tracks": tracks, "opt": list("max_frames=48"), "out": .string("/out/b.png")])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertTrue(failure?.message.contains("format, embed_spec") ?? false, failure?.message ?? "")

        (_, failure) = await call("render_wallpaper", world, [
            "tracks": tracks, "presets": list("iphone"), "opt": list("format=tiff"),
            "out": .string("/out/c.zip")])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertEqual(world.calls, ["GET /api/debug/forms", "GET /api/debug/forms", "GET /api/debug/forms"])
    }

    func testANamedFieldNeedsTheGateAndNoNamedFieldDoesNot() async {
        let world = engine()
        world.serve("/readyz", 200, FakeWorld.readyBody)
        world.serve("/api/debug/forms", 404, #"{"detail":"Not Found"}"#)
        world.serve("/api/debug/engine", 404, #"{"detail":"Not Found"}"#)

        // the tool cannot check a name with the gate off, and it never sends one unchecked
        var (data, failure) = await call("render_proof", world, [
            "tracks": tracks, "set": list("title=Lassen"), "out": .string("/out/a.png")])
        XCTAssertNil(data)
        XCTAssertTrue(failure.map(EngineClient.isGateOff) ?? false)
        XCTAssertEqual(world.posts, [])

        // with no named field the render runs, and the result has no engine_version
        (data, failure) = await call("render_proof", world, [
            "tracks": tracks, "out": .string("/out/b.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.posts.map(\.path), ["/api/upload", "/api/proof"])
        XCTAssertEqual(world.written, [.init(path: "/out/b.png", data: png)])
        XCTAssertEqual(data, .object([
            "out": .string("/out/b.png"), "bytes": .int(3), "sha256": .string(pngSHA),
            "session": .string("ab12"), "region": .string("lassen_ca"),
        ]))
    }

    func testAReservedNameIsRefusedInSetSpecAndOpt() async {
        let world = engine()
        for name in ["session_id", "x0", "y0", "x1", "y1", "files", "file", "presets"] {
            var (_, failure) = await call("render_final", world, [
                "tracks": tracks, "set": list("\(name)=1"), "out": .string("/out/a.png")])
            XCTAssertEqual(failure?.kind, .usage, "set \(name)")
            XCTAssertTrue(failure?.message.contains(name) ?? false, "set \(name)")

            (_, failure) = await call("render_final", world, [
                "tracks": tracks, "opt": list("\(name)=1"), "out": .string("/out/a.png")])
            XCTAssertEqual(failure?.kind, .usage, "opt \(name)")

            world.file("/specs/reserved.json", #"{"\#(name)": 1}"#)
            (_, failure) = await call("render_final", world, [
                "tracks": tracks, "spec": .string("/specs/reserved.json"), "out": .string("/out/a.png")])
            XCTAssertEqual(failure?.kind, .usage, "spec \(name)")
        }
        XCTAssertEqual(world.calls, [])
    }

    func testASetEntryIsKeyValueSplitOnTheFirstEquals() async {
        let world = engine()
        for bad in ["title", "=Lassen", ""] {
            let (_, failure) = await call("render_proof", world, [
                "tracks": tracks, "set": list(bad), "out": .string("/out/a.png")])
            XCTAssertEqual(failure?.kind, .usage, bad)
            XCTAssertTrue(failure?.message.contains("key=value") ?? false, bad)
        }
        let (_, failure) = await call("render_final", world, [
            "tracks": tracks, "opt": list("format"), "out": .string("/out/a.png")])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertEqual(world.calls, [])

        // the value is all the text after the first `=`, an empty text included
        let (_, sent) = await call("render_proof", world, [
            "tracks": tracks, "set": list("title=a=b = c", "contours="), "out": .string("/out/a.png")])
        XCTAssertNil(sent)
        XCTAssertEqual(world.posts.last?.pairs.suffix(2), ["title=a=b = c", "contours="])
    }

    func testASetValueWithALineEndAndAnEqualsSignIsSentIntact() async {
        let world = engine()
        let title = "Lassen\n2019 = 2024\r\nthe third line"
        let (_, failure) = await call("render_proof", world, [
            "tracks": tracks, "set": list("title=" + title), "out": .string("/out/a.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.posts.last?.fields.last, .init(name: "title", value: title))
    }

    func testAFormsAnswerWithoutTheKeyACommandNeedsIsAnEnvironmentFailure() async {
        // an engine older than the tool: the name cannot be checked, so nothing is sent
        let world = engine()
        world.serve("/api/debug/forms", 200, #"{"proof": ["session_id", "title"]}"#)
        var (data, failure) = await call("render_final", world, [
            "tracks": tracks, "opt": list("format=tiff"), "out": .string("/out/a.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertEqual(failure?.message, "The engine did not name the fields of final_submit.")

        world.serve("/api/debug/forms", 200, #"{"final_submit": ["session_id", "format"]}"#)
        (data, failure) = await call("render_final", world, [
            "tracks": tracks, "set": list("title=Lassen"), "out": .string("/out/a.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertEqual(failure?.message, "The engine did not name the fields of proof.")

        // a key that is there and is not a list of names is the same fault
        world.serve("/api/debug/forms", 200, #"{"proof": "title"}"#)
        (_, failure) = await call("render_proof", world, [
            "tracks": tracks, "set": list("title=Lassen"), "out": .string("/out/a.png")])
        XCTAssertEqual(failure?.kind, .environment)

        XCTAssertEqual(world.calls, ["GET /api/debug/forms", "GET /api/debug/forms", "GET /api/debug/forms"])
        XCTAssertEqual(world.posts, [])
        XCTAssertEqual(world.written, [])
    }

    // MARK: The spec file

    func testSetWinsOverSpecAndEachScalarIsSentAsText() async {
        let world = engine()
        world.file("/specs/look.json", """
            {"title": "From the spec", "contours": true, "track_width_pt": 2.6, "custom_px_w": 1170}
            """)
        let (_, failure) = await call("render_proof", world, [
            "tracks": tracks, "spec": .string("/specs/look.json"),
            "set": list("soft_light=0.30", "title=Lassen"), "out": .string("/out/p.png"),
        ])
        XCTAssertNil(failure)
        // the spec's fields by name, then the fields that only `set` names
        XCTAssertEqual(world.posts.last?.pairs, [
            "session_id=ab12", "x0=10", "y0=20.5", "x1=110", "y1=150",
            "contours=true", "custom_px_w=1170", "title=Lassen", "track_width_pt=2.6",
            "soft_light=0.30",
        ])
    }

    func testASpecFileThatIsNotAFlatObjectOfScalarsIsRefused() async {
        let world = engine()
        let bad = [
            #"["title"]"#, #""title""#, "not json", "",
            #"{"title": {"text": "Lassen"}}"#, #"{"title": ["Lassen"]}"#, #"{"title": null}"#,
        ]
        for text in bad {
            world.file("/specs/bad.json", text)
            let (_, failure) = await call("render_proof", world, [
                "tracks": tracks, "spec": .string("/specs/bad.json"), "out": .string("/out/p.png")])
            XCTAssertEqual(failure?.kind, .usage, text)
        }
        let (_, failure) = await call("render_proof", world, [
            "tracks": tracks, "spec": .string("/specs/none.json"), "out": .string("/out/p.png")])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertTrue(failure?.message.contains("/specs/none.json") ?? false)
        XCTAssertEqual(world.calls, [])
    }

    func testAnUnknownSpecNameIsRefusedBeforeTheUpload() async {
        let world = engine()
        world.file("/specs/typo.json", #"{"titel": "Lassen"}"#)
        let (_, failure) = await call("render_final", world, [
            "tracks": tracks, "spec": .string("/specs/typo.json"), "out": .string("/out/p.png")])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertTrue(failure?.message.contains("titel") ?? false)
        XCTAssertEqual(world.calls, ["GET /api/debug/forms"])
    }

    // MARK: The job

    func testAJobThatEndsInErrorIsRefusedAndNoFileIsWritten() async {
        let world = engine()
        let failed = #"{"state":"error","error":"OffDemError: the frame is past the DEM"}"#
        world.serveSequence("GET /api/jobs/cd34", [(200, running), (200, failed)])
        let (data, failure) = await call("render_final", world, [
            "session": .string("ab12"), "out": .string("/out/final.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertTrue(failure?.message.contains("OffDemError: the frame is past the DEM") ?? false)
        XCTAssertTrue(failure?.message.contains("cd34") ?? false)
        XCTAssertEqual(failure?.body?["state"]?.stringValue, "error")
        // the job is finished and it failed: there is no file to fetch
        XCTAssertEqual(failure?.message,
                       "Job cd34 ended in an error: OffDemError: the frame is past the DEM")
        XCTAssertNil(failure?.hint)
        XCTAssertEqual(world.calls, ["POST /api/final/submit", "GET /api/jobs/cd34", "GET /api/jobs/cd34"])
        XCTAssertEqual(world.written, [])
    }

    func testNoWaitReturnsAfterTheSubmitWithNoPoll() async {
        let world = engine()
        let (data, failure) = await call("render_final", world, [
            "session": .string("ab12"), "no_wait": .bool(true)])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, ["POST /api/final/submit", "GET /api/debug/engine"])
        XCTAssertEqual(world.slept, [])
        XCTAssertEqual(world.written, [])
        XCTAssertEqual(data, .object([
            "session": .string("ab12"), "job": .string("cd34"), "engine_version": .string("1.20.0")]))

        // the film and the bundle keep what their submit said
        let (film, _) = await call("render_film", world, ["session": .string("ab12"), "no_wait": .bool(true)])
        XCTAssertEqual(film?["frames"]?.intValue, 48)
        XCTAssertNil(film?["out"])
        let (bundle, _) = await call("render_wallpaper", world, [
            "session": .string("ab12"), "presets": list("iphone"), "no_wait": .bool(true)])
        XCTAssertEqual(bundle?["skipped"]?.arrayValue?.count, 1)
        XCTAssertEqual(world.written, [])
        XCTAssertFalse(world.calls.contains("GET /api/jobs/cd34"))
    }

    func testThePollStopsAt900SecondsAndNamesTheJob() async {
        let world = engine()
        world.serve("GET /api/jobs/cd34", 200, running)
        let (data, failure) = await call("render_final", world, [
            "session": .string("ab12"), "out": .string("/out/final.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertTrue(failure?.message.contains("cd34") ?? false, failure?.message ?? "")
        XCTAssertTrue(failure?.message.contains("900 seconds") ?? false, failure?.message ?? "")
        XCTAssertEqual(failure?.hint, "Run `tecopa render fetch`.")
        XCTAssertEqual(world.clock, 900)
        XCTAssertEqual(world.slept.count, 900)
        // one poll at the start, and one after each second
        XCTAssertEqual(world.calls.filter { $0 == "GET /api/jobs/cd34" }.count, 901)
        XCTAssertFalse(world.calls.contains("GET /api/jobs/cd34/result"))
        XCTAssertEqual(world.written, [])
    }

    func testAPollThatGetsNoAnswerFailsAtOnceAndNamesTheJob() async {
        // nothing listens: the engine stopped. The caller has no other way to learn
        // the id of the job it started.
        let world = engine()
        world.serveSteps("GET /api/jobs/cd34", [.answer(200, running), .noAnswer])
        let (_, failure) = await call("render_final", world, [
            "session": .string("ab12"), "out": .string("/out/final.png")])
        XCTAssertEqual(failure, TecopaFailure(
            .engineUnreachable, "No engine answers on port 8848. The job is cd34.",
            hint: "Run `tecopa render fetch`."))
        // no try after the poll that got no answer
        XCTAssertEqual(world.calls, ["POST /api/final/submit", "GET /api/jobs/cd34", "GET /api/jobs/cd34"])
        XCTAssertEqual(world.written, [])
    }

    func testAPollThatTimesOutIsOneMoreWait() async {
        // the engine's event loop is blocked while it paints a proof, so one poll
        // can time out while the job is healthy
        let world = engine()
        world.serveSteps("GET /api/jobs/cd34", [.timedOut, .timedOut, .answer(200, done)])
        let (data, failure) = await call("render_final", world, [
            "session": .string("ab12"), "out": .string("/out/final.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, [
            "POST /api/final/submit", "GET /api/jobs/cd34", "GET /api/jobs/cd34", "GET /api/jobs/cd34",
            "GET /api/jobs/cd34/result", "GET /api/debug/engine",
        ])
        XCTAssertEqual(world.slept, [1, 1])
        XCTAssertEqual(world.written, [.init(path: "/out/final.png", data: poster)])
        XCTAssertEqual(data?["job"]?.stringValue, "cd34")
    }

    func testPollsThatAlwaysTimeOutStillEndAtTheLimit() async {
        let world = engine()
        world.timeOut("GET /api/jobs/cd34")
        let (data, failure) = await call("render_final", world, [
            "session": .string("ab12"), "out": .string("/out/final.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure, TecopaFailure(
            .environment, "The job did not finish within 900 seconds. The job is cd34.",
            hint: "Run `tecopa render fetch`."))
        // a poll that timed out took its own 10 seconds, and they count: the limit
        // is 900 seconds on the clock, not 900 polls of 11 seconds each
        let polls = world.calls.filter { $0 == "GET /api/jobs/cd34" }.count
        XCTAssertEqual(polls, 82)
        XCTAssertEqual(world.slept.count, 81)
        XCTAssertEqual(world.written, [])
    }

    func testAPollThatTheEngineRefusesNamesTheJob() async {
        // a 500 on one poll says nothing about the job, which can still end well
        let world = engine()
        world.serveSteps("GET /api/jobs/cd34", [.answer(200, running), .answer(500, "Internal Server Error")])
        var (data, failure) = await call("render_final", world, [
            "session": .string("ab12"), "out": .string("/out/final.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure, TecopaFailure(
            .refused, "The engine answered 500 for /api/jobs/cd34. The job is cd34.",
            hint: "Run `tecopa render fetch`.", status: 500, body: .string("Internal Server Error")))
        XCTAssertEqual(world.calls, ["POST /api/final/submit", "GET /api/jobs/cd34", "GET /api/jobs/cd34"])

        // the same for the file of a job that is done
        world.serveSequence("GET /api/jobs/cd34", [(200, done)])
        world.serve("GET /api/jobs/cd34/result", 503, #"{"detail":"The plate lassen_ca is not ready."}"#)
        (data, failure) = await call("render_final", world, [
            "session": .string("ab12"), "out": .string("/out/final.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure, TecopaFailure(
            .refused, "The engine answered 503 for /api/jobs/cd34/result. The job is cd34.",
            hint: "Run `tecopa render fetch`.", status: 503,
            body: .object(["detail": .string("The plate lassen_ca is not ready.")])))
        XCTAssertEqual(world.written, [])
    }

    func testAJobReplyWithNoKnownStateFailsAtOnce() async {
        // without this the tool polled for 900 seconds on a reply it could not read
        let replies = [
            #"{"error":null}"#, #"{"state":null}"#, #"{"state":7}"#, #"{"state":"paused"}"#,
            #"{"state":"Done"}"#, #"["done"]"#, "done",
        ]
        for reply in replies {
            let world = engine()
            world.serve("GET /api/jobs/cd34", 200, reply)
            let (data, failure) = await call("render_final", world, [
                "session": .string("ab12"), "out": .string("/out/final.png")])
            XCTAssertNil(data, reply)
            XCTAssertEqual(failure?.kind, .environment, reply)
            XCTAssertEqual(failure?.message,
                           "The engine's answer for the job has no state that the tool knows. The job is cd34.",
                           reply)
            XCTAssertEqual(failure?.hint, "Run `tecopa render fetch`.", reply)
            let body = (try? JSONValue.parse(Data(reply.utf8))) ?? .string(reply)
            XCTAssertEqual(failure?.body, body, reply)
            XCTAssertEqual(world.calls, ["POST /api/final/submit", "GET /api/jobs/cd34"], reply)
            XCTAssertEqual(world.slept, [], reply)
            XCTAssertEqual(world.written, [], reply)
        }
    }

    func testAQueuedJobIsWaitedForLikeARunningOne() async {
        let world = engine()
        world.serveSequence("GET /api/jobs/cd34", [
            (200, #"{"state":"queued","error":null}"#), (200, running), (200, done)])
        let (_, failure) = await call("render_final", world, [
            "session": .string("ab12"), "out": .string("/out/final.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.slept, [1, 1])
        XCTAssertEqual(world.written, [.init(path: "/out/final.png", data: poster)])
    }

    func testAWriteThatFailsAfterTheRenderNamesTheJob() async {
        // another program made the file after the first look: the job's file is
        // still on the engine, and `render fetch` can save it to another path
        let world = engine()
        var runtime = world.runtime()
        runtime.writeNew = { path, _ in throw fileAlreadyThere(path) }
        let (_, failure) = await Catalog.call("render_final", runtime, [
            "session": .string("ab12"), "out": .string("/out/final.png")])
        XCTAssertEqual(failure, TecopaFailure(
            .usage, "A file is already at /out/final.png. The job is cd34.",
            hint: "Run `tecopa render fetch`."))
    }

    func testAProofWriteThatFailsNamesTheSession() async {
        // the proof was made, and its spec is stamped on the session: the caller
        // must learn the session, or the upload and the proof are lost
        let world = engine()
        var runtime = world.runtime()
        runtime.writeNew = { path, _ in throw fileAlreadyThere(path) }
        var (envelope, failure) = await Catalog.call("render_proof", runtime, [
            "tracks": tracks, "out": .string("/out/p.png")])
        XCTAssertNil(envelope["data"])
        XCTAssertEqual(failure, TecopaFailure(
            .usage, "A file is already at /out/p.png. The session is ab12.",
            hint: "Run `tecopa render proof --session ab12`."))
        XCTAssertEqual(world.calls, ["POST /api/upload", "POST /api/proof"])

        // the folder was there at the first look and is gone at the write
        runtime.writeNew = { _, _ in throw TecopaFailure(.usage, "The folder /out does not exist.") }
        (envelope, failure) = await Catalog.call("render_proof", runtime, [
            "session": .string("ab12"), "out": .string("/out/p.png")])
        XCTAssertNil(envelope["data"])
        XCTAssertEqual(failure, TecopaFailure(
            .usage, "The folder /out does not exist. The session is ab12.",
            hint: "Run `tecopa render proof --session ab12`."))

        // a disk fault keeps its kind
        runtime.writeNew = { path, _ in
            throw TecopaFailure(.environment, "Could not write \(path): No space left on device")
        }
        (_, failure) = await Catalog.call("render_proof", runtime, [
            "session": .string("ab12"), "out": .string("/out/p.png")])
        XCTAssertEqual(failure, TecopaFailure(
            .environment, "Could not write /out/p.png: No space left on device. The session is ab12.",
            hint: "Run `tecopa render proof --session ab12`."))
        XCTAssertEqual(world.written, [])
    }

    func testAnUnknownJobPassesThe404Through() async {
        let world = engine()
        world.serve("GET /api/jobs/cd34", 404, #"{"detail":"Unknown job"}"#)
        let (_, failure) = await call("render_final", world, [
            "session": .string("ab12"), "out": .string("/out/final.png")])
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(failure?.status, 404)
        XCTAssertEqual(failure?.body?["detail"]?.stringValue, "Unknown job")
        XCTAssertEqual(world.written, [])
    }

    // MARK: A session

    func testRenderFinalWithASessionAndNoChangeSendsNoUploadAndNoProof() async {
        let world = engine()
        let (data, failure) = await call("render_final", world, [
            "session": .string("ab12"), "out": .string("/out/final.png")])
        XCTAssertNil(failure)
        // the stamped spec is used: no field is named, so no debug route is needed
        XCTAssertEqual(world.calls, ["POST /api/final/submit", "GET /api/jobs/cd34",
                                     "GET /api/jobs/cd34/result", "GET /api/debug/engine"])
        XCTAssertEqual(world.posts.map(\.pairs), [["session_id=ab12"]])
        XCTAssertEqual(world.written, [.init(path: "/out/final.png", data: poster)])
        XCTAssertEqual(data?["session"]?.stringValue, "ab12")
    }

    func testRenderProofWithASessionAndASetStartsFromTheSessionsFields() async {
        let world = engine()
        let (_, failure) = await call("render_proof", world, [
            "session": .string("ab12"), "set": list("title=New"), "out": .string("/out/p.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, ["GET /api/debug/forms", "GET /api/debug/sessions/ab12/proof_form",
                                     "POST /api/proof", "GET /api/debug/engine"])
        // the route's crop, each of the session's fields, and the one `set` replaces
        XCTAssertEqual(world.posts.map(\.pairs), [[
            "session_id=ab12", "x0=5", "y0=6.5", "x1=70", "y1=80",
            "contours=true", "print_h=22", "print_w=17", "soft_light=0.25", "title=New",
        ]])
        XCTAssertEqual(world.written, [.init(path: "/out/p.png", data: png)])
    }

    func testRenderProofWithOnlyASessionSendsTheSessionsOwnFields() async {
        let world = engine()
        let (data, failure) = await call("render_proof", world, [
            "session": .string("ab12"), "out": .string("/out/p.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, ["GET /api/debug/sessions/ab12/proof_form", "POST /api/proof",
                                     "GET /api/debug/engine"])
        XCTAssertEqual(world.posts.last?.pairs, [
            "session_id=ab12", "x0=5", "y0=6.5", "x1=70", "y1=80",
            "contours=true", "print_h=22", "print_w=17", "soft_light=0.25", "title=Old",
        ])
        XCTAssertEqual(data?["session"]?.stringValue, "ab12")
        XCTAssertNil(data?["job"])
    }

    func testASessionChangeOrderIsProofFormThenSpecThenSet() async {
        let world = engine()
        world.file("/specs/look.json", #"{"title": "From the spec", "soft_light": 0.5}"#)
        let (_, failure) = await call("render_final", world, [
            "session": .string("ab12"), "spec": .string("/specs/look.json"),
            "set": list("title=Set"), "crop": .string("1,2,3,4"), "out": .string("/out/final.png"),
        ])
        XCTAssertNil(failure)
        XCTAssertEqual(world.posts.first?.pairs, [
            "session_id=ab12", "x0=1", "y0=2", "x1=3", "y1=4",
            "contours=true", "print_h=22", "print_w=17", "soft_light=0.5", "title=Set",
        ])
        XCTAssertEqual(world.posts.map(\.path), ["/api/proof", "/api/final/submit"])
    }

    func testACropAloneIsAChangeToASession() async {
        let world = engine()
        let (_, failure) = await call("render_final", world, [
            "session": .string("ab12"), "crop": .string("1,2,3,4"), "out": .string("/out/final.png")])
        XCTAssertNil(failure)
        // no field is named, so the forms route is not asked
        XCTAssertEqual(world.calls.prefix(3), ["GET /api/debug/sessions/ab12/proof_form",
                                               "POST /api/proof", "POST /api/final/submit"])
        XCTAssertEqual(world.posts.first?.pairs.prefix(5), ["session_id=ab12", "x0=1", "y0=2", "x1=3", "y1=4"])
    }

    func testASessionWithNoProofPassesThe409Through() async {
        let world = engine()
        world.serve("/api/debug/sessions/ab12/proof_form", 409,
                    #"{"detail":"This session has no proof yet."}"#)
        let (_, failure) = await call("render_proof", world, [
            "session": .string("ab12"), "out": .string("/out/p.png")])
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(failure?.status, 409)
        XCTAssertEqual(failure?.body?["detail"]?.stringValue, "This session has no proof yet.")
        XCTAssertEqual(world.posts, [])
        XCTAssertEqual(world.written, [])
    }

    // MARK: The crop

    func testASetThatNamesThePrintSizeAsksTheStarterCropRoute() async {
        let world = engine()
        world.serve("/api/debug/sessions/ab12/starter_crop?print_w=11&print_h=17", 200,
                    #"{"starter_crop":[1.5,2,3,4]}"#)
        let (_, failure) = await call("render_proof", world, [
            "tracks": tracks, "set": list("print_w=11", "print_h=17"), "out": .string("/out/p.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, [
            "GET /api/debug/forms", "POST /api/upload",
            "GET /api/debug/sessions/ab12/starter_crop?print_w=11&print_h=17",
            "POST /api/proof", "GET /api/debug/engine",
        ])
        XCTAssertEqual(world.posts.last?.pairs, [
            "session_id=ab12", "x0=1.5", "y0=2", "x1=3", "y1=4", "print_w=11", "print_h=17"])
    }

    func testASessionChangeOfOnePrintSizeTakesTheOtherFromTheSession() async {
        let world = engine()
        world.serve("/api/debug/sessions/ab12/starter_crop?print_w=17&print_h=11", 200,
                    #"{"starter_crop":[9,8,7,6]}"#)
        let (_, failure) = await call("render_proof", world, [
            "session": .string("ab12"), "set": list("print_h=11"), "out": .string("/out/p.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, [
            "GET /api/debug/forms", "GET /api/debug/sessions/ab12/proof_form",
            "GET /api/debug/sessions/ab12/starter_crop?print_w=17&print_h=11",
            "POST /api/proof", "GET /api/debug/engine",
        ])
        XCTAssertEqual(world.posts.last?.pairs.prefix(5), ["session_id=ab12", "x0=9", "y0=8", "x1=7", "y1=6"])
        XCTAssertTrue(world.posts.last?.pairs.contains("print_h=11") ?? false)
    }

    func testAPrintSizeIsEscapedInTheQuery() async {
        // the caller's text goes to the engine, and it cannot add a second argument
        let world = engine()
        let (_, failure) = await call("render_proof", world, [
            "tracks": tracks, "set": list("print_w=11&full=1", "print_h=1 7"), "out": .string("/out/p.png")])
        XCTAssertEqual(failure?.kind, .engineUnreachable)       // the fake has no such route
        XCTAssertEqual(world.calls.last,
                       "GET /api/debug/sessions/ab12/starter_crop?print_w=11%26full%3D1&print_h=1%207")
        XCTAssertEqual(world.written, [])
    }

    func testOnePrintSizeWithTracksIsRefusedBecauseTheToolHasNoDefault() async {
        let world = engine()
        let (_, failure) = await call("render_proof", world, [
            "tracks": tracks, "set": list("print_w=11"), "out": .string("/out/p.png")])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertTrue(failure?.message.contains("print_h") ?? false, failure?.message ?? "")
        XCTAssertEqual(world.calls, [])
    }

    func testAGivenCropWinsAndIsSentAsTheCallerWroteIt() async {
        let world = engine()
        let (_, failure) = await call("render_proof", world, [
            "tracks": tracks, "set": list("print_w=11"), "crop": .string("10.0,20,30.50,-4e1"),
            "out": .string("/out/p.png")])
        XCTAssertNil(failure)
        // no starter crop is asked for, and no number is written again
        XCTAssertEqual(world.calls, ["GET /api/debug/forms", "POST /api/upload", "POST /api/proof",
                                     "GET /api/debug/engine"])
        XCTAssertEqual(world.posts.last?.pairs, [
            "session_id=ab12", "x0=10.0", "y0=20", "x1=30.50", "y1=-4e1", "print_w=11"])
    }

    func testACropIsFourFiniteNumbers() async {
        let world = engine()
        let bad = ["1,2,3", "1,2,3,4,5", "1,2,3,x", "1,2,3,nan", "1,2,3,inf", "1,2,3,", "1, 2,3,4",
                   "0x10,2,3,4", "１,2,3,4", ""]
        for crop in bad {
            let (_, failure) = await call("render_proof", world, [
                "tracks": tracks, "crop": .string(crop), "out": .string("/out/p.png")])
            XCTAssertEqual(failure?.kind, .usage, crop)
            XCTAssertTrue(failure?.message.contains("crop") ?? false, crop)
        }
        XCTAssertEqual(world.calls, [])
    }

    // MARK: The other arguments

    func testANonHexSessionOrJobIdIsAUsageFailureWithNoRequest() async {
        let world = engine()
        for id in ["../ab", "ab/12", "zz", "ab 12", "ａｂ", "ab?x=1"] {
            var (_, failure) = await call("render_final", world, [
                "session": .string(id), "out": .string("/out/a.png")])
            XCTAssertEqual(failure?.kind, .usage, id)
            XCTAssertTrue(failure?.message.contains("hexadecimal") ?? false, id)

            (_, failure) = await call("render_fetch", world, ["job": .string(id), "out": .string("/out/a.png")])
            XCTAssertEqual(failure?.kind, .usage, id)
            XCTAssertTrue(failure?.message.contains("hexadecimal") ?? false, id)
        }
        let (_, failure) = await call("render_fetch", world, ["out": .string("/out/a.png")])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertEqual(world.calls, [])
    }

    func testAnIdTheEngineGivesIsCheckedBeforeItGoesIntoAPath() async {
        let world = engine()
        world.serve("POST /api/final/submit", 200, #"{"job":"../debug/engine"}"#)
        var (_, failure) = await call("render_final", world, [
            "session": .string("ab12"), "out": .string("/out/a.png")])
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertEqual(world.calls, ["POST /api/final/submit"])

        world.serve("POST /api/upload", 200, #"{"session":"ab/../12","starter_crop":[1,2,3,4]}"#)
        (_, failure) = await call("render_proof", world, ["tracks": tracks, "out": .string("/out/a.png")])
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertEqual(world.calls.last, "POST /api/upload")
        XCTAssertEqual(world.written, [])
    }

    func testTracksOrASessionAndNeverBoth() async {
        let world = engine()
        let out: JSONValue = .string("/out/a.png")
        let bad: [[String: JSONValue]] = [
            ["out": out],
            ["tracks": .array([]), "out": out],
            ["tracks": tracks, "session": .string("ab12"), "out": out],
            // a session has its plate already
            ["session": .string("ab12"), "region": .string("lassen_ca"), "out": out],
            ["tracks": tracks, "region": .string("../lassen"), "out": out],
            ["tracks": tracks, "region": .string("Lassen CA"), "out": out],
            ["tracks": .array([.string("/tracks/none.gpx")]), "out": out],
        ]
        for arguments in bad {
            let (_, failure) = await call("render_final", world, arguments)
            XCTAssertEqual(failure?.kind, .usage, "\(arguments.keys.sorted())")
        }
        let (_, failure) = await call("render_wallpaper", world, ["session": .string("ab12"), "out": out])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertTrue(failure?.message.contains("presets") ?? false)
        XCTAssertEqual(world.calls, [])
    }

    func testEachEntryTakesOnlyTheArgumentsThatApply() async {
        let names = ["render_proof", "render_final", "render_wallpaper", "render_film", "render_fetch"]
        for name in names {
            // each one writes a file
            XCTAssertEqual(Catalog.named(name)?.readOnly, false, name)
        }
        func parameters(_ name: String) -> [String] {
            (Catalog.named(name)?.parameters ?? []).map(\.name)
        }
        XCTAssertEqual(parameters("render_proof"),
                       ["tracks", "session", "region", "spec", "set", "crop", "out"])
        XCTAssertEqual(parameters("render_final"),
                       ["tracks", "session", "region", "spec", "set", "opt", "crop", "out", "no_wait"])
        XCTAssertEqual(parameters("render_wallpaper"),
                       ["tracks", "session", "region", "spec", "set", "opt", "crop", "presets", "out", "no_wait"])
        XCTAssertEqual(parameters("render_film"), parameters("render_final"))
        XCTAssertEqual(parameters("render_fetch"), ["job", "out"])

        // `opt` is a field of an output route, and a proof has none
        let world = engine()
        let (_, failure) = await call("render_proof", world, [
            "session": .string("ab12"), "opt": list("format=png"), "out": .string("/out/p.png")])
        XCTAssertEqual(failure?.message, "Unknown argument for render_proof: opt")
        XCTAssertEqual(world.calls, [])
    }

    // MARK: What the engine says

    func testAnEngineRefusalPassesThroughAndIsNotTriedAgain() async {
        let world = engine()
        world.serve("POST /api/proof", 422, #"{"detail":"The crop is past the zoom cap."}"#)
        var (_, failure) = await call("render_final", world, [
            "tracks": tracks, "out": .string("/out/final.png")])
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(failure?.status, 422)
        XCTAssertEqual(failure?.body, .object(["detail": .string("The crop is past the zoom cap.")]))
        XCTAssertEqual(world.calls, ["POST /api/upload", "POST /api/proof"])

        world.serve("POST /api/upload", 503, #"{"detail":"The plate lassen_ca is not ready."}"#)
        (_, failure) = await call("render_proof", world, ["tracks": tracks, "out": .string("/out/p.png")])
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(failure?.status, 503)
        XCTAssertEqual(world.calls.suffix(1), ["POST /api/upload"])

        (_, failure) = await call("render_wallpaper", world, [
            "session": .string("ab12"), "presets": list("watch"), "out": .string("/out/w.zip")])
        XCTAssertNil(failure)
        world.serve("POST /api/wallpapers/submit", 422, #"{"detail":"No requested device fits this region"}"#)
        (_, failure) = await call("render_wallpaper", world, [
            "session": .string("ab12"), "presets": list("watch"), "out": .string("/out/w2.zip")])
        XCTAssertEqual(failure, TecopaFailure(
            .refused, "The engine answered 422 for /api/wallpapers/submit.", status: 422,
            body: .object(["detail": .string("No requested device fits this region")])))
        XCTAssertEqual(world.written.map(\.path), ["/out/w.zip"])
    }

    func testAProofAnswerThatIsNotAFileIsNotWritten() async {
        // a 200 with JSON is not a proof, and the tool never writes it as one
        let world = engine()
        world.serve("POST /api/proof", 200, #"{"note":"not an image"}"#)
        let (_, failure) = await call("render_proof", world, ["tracks": tracks, "out": .string("/out/p.png")])
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertEqual(world.written, [])
    }

    func testNoResultHoldsTheTrackGeometry() async {
        let world = engine()
        let commands: [(String, [String: JSONValue])] = [
            ("render_proof", ["out": .string("/out/a.png")]),
            ("render_final", ["out": .string("/out/b.png")]),
            ("render_final", ["no_wait": .bool(true)]),
            ("render_wallpaper", ["presets": list("iphone"), "out": .string("/out/c.zip")]),
            ("render_film", ["out": .string("/out/d.png")]),
        ]
        for (name, arguments) in commands {
            var arguments = arguments
            arguments["tracks"] = tracks
            let (data, failure) = await call(name, world, arguments)
            XCTAssertNil(failure, name)
            XCTAssertNil(data?["tracks"], name)
            let text = data?.text(pretty: false) ?? ""
            XCTAssertFalse(text.contains("track"), "\(name): \(text)")
            XCTAssertFalse(text.contains("starter_crop"), "\(name): \(text)")
            XCTAssertEqual(data?["session"]?.stringValue, "ab12", name)
        }
    }

    // MARK: The engine's warnings

    /// An upload answer that says each thing the engine dropped or changed.
    private let loudUpload = #"{"session":"ab12","region":"rifle_aspen","starter_crop":[10,20.5,110,150],"#
        + #""tracks":[{"track_id":"t1","px":[[1,2],[3,4]]}],"hotspots":[{"px":[5,6],"label":"camp"}],"#
        + #""recovered":true,"skipped_duplicates":["a.gpx"],"skipped_duplicate_tracks":3,"#
        + #""dropped_points":12,"journeys_outside_plate":2,"track_days":["2023-07-01"]}"#

    private let loud: JSONValue = .object([
        "recovered": .bool(true), "skipped_duplicates": .array([.string("a.gpx")]),
        "skipped_duplicate_tracks": .int(3), "dropped_points": .int(12),
        "journeys_outside_plate": .int(2),
    ])

    func testTheUploadsWarningsRideTheResultUnderOneKey() async {
        let world = engine()
        world.serve("POST /api/upload", 200, loudUpload)
        let commands: [(String, [String: JSONValue])] = [
            ("render_proof", ["out": .string("/out/a.png")]),
            ("render_final", ["out": .string("/out/b.png")]),
            ("render_final", ["no_wait": .bool(true)]),
            ("render_wallpaper", ["presets": list("iphone"), "out": .string("/out/c.zip")]),
            ("render_film", ["out": .string("/out/d.png")]),
        ]
        for (name, arguments) in commands {
            var arguments = arguments
            arguments["tracks"] = tracks
            let (data, failure) = await call(name, world, arguments)
            XCTAssertNil(failure, name)
            // the five keys and no other: never the geometry, never the hotspots
            XCTAssertEqual(data?["upload"], loud, name)
            XCTAssertNil(data?["tracks"], name)
            XCTAssertNil(data?["hotspots"], name)
            let text = data?.text(pretty: false) ?? ""
            for word in [#""px""#, #""tracks""#, "track_id", "hotspots", "camp", "track_days", "starter_crop"] {
                XCTAssertFalse(text.contains(word), "\(name) \(word): \(text)")
            }
        }
    }

    func testAnUploadWarningIsKeptAsTheEngineGaveItAndOnlyWhenItDid() async {
        // a zero and a false are the engine's answer too: the tool does not judge them
        let world = engine()
        world.serve("POST /api/upload", 200,
                    #"{"session":"ab12","region":"lassen_ca","starter_crop":[10,20.5,110,150],"#
                        + #""recovered":false,"dropped_points":0,"skipped_duplicates":[]}"#)
        var (data, failure) = await call("render_proof", world, ["tracks": tracks, "out": .string("/out/a.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(data?["upload"], .object([
            "recovered": .bool(false), "dropped_points": .int(0), "skipped_duplicates": .array([])]))

        // a session was given: no upload was sent, so the result has no such key
        (data, failure) = await call("render_proof", world, [
            "session": .string("ab12"), "out": .string("/out/b.png")])
        XCTAssertNil(failure)
        XCTAssertNil(data?["upload"])
    }

    func testTheTextOfAResultNamesEachWarningThatIsNotZero() {
        let result: JSONValue = .object([
            "out": .string("/out/w.zip"), "session": .string("ab12"), "job": .string("cd34"),
            "count": .int(2),
            "skipped": .array([.object(["preset": .string("watch"), "reason": .string("too small")])]),
            "fitted": .array([
                .object(["preset": .string("iphone"), "crop_growth": .double(1.2)]),
                .object(["preset": .string("ipad"), "crop_growth": .int(1)]),
            ]),
            "upload": .object([
                "recovered": .bool(true), "skipped_duplicates": .array([.string("a.gpx"), .string("b.kml")]),
                "skipped_duplicate_tracks": .int(3), "dropped_points": .int(12),
                "journeys_outside_plate": .int(2),
            ]),
        ])
        XCTAssertEqual(Catalog.named("render_wallpaper")?.text?(result), """
            out: /out/w.zip
            session: ab12
            job: cd34
            count: 2
            skipped: watch: too small
            fitted: iphone: crop growth 1.2
            fitted: ipad: crop growth 1
            recovered: true
            skipped duplicates: a.gpx, b.kml
            skipped duplicate tracks: 3
            dropped points: 12
            journeys outside the plate: 2
            """)

        // nothing to say is no line
        let quiet: JSONValue = .object([
            "session": .string("ab12"),
            "upload": .object([
                "recovered": .bool(false), "skipped_duplicates": .array([]),
                "skipped_duplicate_tracks": .int(0), "dropped_points": .int(0),
                "journeys_outside_plate": .int(0),
            ]),
        ])
        XCTAssertEqual(Catalog.named("render_proof")?.text?(quiet), "session: ab12")
    }

    func testTheTextOfAResultIsAFewLines() {
        let result: JSONValue = .object([
            "out": .string("/out/w.zip"), "bytes": .int(9), "sha256": .string("ab"),
            "session": .string("ab12"), "job": .string("cd34"), "region": .string("lassen_ca"),
            "engine_version": .string("1.20.0"),
            "skipped": .array([.object(["preset": .string("watch"), "reason": .string("too small")])]),
        ])
        XCTAssertEqual(Catalog.named("render_wallpaper")?.text?(result), """
            out: /out/w.zip
            bytes: 9
            sha256: ab
            session: ab12
            job: cd34
            region: lassen_ca
            engine_version: 1.20.0
            skipped: watch: too small
            """)
        let film: JSONValue = .object([
            "session": .string("ab12"), "job": .string("cd34"), "frames": .int(48)])
        XCTAssertEqual(Catalog.named("render_film")?.text?(film), "session: ab12\njob: cd34\nframes: 48")
    }
}
