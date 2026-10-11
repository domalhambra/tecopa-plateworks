import XCTest
@testable import TecopaKit

final class ReprintTests: XCTestCase {
    /// The poster file the caller has, and the files the fake engine answers with.
    private let file = Data("a poster with a manifest".utf8)
    private let reprinted = Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0xFF, 0x01])
    private let png = Data("abc".utf8)
    private let poster = Data([0x89, 0x50, 0x4E, 0x47, 0x00, 0xFF, 0x0D, 0x0A, 0x1A])

    private let running = #"{"state":"running","error":null}"#
    private let done = #"{"state":"done","error":null,"result":"/api/jobs/cd34/result"}"#
    private let film = #"{"job":"cd34","frames":48}"#
    private let mismatch = #"{"detail":"This poster was made on another build of the plate lassen_ca. "#
        + #"Resubmit with allow_plate_mismatch=true to reprint it on the current plate."}"#

    private let inspection = """
        {"manifest_version": 3, "engine": "tecopa-plateworks", "region_id": "lassen_ca",
         "region_available": true, "sources": [{"filename": "a.gpx", "sha256": "ff"}],
         "print_size_in": [17, 22], "title": "Lassen", "tracks": 4, "hotspots": 1, "edition": 2,
         "lineage": [{"sha256": "ee", "edition": 1}], "animation": null, "plate": "verified",
         "plate_file": "p1", "plate_server": "p1"}
        """

    /// The answer of /api/continue: the /api/upload shape, with geometry and the
    /// studio's prefill, which no result may hold.
    private let continued = """
        {"session": "ab12", "region": "lassen_ca", "name": "Lassen",
         "overview": "/regions/lassen_ca/overview.png", "overview_size": [2000, 3000],
         "tracks": [[[1, 2], [3, 4]]], "track_days": ["2023-07-01"],
         "hotspots": [{"px": [5, 6], "label": "camp"}], "starter_crop": [5, 6.5, 70, 80],
         "recovered": false, "skipped_duplicates": [], "edition": 2, "files": ["a.gpx"],
         "year_span": "2023", "journey_light": null, "final_dpi": 300,
         "prefill": {"title": "Lassen", "style": {"width": 2.6}},
         "proof_form": {"title": "Lassen", "print_w": 17, "print_h": 22, "contours": true,
                        "soft_light": 0.25, "track_color": "#c0392b"}}
        """

    /// An engine with the gate open. A reprint is a still, a continue gives the
    /// session "ab12" at edition 2, and each job is "cd34" and done.
    private func engine() -> FakeWorld {
        let world = FakeWorld()
        world.folder("/out")
        world.binary("/posters/lassen.png", file)
        world.binary("/tracks/new.gpx", Data("<gpx>new</gpx>".utf8))
        world.serve("POST /api/reprint/inspect", 200, inspection)
        world.serveData("POST /api/reprint", 200, "image/png", reprinted)
        world.serve("POST /api/continue", 200, continued)
        world.serve("POST /api/upload", 200,
                    #"{"session":"ab12","region":"lassen_ca","starter_crop":[10,20.5,110,150],"#
                        + #""tracks":[{"track_id":"t1","px":[[1,2],[3,4]]}]}"#)
        world.serveData("POST /api/proof", 200, "image/png", png)
        world.serve("POST /api/final/submit", 200, #"{"job":"cd34"}"#)
        world.serve("GET /api/jobs/cd34", 200, done)
        world.serveData("GET /api/jobs/cd34/result", 200, "image/png", poster)
        world.serve("/api/debug/engine", 200,
                    #"{"engine":"tecopa-plateworks","engine_version":"1.20.0","pid":7}"#)
        world.serve("/api/debug/forms", 200, """
            {"proof": ["session_id", "x0", "y0", "x1", "y1", "print_w", "print_h", "title",
                       "contours", "soft_light", "track_color"],
             "final_submit": ["session_id", "format", "embed_spec"],
             "reprint": ["file", "format", "allow_plate_mismatch", "embed_spec"],
             "continue": ["file", "allow_plate_mismatch"]}
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

    /// The fields of one POST as "name=value", or none when it was not sent.
    private func pairs(_ world: FakeWorld, _ index: Int) -> [String] {
        world.posts.indices.contains(index) ? world.posts[index].pairs : []
    }

    private let lassen: JSONValue = .string("/posters/lassen.png")
    private let posterPart = [FakeWorld.Post.File(name: "file", filename: "lassen.png", bytes: 24)]

    // MARK: reprint inspect

    func testReprintInspectReturnsTheEnginesAnswerUnchanged() async throws {
        let world = engine()
        let (data, failure) = await call("reprint_inspect", world, ["file": lassen])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, ["POST /api/reprint/inspect"])
        XCTAssertEqual(world.posts, [.init(path: "/api/reprint/inspect", fields: [], files: posterPart)])
        XCTAssertEqual(data, try JSONValue.parse(Data(inspection.utf8)))
        XCTAssertEqual(world.written, [])
    }

    func testReprintInspectOnAFileWithNoManifestPassesThe422Through() async {
        let world = engine()
        world.serve("POST /api/reprint/inspect", 422, #"{"detail":"This file has no Tecopa Plateworks manifest."}"#)
        let (data, failure) = await call("reprint_inspect", world, ["file": lassen])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(failure?.status, 422)
        XCTAssertEqual(failure?.body,
                       .object(["detail": .string("This file has no Tecopa Plateworks manifest.")]))
    }

    // MARK: reprint

    func testReprintWritesTheReplyBytesForAStill() async {
        let world = engine()
        let (data, failure) = await call("reprint", world, ["file": lassen, "out": .string("/out/again.png")])
        XCTAssertNil(failure)
        // no field is named, so the forms route is not asked, and no job is polled
        XCTAssertEqual(world.calls, ["POST /api/reprint", "GET /api/debug/engine"])
        XCTAssertEqual(world.posts, [.init(path: "/api/reprint", fields: [], files: posterPart)])
        XCTAssertEqual(world.written, [.init(path: "/out/again.png", data: reprinted)])
        XCTAssertEqual(data?["out"]?.stringValue, "/out/again.png")
        XCTAssertEqual(data?["bytes"]?.intValue, 11)
        XCTAssertEqual(data?["sha256"]?.stringValue?.count, 64)
        XCTAssertEqual(data?["engine_version"]?.stringValue, "1.20.0")
        XCTAssertNil(data?["job"])
        XCTAssertNil(data?["session"])
    }

    func testReprintWritesTheZipOfASet() async {
        // one panel file gives the whole set, as one zip: the reply is written as it came
        let zip = Data([0x50, 0x4B, 0x03, 0x04, 0x01, 0x02])
        let world = engine()
        world.serveData("POST /api/reprint", 200, "application/zip", zip)
        let (data, failure) = await call("reprint", world, [
            "file": lassen, "out": .string("/out/set.zip")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, ["POST /api/reprint", "GET /api/debug/engine"])
        XCTAssertEqual(world.written, [.init(path: "/out/set.zip", data: zip)])
        XCTAssertEqual(data?["out"]?.stringValue, "/out/set.zip")
        XCTAssertEqual(data?["bytes"]?.intValue, 6)
        // a zip is not a job: nothing is polled and no job is named
        XCTAssertNil(data?["job"])
    }

    func testReprintRefusesAnExistingZipBeforeAnyRequest() async {
        let world = engine()
        world.serveData("POST /api/reprint", 200, "application/zip", Data([0x50, 0x4B, 0x03, 0x04]))
        world.existingFile("/out/set.zip")
        let (data, failure) = await call("reprint", world, ["file": lassen, "out": .string("/out/set.zip")])
        XCTAssertNil(data)
        XCTAssertEqual(failure, TecopaFailure(.usage, "A file is already at /out/set.zip."))
        XCTAssertEqual(world.calls, [])
        XCTAssertEqual(world.written, [])
    }

    func testTheSummaryOfAReprintSaysThatOnePanelGivesTheSetAsAZip() {
        let summary = Catalog.named("reprint")?.summary ?? ""
        XCTAssertTrue(summary.contains("One panel of a set"))
        XCTAssertTrue(summary.contains("zip"))
    }

    func testReprintSendsEachOptToTheReprintRoute() async {
        let world = engine()
        let pdf = Data("%PDF-1.7".utf8)
        world.serveData("POST /api/reprint", 200, "application/pdf", pdf)
        let (_, failure) = await call("reprint", world, [
            "file": lassen, "opt": list("format=pdf", "embed_spec=false"), "out": .string("/out/again.pdf")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, ["GET /api/debug/forms", "POST /api/reprint", "GET /api/debug/engine"])
        XCTAssertEqual(world.posts.first?.pairs, ["format=pdf", "embed_spec=false"])
        XCTAssertEqual(world.posts.first?.files, posterPart)
        XCTAssertEqual(world.written, [.init(path: "/out/again.pdf", data: pdf)])
    }

    func testReprintFollowsTheJobForAFilm() async {
        let world = engine()
        world.serve("POST /api/reprint", 200, film)
        world.serveSequence("GET /api/jobs/cd34", [(200, running), (200, done)])
        let (data, failure) = await call("reprint", world, ["file": lassen, "out": .string("/out/film.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, [
            "POST /api/reprint", "GET /api/jobs/cd34", "GET /api/jobs/cd34",
            "GET /api/jobs/cd34/result", "GET /api/debug/engine",
        ])
        XCTAssertEqual(world.slept, [1])
        // the reply is the job, not the film: only the job's file is written
        XCTAssertEqual(world.written, [.init(path: "/out/film.png", data: poster)])
        XCTAssertEqual(data?["job"]?.stringValue, "cd34")
        XCTAssertEqual(data?["frames"]?.intValue, 48)
        XCTAssertEqual(data?["out"]?.stringValue, "/out/film.png")
        XCTAssertEqual(data?["bytes"]?.intValue, 9)
    }

    func testReprintNoWaitOnAFilmReturnsTheJobAndWritesNothing() async {
        let world = engine()
        world.serve("POST /api/reprint", 200, film)
        let (data, failure) = await call("reprint", world, [
            "file": lassen, "out": .string("/out/film.png"), "no_wait": .bool(true)])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, ["POST /api/reprint", "GET /api/debug/engine"])
        XCTAssertEqual(world.slept, [])
        XCTAssertEqual(world.written, [])
        // no `out`: a path that holds no file is not in the result
        XCTAssertEqual(data, .object([
            "job": .string("cd34"), "frames": .int(48), "engine_version": .string("1.20.0")]))
    }

    func testReprintNoWaitOnAStillWritesThePosterThatHasArrived() async {
        // a still is the reply itself: there is no job to fetch later
        let world = engine()
        let (data, failure) = await call("reprint", world, [
            "file": lassen, "out": .string("/out/again.png"), "no_wait": .bool(true)])
        XCTAssertNil(failure)
        XCTAssertEqual(world.written, [.init(path: "/out/again.png", data: reprinted)])
        XCTAssertEqual(data?["out"]?.stringValue, "/out/again.png")
        XCTAssertNil(data?["job"])
    }

    func testReprintNeedsOutBeforeAnyRequestWithNoWaitToo() async {
        // without a path, the poster of a still would arrive and have no place to go
        let world = engine()
        for arguments: [String: JSONValue] in [["file": lassen], ["file": lassen, "no_wait": .bool(true)]] {
            let (_, failure) = await call("reprint", world, arguments)
            XCTAssertEqual(failure?.kind, .usage)
            XCTAssertTrue(failure?.message.hasPrefix("out is required") ?? false, failure?.message ?? "")
            XCTAssertTrue(failure?.message.contains("still") ?? false, failure?.message ?? "")
        }
        XCTAssertEqual(world.calls, [])
    }

    func testAnOptNameNotInTheReprintFormIsRefusedBeforeTheFileIsSent() async {
        let world = engine()
        let (_, failure) = await call("reprint", world, [
            "file": lassen, "opt": list("format=png", "max_frames=3"), "out": .string("/out/again.png")])
        XCTAssertEqual(failure?.kind, .usage)
        let message = failure?.message ?? ""
        XCTAssertTrue(message.contains("max_frames"), message)
        // the engine's names, without the ones the tool sends from its own arguments
        XCTAssertTrue(message.hasSuffix("The engine's fields are: format, embed_spec."), message)
        XCTAssertEqual(world.calls, ["GET /api/debug/forms"])
        XCTAssertEqual(world.posts, [])
        XCTAssertEqual(world.written, [])
    }

    func testAReprintReplyThatIsJsonWithNoJobIsNotWritten() async {
        let world = engine()
        world.serve("POST /api/reprint", 200, #"{"note":"not a poster"}"#)
        var (_, failure) = await call("reprint", world, ["file": lassen, "out": .string("/out/a.png")])
        XCTAssertEqual(failure?.kind, .environment)

        // a job id goes into a URL path, so the engine's own is checked too
        world.serve("POST /api/reprint", 200, #"{"job":"../debug/engine","frames":2}"#)
        (_, failure) = await call("reprint", world, ["file": lassen, "out": .string("/out/a.png")])
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertEqual(world.calls, ["POST /api/reprint", "POST /api/reprint"])
        XCTAssertEqual(world.written, [])
    }

    func testAReprintRefusalThatIsNotJsonKeepsItsText() async {
        let world = engine()
        world.serve("POST /api/reprint", 500, "Internal Server Error")
        let (_, failure) = await call("reprint", world, ["file": lassen, "out": .string("/out/a.png")])
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(failure?.status, 500)
        XCTAssertEqual(failure?.body, .string("Internal Server Error"))
        XCTAssertEqual(world.written, [])
    }

    func testAReprintReplyWithATextContentTypeIsNotWrittenAsAPoster() async {
        // another program on the port answers 200 with a page
        let world = engine()
        world.serveData("POST /api/reprint", 200, "text/html; charset=utf-8", Data("<html>hello</html>".utf8))
        let (data, failure) = await call("reprint", world, ["file": lassen, "out": .string("/out/a.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertEqual(failure?.message, "Port 8848 answers, but it is not Tecopa Plateworks.")
        XCTAssertTrue(failure?.hint?.contains("/api/reprint") ?? false, failure?.hint ?? "")
        XCTAssertEqual(world.calls, ["POST /api/reprint"])
        XCTAssertEqual(world.written, [])

        // the letter case of a header value is not a rule
        world.serveData("POST /api/reprint", 200, "Text/Plain", Data("hello".utf8))
        let (_, plain) = await call("reprint", world, ["file": lassen, "out": .string("/out/a.png")])
        XCTAssertEqual(plain?.kind, .environment)
        XCTAssertEqual(world.written, [])
    }

    func testAReprintReplyWithNoContentTypeIsNotWrittenAsAPoster() async {
        let world = engine()
        world.serveData("POST /api/reprint", 200, nil, reprinted)
        let (data, failure) = await call("reprint", world, ["file": lassen, "out": .string("/out/a.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertEqual(failure?.message, "Port 8848 answers, but it is not Tecopa Plateworks.")
        XCTAssertEqual(world.written, [])
    }

    func testAReprintReplyWithAnEmptyBodyIsNotWrittenAsAPoster() async {
        let world = engine()
        world.serveData("POST /api/reprint", 200, "image/png", Data())
        let (data, failure) = await call("reprint", world, ["file": lassen, "out": .string("/out/a.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertEqual(failure?.message, "Port 8848 answers, but it is not Tecopa Plateworks.")
        XCTAssertEqual(world.written, [])
    }

    // MARK: continue

    func testContinueProofFormValuesReadBackAsTheSameValues() async {
        // FastAPI must parse each text back to the value the engine gave: a false,
        // a float with a whole value, a float with an exponent, and strings that a
        // shell or a header could change.
        let world = engine()
        world.serve("POST /api/continue", 200, """
            {"session": "ab12", "region": "lassen_ca", "starter_crop": [5, 6.5, 70, 80], "edition": 2,
             "proof_form": {"contours": false, "labels": true, "print_w": 17.0, "print_h": 22,
                            "soft_light": 0.25, "haze": 1e-05, "title": "-",
                            "subtitle": "Caf\\u00e9 \\"Lassen\\" 2023", "track_color": "#c0392b"}}
            """)
        let (_, failure) = await call("continue", world, ["file": lassen, "out": .string("/out/two.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(pairs(world, 1), [
            "session_id=ab12", "x0=5", "y0=6.5", "x1=70", "y1=80",
            "contours=false", "haze=1e-05", "labels=true", "print_h=22", "print_w=17",
            "soft_light=0.25", "subtitle=Café \"Lassen\" 2023", "title=-", "track_color=#c0392b",
        ])
        // the text of each number reads back as the same number
        XCTAssertEqual(Double("1e-05"), 0.00001)
        XCTAssertEqual(Double("17"), 17.0)
    }

    func testAContinueOptNameNotInTheFinalFormIsRefusedBeforeTheFileIsSent() async {
        // `max_frames` is a field of the film route, not of the final
        let world = engine()
        let (data, failure) = await call("continue", world, [
            "file": lassen, "set": list("title=Two", "soft_light=0.30"), "opt": list("max_frames=3"),
            "out": .string("/out/two.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .usage)
        let message = failure?.message ?? ""
        XCTAssertTrue(message.hasPrefix("Unknown field for final_submit: max_frames."), message)
        XCTAssertTrue(message.hasSuffix("The engine's fields are: format, embed_spec."), message)
        XCTAssertEqual(world.calls, ["GET /api/debug/forms"])
        XCTAssertEqual(world.posts, [])
        XCTAssertEqual(world.written, [])
    }

    func testAFileNameThatCannotGoIntoAHeaderIsRefusedBeforeAnyRequest() async {
        // /api/continue takes the poster and makes a session, so the name of a new
        // track is checked before it, not at the upload that follows
        let world = engine()
        let out: JSONValue = .string("/out/two.png")
        for name in ["day \"one\".gpx", "day\\one.gpx", "day\rone.gpx", "day\none.gpx", "day\r\none.gpx"] {
            world.binary("/tracks/" + name, Data("<gpx/>".utf8))
            let (data, failure) = await call("continue", world, [
                "file": lassen, "tracks": list("/tracks/new.gpx", "/tracks/" + name), "out": out])
            XCTAssertNil(data, name.debugDescription)
            XCTAssertEqual(failure?.kind, .usage, name.debugDescription)
            XCTAssertTrue(failure?.message.hasPrefix("A file name cannot contain") ?? false,
                          failure?.message ?? "")
        }
        // the poster's own name, on each entry that sends it
        world.binary("/posters/las\"sen.png", file)
        for name in ["reprint_inspect", "reprint", "continue"] {
            var arguments: [String: JSONValue] = ["file": .string("/posters/las\"sen.png")]
            if name != "reprint_inspect" {
                arguments["out"] = out
                arguments["opt"] = list("format=png")
            }
            let (_, failure) = await call(name, world, arguments)
            XCTAssertEqual(failure?.kind, .usage, name)
            XCTAssertTrue(failure?.message.hasPrefix("A file name cannot contain") ?? false, name)
        }
        XCTAssertEqual(world.calls, [])
        XCTAssertEqual(world.written, [])
    }

    func testContinueSendsProofFormUnchangedThenTheFinal() async {
        let world = engine()
        let (data, failure) = await call("continue", world, ["file": lassen, "out": .string("/out/two.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, [
            "POST /api/continue", "POST /api/proof", "POST /api/final/submit",
            "GET /api/jobs/cd34", "GET /api/jobs/cd34/result", "GET /api/debug/engine",
        ])
        XCTAssertEqual(world.posts.first, .init(path: "/api/continue", fields: [], files: posterPart))
        // the continue answer's crop, and each proof_form value as the engine gave it
        XCTAssertEqual(pairs(world, 1), [
            "session_id=ab12", "x0=5", "y0=6.5", "x1=70", "y1=80",
            "contours=true", "print_h=22", "print_w=17", "soft_light=0.25", "title=Lassen",
            "track_color=#c0392b",
        ])
        XCTAssertEqual(pairs(world, 2), ["session_id=ab12"])
        // the proof is not the output: only the job's file is written
        XCTAssertEqual(world.written, [.init(path: "/out/two.png", data: poster)])
        XCTAssertEqual(data, .object([
            "out": .string("/out/two.png"), "bytes": .int(9),
            "sha256": data?["sha256"] ?? .null, "session": .string("ab12"),
            "region": .string("lassen_ca"), "job": .string("cd34"), "edition": .int(2),
            "year_span": .string("2023"), "engine_version": .string("1.20.0"),
        ]))
        XCTAssertEqual(data?["sha256"]?.stringValue?.count, 64)
    }

    func testAContinueSetReplacesOneProofFormValueAndOptGoesToTheFinal() async {
        let world = engine()
        let (_, failure) = await call("continue", world, [
            "file": lassen, "set": list("title=Lassen, year two", "haze=0.1"),
            "opt": list("format=pdf"), "out": .string("/out/two.pdf"),
        ])
        XCTAssertEqual(failure?.kind, .usage)                    // `haze` is not in the fake's list
        XCTAssertEqual(world.calls, ["GET /api/debug/forms"])

        let (_, sent) = await call("continue", world, [
            "file": lassen, "set": list("title=Lassen, year two", "soft_light=0.30"),
            "opt": list("format=pdf"), "out": .string("/out/two.pdf"),
        ])
        XCTAssertNil(sent)
        XCTAssertEqual(world.posts.map(\.path), ["/api/continue", "/api/proof", "/api/final/submit"])
        // each replaced value keeps its place, and every other value is unchanged
        XCTAssertEqual(pairs(world, 1), [
            "session_id=ab12", "x0=5", "y0=6.5", "x1=70", "y1=80",
            "contours=true", "print_h=22", "print_w=17", "soft_light=0.30",
            "title=Lassen, year two", "track_color=#c0392b",
        ])
        XCTAssertEqual(pairs(world, 2), ["session_id=ab12", "format=pdf"])
    }

    func testContinueWithTracksSendsTheUploadWithTheSessionID() async {
        let world = engine()
        let (data, failure) = await call("continue", world, [
            "file": lassen, "tracks": list("/tracks/new.gpx"), "out": .string("/out/two.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls.prefix(4), [
            "POST /api/continue", "POST /api/upload", "POST /api/proof", "POST /api/final/submit"])
        XCTAssertEqual(world.posts.dropFirst().first, .init(
            path: "/api/upload", fields: [.init(name: "session_id", value: "ab12")],
            files: [.init(name: "files", filename: "new.gpx", bytes: 14)]))
        // the crop is the continue answer's, not the upload's
        XCTAssertEqual(pairs(world, 2).prefix(5), ["session_id=ab12", "x0=5", "y0=6.5", "x1=70", "y1=80"])
        XCTAssertEqual(data?["session"]?.stringValue, "ab12")
        XCTAssertEqual(data?["edition"]?.intValue, 2)
    }

    func testContinueWithTracksCarriesTheUploadsWarnings() async {
        let world = engine()
        world.serve("POST /api/upload", 200,
                    #"{"session":"ab12","region":"lassen_ca","starter_crop":[10,20.5,110,150],"#
                        + #""tracks":[{"track_id":"t1","px":[[1,2],[3,4]]}],"hotspots":[{"px":[5,6]}],"#
                        + #""recovered":false,"skipped_duplicates":["new.gpx"],"skipped_duplicate_tracks":4,"#
                        + #""dropped_points":0,"journeys_outside_plate":1}"#)
        let loud: JSONValue = .object([
            "recovered": .bool(false), "skipped_duplicates": .array([.string("new.gpx")]),
            "skipped_duplicate_tracks": .int(4), "dropped_points": .int(0),
            "journeys_outside_plate": .int(1),
        ])
        for arguments: [String: JSONValue] in [["out": .string("/out/two.png")], ["no_wait": .bool(true)]] {
            var arguments = arguments
            arguments["file"] = lassen
            arguments["tracks"] = list("/tracks/new.gpx")
            let (data, failure) = await call("continue", world, arguments)
            XCTAssertNil(failure)
            XCTAssertEqual(data?["upload"], loud)
            let text = data?.text(pretty: false) ?? ""
            for word in [#""px""#, #""tracks""#, "track_id", "hotspots", "prefill", "proof_form", "starter_crop"] {
                XCTAssertFalse(text.contains(word), "\(word): \(text)")
            }
        }

        // with no new tracks there is no upload: the continue answer's own keys of
        // the same names are not an upload's warnings
        let (data, failure) = await call("continue", world, ["file": lassen, "out": .string("/out/one.png")])
        XCTAssertNil(failure)
        XCTAssertNil(data?["upload"])
    }

    func testContinueStopsWhenTheUploadAnswersAnotherSession() async {
        // the engine makes a new session for an id it does not have. That session
        // has only the new tracks, at edition 1: it is not the continued poster.
        let world = engine()
        world.serve("POST /api/upload", 200, #"{"session":"ef56","region":"lassen_ca","starter_crop":[1,2,3,4]}"#)
        let (data, failure) = await call("continue", world, [
            "file": lassen, "tracks": list("/tracks/new.gpx"), "out": .string("/out/two.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertTrue(failure?.message.contains("ef56") ?? false, failure?.message ?? "")
        XCTAssertEqual(world.calls, ["POST /api/continue", "POST /api/upload"])
        XCTAssertEqual(world.written, [])
    }

    func testContinueNeverReturnsTheTrackGeometryOrThePrefill() async {
        let world = engine()
        let runs: [[String: JSONValue]] = [
            ["out": .string("/out/a.png")],
            ["tracks": list("/tracks/new.gpx"), "out": .string("/out/b.png")],
            ["no_wait": .bool(true)],
        ]
        for arguments in runs {
            var arguments = arguments
            arguments["file"] = lassen
            let (data, failure) = await call("continue", world, arguments)
            XCTAssertNil(failure)
            let keys = Set(["out", "bytes", "sha256", "session", "region", "job", "edition",
                            "year_span", "engine_version"])
            guard case .object(let object)? = data else { return XCTFail("no result") }
            XCTAssertTrue(Set(object.keys).isSubset(of: keys), "\(object.keys.sorted())")
            let text = data?.text(pretty: false) ?? ""
            for word in ["tracks", "prefill", "px", "proof_form", "starter_crop", "hotspots", "files"] {
                XCTAssertFalse(text.contains(word), "\(word): \(text)")
            }
        }
    }

    func testContinueNoWaitReturnsTheJobAfterTheSubmit() async {
        let world = engine()
        let (data, failure) = await call("continue", world, ["file": lassen, "no_wait": .bool(true)])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls, ["POST /api/continue", "POST /api/proof", "POST /api/final/submit",
                                     "GET /api/debug/engine"])
        XCTAssertEqual(world.slept, [])
        XCTAssertEqual(world.written, [])
        XCTAssertEqual(data, .object([
            "session": .string("ab12"), "region": .string("lassen_ca"), "job": .string("cd34"),
            "edition": .int(2), "year_span": .string("2023"), "engine_version": .string("1.20.0"),
        ]))
    }

    func testAContinueCropWinsAndAPrintSizeAsksTheStarterCropRoute() async {
        let world = engine()
        var (_, failure) = await call("continue", world, [
            "file": lassen, "crop": .string("1,2,3.50,4"), "set": list("print_h=11"),
            "out": .string("/out/a.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(pairs(world, 1).prefix(5), ["session_id=ab12", "x0=1", "y0=2", "x1=3.50", "y1=4"])
        XCTAssertFalse(world.calls.contains { $0.contains("starter_crop") })

        // one size is named: the other one is the file's own, from proof_form
        world.serve("/api/debug/sessions/ab12/starter_crop?print_w=17&print_h=11", 200,
                    #"{"starter_crop":[9,8,7,6]}"#)
        (_, failure) = await call("continue", world, [
            "file": lassen, "set": list("print_h=11"), "out": .string("/out/b.png")])
        XCTAssertNil(failure)
        XCTAssertEqual(world.calls.suffix(8).prefix(4), [
            "GET /api/debug/forms", "POST /api/continue",
            "GET /api/debug/sessions/ab12/starter_crop?print_w=17&print_h=11", "POST /api/proof"])
        let proof = world.posts.last { $0.path == "/api/proof" }
        XCTAssertEqual(proof?.pairs.prefix(5), ["session_id=ab12", "x0=9", "y0=8", "x1=7", "y1=6"])
        XCTAssertTrue(proof?.pairs.contains("print_h=11") ?? false)
        XCTAssertTrue(proof?.pairs.contains("print_w=17") ?? false)
    }

    func testAContinueAnswerWithNoProofFormIsAnEnvironmentFailure() async {
        // an engine from before `proof_form`: the tool has no copy of the mapping
        let world = engine()
        world.serve("POST /api/continue", 200,
                    #"{"session":"ab12","region":"lassen_ca","starter_crop":[5,6,7,8],"edition":2}"#)
        var (_, failure) = await call("continue", world, ["file": lassen, "out": .string("/out/a.png")])
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertTrue(failure?.message.contains("proof_form") ?? false, failure?.message ?? "")

        world.serve("POST /api/continue", 200,
                    #"{"session":"ab/../12","starter_crop":[5,6,7,8],"proof_form":{}}"#)
        (_, failure) = await call("continue", world, ["file": lassen, "out": .string("/out/a.png")])
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertEqual(world.calls, ["POST /api/continue", "POST /api/continue"])
        XCTAssertEqual(world.written, [])
    }

    func testContinueOutFollowsTheRulesOfRenderFinal() async {
        let world = engine()
        world.existingFile("/out/old.png")
        var (_, failure) = await call("continue", world, ["file": lassen, "out": .string("/out/old.png")])
        XCTAssertEqual(failure, TecopaFailure(.usage, "A file is already at /out/old.png."))
        (_, failure) = await call("continue", world, ["file": lassen, "out": .string("/none/two.png")])
        XCTAssertEqual(failure, TecopaFailure(.usage, "The folder /none does not exist."))
        (_, failure) = await call("continue", world, ["file": lassen])
        XCTAssertTrue(failure?.message.hasPrefix("out is required") ?? false)
        (_, failure) = await call("continue", world, [
            "file": lassen, "no_wait": .bool(true), "out": .string("/out/two.png")])
        XCTAssertTrue(failure?.message.contains("no_wait") ?? false)

        (_, failure) = await call("reprint", world, ["file": lassen, "out": .string("/out/old.png")])
        XCTAssertEqual(failure, TecopaFailure(.usage, "A file is already at /out/old.png."))
        (_, failure) = await call("reprint", world, ["file": lassen, "out": .string("/none/again.png")])
        XCTAssertEqual(failure, TecopaFailure(.usage, "The folder /none does not exist."))
        XCTAssertEqual(world.calls, [])
    }

    // MARK: The plate

    /// One call of each path through the three entries. `flag` is the caller's
    /// `allow_plate_mismatch`, or nil when the caller gives none.
    private func everyPath(_ flag: JSONValue?) async -> [FakeWorld.Post] {
        var posts: [FakeWorld.Post] = []
        func run(_ name: String, _ arguments: [String: JSONValue], _ change: (FakeWorld) -> Void = { _ in }) async {
            let world = engine()
            change(world)
            var arguments = arguments
            arguments["file"] = lassen
            if let flag, name != "reprint_inspect" { arguments["allow_plate_mismatch"] = flag }
            _ = await call(name, world, arguments)
            XCTAssertFalse(world.posts.isEmpty, name)
            posts += world.posts
        }
        let out: JSONValue = .string("/out/a.png")
        await run("reprint_inspect", [:])
        await run("reprint", ["out": out])
        await run("reprint", ["out": out, "opt": list("format=pdf", "embed_spec=false")])
        await run("reprint", ["out": out]) { $0.serve("POST /api/reprint", 200, self.film) }
        await run("reprint", ["out": out, "no_wait": .bool(true)]) { $0.serve("POST /api/reprint", 200, self.film) }
        await run("reprint", ["out": out]) { $0.serve("POST /api/reprint", 422, self.mismatch) }
        await run("continue", ["out": out])
        await run("continue", ["out": out, "tracks": list("/tracks/new.gpx"), "set": list("title=Two"),
                               "opt": list("format=pdf"), "crop": .string("1,2,3,4")])
        await run("continue", ["no_wait": .bool(true)])
        await run("continue", ["out": out]) { $0.serve("POST /api/continue", 422, self.mismatch) }
        return posts
    }

    func testNoRequestCarriesAllowPlateMismatchUnlessTheArgumentIsTrue() async {
        for flag: JSONValue? in [nil, .bool(false)] {
            let posts = await everyPath(flag)
            // every route of the three entries is in the scan
            XCTAssertEqual(Set(posts.map(\.path)), [
                "/api/reprint/inspect", "/api/reprint", "/api/continue", "/api/upload", "/api/proof",
                "/api/final/submit"])
            for post in posts {
                let names = post.fields.map(\.name) + post.files.map(\.name)
                XCTAssertFalse(names.contains("allow_plate_mismatch"), "\(post.path): \(names)")
                XCTAssertFalse(post.pairs.joined().contains("allow_plate_mismatch"), post.path)
            }
        }

        // with true, the two routes that read the file get it, as `true`, and no other route
        for post in await everyPath(.bool(true)) {
            let sent = post.fields.filter { $0.name == "allow_plate_mismatch" }.map(\.value)
            let reads = post.path == "/api/reprint" || post.path == "/api/continue"
            XCTAssertEqual(sent, reads ? ["true"] : [], post.path)
        }
    }

    func testTheFlagIsAnArgumentAndNeverASetOrAnOpt() async {
        let world = engine()
        let out: JSONValue = .string("/out/a.png")
        let bad: [(String, [String: JSONValue])] = [
            ("reprint", ["opt": list("allow_plate_mismatch=true")]),
            ("reprint", ["opt": list("file=/etc/passwd")]),
            ("continue", ["opt": list("allow_plate_mismatch=true")]),
            ("continue", ["set": list("allow_plate_mismatch=true")]),
            ("continue", ["set": list("session_id=ef56")]),
        ]
        for (name, arguments) in bad {
            var arguments = arguments
            arguments["file"] = lassen
            arguments["out"] = out
            let (_, failure) = await call(name, world, arguments)
            XCTAssertEqual(failure?.kind, .usage, "\(name) \(arguments.keys.sorted())")
            XCTAssertTrue(failure?.message.contains("cannot name") ?? false, failure?.message ?? "")
        }
        // a boolean, as the catalog says
        let (_, failure) = await call("reprint", world, [
            "file": lassen, "out": out, "allow_plate_mismatch": .string("true")])
        XCTAssertEqual(failure?.message, "allow_plate_mismatch must be a boolean.")
        XCTAssertEqual(world.calls, [])
    }

    func testAPlateMismatch422PassesThroughUnchanged() async throws {
        let body = try JSONValue.parse(Data(mismatch.utf8))
        let world = engine()
        world.serve("POST /api/reprint", 422, mismatch)
        world.serve("POST /api/continue", 422, mismatch)
        for name in ["reprint", "continue"] {
            let (data, failure) = await call(name, world, ["file": lassen, "out": .string("/out/a.png")])
            XCTAssertNil(data, name)
            XCTAssertEqual(failure?.kind, .refused, name)
            XCTAssertEqual(failure?.status, 422, name)
            XCTAssertEqual(failure?.body, body, name)
        }
        // the tool does not send the flag for the caller, and it does not try again
        XCTAssertEqual(world.calls, ["POST /api/reprint", "POST /api/continue"])
        XCTAssertEqual(world.written, [])
    }

    // MARK: The arguments

    func testTheFileIsRequiredAbsoluteAndReadBeforeAnyRequest() async {
        let world = engine()
        world.binary("lassen.png", file)
        world.binary("new.gpx", Data("<gpx/>".utf8))
        let out: JSONValue = .string("/out/a.png")
        for name in ["reprint_inspect", "reprint", "continue"] {
            let base: [String: JSONValue] = name == "reprint_inspect" ? [:] : ["out": out]
            var (_, failure) = await call(name, world, base)
            XCTAssertEqual(failure?.kind, .usage, name)
            XCTAssertTrue(failure?.message.hasPrefix("file is required") ?? false, name)

            for path in ["lassen.png", "~/lassen.png", "./lassen.png"] {
                (_, failure) = await call(name, world, base.merging(["file": .string(path)]) { _, new in new })
                XCTAssertEqual(failure, TecopaFailure(.usage, "file must be an absolute path: \(path)"), name)
            }
            (_, failure) = await call(name, world, base.merging(["file": .string("/posters/none.png")]) { _, new in new })
            XCTAssertEqual(failure, TecopaFailure(.usage, "Cannot read the poster file: /posters/none.png"), name)
        }
        // the new tracks and the output of a continue follow the same rule
        var (_, failure) = await call("continue", world, ["file": lassen, "tracks": list("new.gpx"), "out": out])
        XCTAssertEqual(failure, TecopaFailure(.usage, "tracks must be an absolute path: new.gpx"))
        (_, failure) = await call("continue", world, ["file": lassen, "tracks": list("/tracks/none.gpx"), "out": out])
        XCTAssertEqual(failure, TecopaFailure(.usage, "Cannot read the track file: /tracks/none.gpx"))
        for name in ["reprint", "continue"] {
            (_, failure) = await call(name, world, ["file": lassen, "out": .string("a.png")])
            XCTAssertEqual(failure, TecopaFailure(.usage, "out must be an absolute path: a.png"), name)
        }
        (_, failure) = await call("continue", world, ["file": lassen, "crop": .string("1,2,3"), "out": out])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertEqual(world.calls, [])
    }

    func testOnlyReprintInspectIsReadOnly() {
        XCTAssertEqual(Catalog.named("reprint_inspect")?.readOnly, true)
        XCTAssertEqual(Catalog.named("reprint")?.readOnly, false)
        XCTAssertEqual(Catalog.named("continue")?.readOnly, false)
        func parameters(_ name: String) -> [String] {
            (Catalog.named(name)?.parameters ?? []).map(\.name)
        }
        XCTAssertEqual(parameters("reprint_inspect"), ["file"])
        XCTAssertEqual(parameters("reprint"), ["file", "out", "opt", "allow_plate_mismatch", "no_wait"])
        XCTAssertEqual(parameters("continue"),
                       ["file", "tracks", "set", "opt", "crop", "out", "allow_plate_mismatch", "no_wait"])
    }

    func testTheTextOfAContinueResultNamesTheEdition() {
        let result: JSONValue = .object([
            "out": .string("/out/two.png"), "bytes": .int(9), "sha256": .string("ab"),
            "session": .string("ab12"), "job": .string("cd34"), "region": .string("lassen_ca"),
            "engine_version": .string("1.20.0"), "edition": .int(2), "year_span": .string("2023"),
        ])
        XCTAssertEqual(Catalog.named("continue")?.text?(result), """
            out: /out/two.png
            bytes: 9
            sha256: ab
            session: ab12
            job: cd34
            region: lassen_ca
            engine_version: 1.20.0
            edition: 2
            year_span: 2023
            """)
        // the inspection is the engine's own answer, so it prints as JSON
        XCTAssertNil(Catalog.named("reprint_inspect")?.text)
    }
}
