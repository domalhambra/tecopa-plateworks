import XCTest
@testable import TecopaKit

/// The `plate` entries on the fake machine: the exact command of each, the venv
/// that runs it, the three guards on `sources.json`, and the flags that the tool
/// never passes.
final class PlatesTests: XCTestCase {
    private let runs = "/home/Library/Application Support/TecopaPlateworks/runs"
    /// The id of a start at the fake's default clock and digits.
    private let run = "20261010-185515-a1b2c3"
    private let app = "/repo/.venv/bin/python"
    private let prep = "/repo/.venv-prep/bin/python"

    private func call(_ name: String, _ world: FakeWorld,
                      _ arguments: [String: JSONValue] = [:]) async -> (data: JSONValue?, failure: TecopaFailure?) {
        let (envelope, failure) = await Catalog.call(name, world.runtime(), arguments)
        return (envelope["data"], failure)
    }

    /// The program and the arguments of each detached start, without the shell around them.
    private func started(_ world: FakeWorld) -> [[String]] {
        world.detached.map { Array($0.arguments.dropFirst(5)) }
    }

    /// The record that a tracked start wrote. The run's empty log is written before it.
    private func record(_ world: FakeWorld) throws -> JSONValue {
        try JSONValue.parse(try XCTUnwrap(world.written.first { $0.path.hasSuffix(".json") }).data)
    }

    /// What `ScriptRunner.start` returns for a start at the fake's default clock.
    private var startResult: JSONValue {
        .object(["run": .string(run), "pid": .int(4001), "log": .string("\(runs)/\(run).log"),
                 "hint": .string("Run `tecopa runs show \(run)`.")])
    }

    /// A `sources.json` that lists these assets.
    private func sources(_ assets: [String]) -> String {
        JSONValue.object([
            "region_id": .string("lassen_ca"),
            "assets": .object(Dictionary(uniqueKeysWithValues: assets.map {
                ($0, JSONValue.object(["sha256": .string("ab12"), "bytes": .int(7)]))
            })),
        ]).text()
    }

    /// A plate that is built: its folder, and a `sources.json` with these assets.
    private func plate(_ world: FakeWorld, _ id: String = "lassen_ca", assets: [String] = ["dem.tif"]) {
        world.folder("/repo/regions/\(id)")
        world.file("/repo/regions/\(id)/sources.json", sources(assets))
    }

    private let build: [String: JSONValue] = [
        "id": .string("lassen_ca"), "name": .string("Lassen Volcanic"),
        "bbox": .array([.string("-121.6"), .string("40.3"), .string("-121.2"), .string("40.6")]),
        "epsg": .int(32610),
    ]

    /// Nothing ran, nothing started and nothing was written.
    private func assertNothingHappened(_ world: FakeWorld, _ message: String = "",
                                       file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(world.commands, [], message, file: file, line: line)
        XCTAssertEqual(world.detached, [], message, file: file, line: line)
        XCTAssertEqual(world.written, [], message, file: file, line: line)
        XCTAssertEqual(world.madeFolders, [], message, file: file, line: line)
        XCTAssertEqual(world.calls, [], message, file: file, line: line)
    }

    // MARK: The script table

    func testThePrepStackRunsOnlyInThePrepVenv() {
        // CLAUDE.md, invariant 13: region_prep.py and the playa bake import the
        // region-prep stack, and that stack never enters .venv. No other row is prep.
        XCTAssertEqual(ScriptRunner.table["region_prep.py"], .script(.prep))
        XCTAssertEqual(ScriptRunner.table["scripts/bake_playa.py"], .script(.prep))
        let inPrep = Set(ScriptRunner.table.filter { $0.value.venv == .prep }.keys)
        XCTAssertEqual(inPrep, ["region_prep.py", "scripts/bake_playa.py"])
    }

    func testThePlateRowsOfTheScriptTable() {
        XCTAssertEqual(ScriptRunner.table["scripts/build_labels.py"], .script(.app))
        XCTAssertEqual(ScriptRunner.table["scripts/pack_region.py"], .script(.app))
        // `python -m app.plates` is a module, not a path under the repo
        XCTAssertEqual(ScriptRunner.table["app.plates"], .module(.app))
        // plan decision 17: no command runs dem_coverage.py, so it has no row
        XCTAssertNil(ScriptRunner.table["scripts/dem_coverage.py"])
    }

    func testWithNoPrepVenvAPrepScriptDoesNotStartInTheAppVenv() async {
        let world = FakeWorld()
        plate(world, "rifle_aspen")
        var runtime = world.runtime()
        runtime.fileExists = { !$0.hasSuffix("/.venv-prep/bin/python") }
        for (name, arguments) in [("plate_build", build), ("plate_playa", ["id": .string("rifle_aspen")])] {
            let (_, failure) = await Catalog.call(name, runtime, arguments)
            XCTAssertEqual(failure?.kind, .environment, name)
            XCTAssertEqual(failure?.message, "No interpreter at /repo/.venv-prep/bin/python.", name)
        }
        assertNothingHappened(world)
    }

    // MARK: plate plan

    func testPlatePlanPostsEachTrackAndReturnsTheEnginesAnswerUnchanged() async throws {
        let world = FakeWorld()
        world.binary("/t/day one.gpx", Data("<gpx/>".utf8))
        world.binary("/t/two.kml", Data("<kml></kml>".utf8))
        let answer = #"{"us_covered":true,"bbox":[-121.6,40.3,-121.2,40.6],"epsg":32610,"#
            + #""name_prefill":"Day One","id":"day_one","prep_ready":true,"resolution_m":10,"#
            + #""grid":[3400,3300],"grid_mpx":11.22,"est_dem_mb":44.9,"n_slices":1,"over_budget":false}"#
        world.serve("POST /api/regions/plan", 200, answer)

        let (data, failure) = await call(
            "plate_plan", world, ["tracks": .array([.string("/t/day one.gpx"), .string("/t/two.kml")])])
        XCTAssertNil(failure)
        XCTAssertEqual(data, try JSONValue.parse(Data(answer.utf8)))
        // one request: one `files` part for each track, and no field
        XCTAssertEqual(world.calls, ["POST /api/regions/plan"])
        XCTAssertEqual(world.posts, [.init(path: "/api/regions/plan", fields: [], files: [
            .init(name: "files", filename: "day one.gpx", bytes: 6),
            .init(name: "files", filename: "two.kml", bytes: 11),
        ])])
        // it reads only: no script, no run, no file
        XCTAssertEqual(world.commands, [])
        XCTAssertEqual(world.detached, [])
        XCTAssertEqual(world.written, [])
    }

    func testPlatePlanNeedsAbsoluteTracksThatCanBeRead() async {
        let world = FakeWorld()
        world.binary("/t/a.gpx", Data("<gpx/>".utf8))
        world.serve("POST /api/regions/plan", 200, "{}")
        var (_, failure) = await call("plate_plan", world)
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertTrue(failure?.message.hasPrefix("tracks is required") ?? false, failure?.message ?? "")
        (_, failure) = await call("plate_plan", world, ["tracks": .array([])])
        XCTAssertEqual(failure?.kind, .usage)
        (_, failure) = await call("plate_plan", world, ["tracks": .array([.string("/t/a.gpx"), .string("b.gpx")])])
        XCTAssertEqual(failure, TecopaFailure(.usage, "tracks must be an absolute path: b.gpx"))
        (_, failure) = await call("plate_plan", world, ["tracks": .array([.string("/t/a.gpx"), .string("/t/none.gpx")])])
        XCTAssertEqual(failure, TecopaFailure(.usage, "Cannot read the track file: /t/none.gpx"))
        // this route takes no session and no region
        for name in ["session", "session_id", "region", "region_id"] {
            (_, failure) = await call("plate_plan", world,
                                      ["tracks": .array([.string("/t/a.gpx")]), name: .string("ab12")])
            XCTAssertEqual(failure?.kind, .usage, name)
        }
        assertNothingHappened(world)
    }

    func testPlatePlanPassesTheEnginesRefusalThrough() async {
        let world = FakeWorld()
        world.binary("/t/a.gpx", Data("<gpx/>".utf8))
        world.serve("POST /api/regions/plan", 422, #"{"detail":"No track points found in the dropped files"}"#)
        let (data, failure) = await call("plate_plan", world, ["tracks": .array([.string("/t/a.gpx")])])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(failure?.status, 422)
        XCTAssertEqual(failure?.body, .object(["detail": .string("No track points found in the dropped files")]))
    }

    // MARK: plate build

    func testPlateBuildStartsRegionPrepInThePrepVenvAsATrackedRun() async throws {
        let world = FakeWorld()
        let (data, failure) = await call("plate_build", world, build)
        XCTAssertNil(failure)
        // a negative longitude is one argument of its own, as the caller wrote it
        XCTAssertEqual(started(world), [[
            prep, "region_prep.py", "--id", "lassen_ca", "--name", "Lassen Volcanic",
            "--bbox", "-121.6", "40.3", "-121.2", "40.6", "--epsg", "32610",
        ]])
        XCTAssertEqual(world.detached.first?.executable, "/bin/sh")
        XCTAssertEqual(world.detached.first?.cwd, "/repo")
        let written = try record(world)
        XCTAssertEqual(written["command"]?.stringValue, "plate_build")
        XCTAssertEqual(written["cwd"]?.stringValue, "/repo")
        XCTAssertEqual(written["failure_text"], .null)
        XCTAssertEqual(written["argv"]?.arrayValue?.first?.stringValue, prep)
        // the call returns at once, with the run and the next command
        XCTAssertEqual(data, startResult)
        XCTAssertEqual(world.commands, [])
        XCTAssertEqual(world.slept, [])
    }

    func testPlateBuildSendsTheResolutionOnlyWhenItIsGiven() async {
        for (given, sent) in [("auto", ["--resolution", "auto"]), ("55", ["--resolution", "55"]),
                              ("7.5", ["--resolution", "7.5"])] {
            let world = FakeWorld()
            var arguments = build
            arguments["resolution"] = .string(given)
            let (_, failure) = await call("plate_build", world, arguments)
            XCTAssertNil(failure, given)
            XCTAssertEqual(started(world).first?.suffix(4).map { $0 }, ["--epsg", "32610"] + sent, given)
        }
        // without it, the script's own default applies: the tool has none
        let world = FakeWorld()
        _ = await call("plate_build", world, build)
        XCTAssertFalse(started(world).first?.contains("--resolution") ?? true)
    }

    func testPlateBuildSendsEachValueAsTheCallerWroteIt() async {
        // the tool checks the form and owns no range: 400 degrees is the script's to refuse
        let world = FakeWorld()
        var arguments = build
        arguments["bbox"] = .array([.string("-121.60"), .string("+40"), .string("4e2"), .string(".5")])
        arguments["epsg"] = .double(2227.0)
        arguments["name"] = .string("Lassen — the \"north\" $(half); é")
        let (_, failure) = await call("plate_build", world, arguments)
        XCTAssertNil(failure)
        XCTAssertEqual(started(world), [[
            prep, "region_prep.py", "--id", "lassen_ca", "--name", "Lassen — the \"north\" $(half); é",
            "--bbox", "-121.60", "+40", "4e2", ".5", "--epsg", "2227",
        ]])
    }

    func testPlateBuildRefusesAPlateThatExistsAndStartsNothing() async {
        // plan decision 11: region_prep.py writes sources.json whole, so a build
        // over a plate would re-stamp it (CLAUDE.md, invariant 12)
        let folder = FakeWorld()
        folder.folder("/repo/regions/lassen_ca")
        // a failed build leaves a partial folder, and anything at the path counts
        let file = FakeWorld()
        file.existingFile("/repo/regions/lassen_ca")
        for world in [folder, file] {
            let (data, failure) = await call("plate_build", world, build)
            XCTAssertNil(data)
            XCTAssertEqual(failure?.kind, .refused)
            XCTAssertEqual(failure?.message,
                           "The plate lassen_ca exists. A build would write its sources.json again.")
            XCTAssertTrue(failure?.hint?.contains("invariant 12") ?? false, failure?.hint ?? "")
            assertNothingHappened(world)
        }
        // another plate is no reason to refuse
        let other = FakeWorld()
        other.folder("/repo/regions/lassen_ca_2")
        other.folder("/repo/regions")
        let (_, failure) = await call("plate_build", other, build)
        XCTAssertNil(failure)
        XCTAssertEqual(other.detached.count, 1)
    }

    func testPlateBuildChecksTheFormOfEachValue() async {
        func bbox(_ values: String...) -> JSONValue { .array(values.map { .string($0) }) }
        var cases: [(String, [String: JSONValue?])] = [
            // an id is the engine's own alphabet
            ("id", ["id": .string("Lassen")]), ("id", ["id": .string("--out-root")]),
            ("id", ["id": .string("../lassen")]), ("id", ["id": .string("")]), ("id", ["id": nil]),
            ("id", ["id": .string("lassen ca")]), ("id", ["id": .string(String(repeating: "a", count: 65))]),
            // a name that starts with a hyphen would be read as a flag
            ("name", ["name": .string("")]), ("name", ["name": nil]), ("name", ["name": .string("-x")]),
            ("name", ["name": .string("--replace")]), ("name", ["name": .string("--out-root=/tmp")]),
            // exactly four values, each one finite number
            ("bbox", ["bbox": nil]), ("bbox", ["bbox": bbox()]),
            ("bbox", ["bbox": bbox("-121.6", "40.3", "-121.2")]),
            ("bbox", ["bbox": bbox("-121.6", "40.3", "-121.2", "40.6", "1")]),
            ("bbox", ["bbox": bbox("-121.6,40.3,-121.2,40.6")]),
            ("bbox", ["bbox": bbox("-121.6 40.3", "-121.2", "40.6", "1")]),
            ("epsg", ["epsg": nil]),
        ]
        for bad in ["", "west", "nan", "inf", "-inf", "infinity", "0x10", "1 2", " 1", "1\n", "--out", "-",
                    "1e999", "１", "1,2", "--resolution", "-e"] {
            cases.append(("bbox", ["bbox": bbox("-121.6", bad, "-121.2", "40.6")]))
        }
        for bad in ["", "fine", "Auto", "nan", "-inf", "--out", "auto ", "10 m", "0x10", "-"] {
            cases.append(("resolution", ["resolution": .string(bad)]))
        }
        let world = FakeWorld()
        for (name, change) in cases {
            var arguments = build
            for (key, value) in change { arguments[key] = value }
            let (data, failure) = await call("plate_build", world, arguments)
            XCTAssertNil(data, "\(change)")
            XCTAssertEqual(failure?.kind, .usage, "\(change)")
            XCTAssertTrue(failure?.message.contains(name) ?? false, "\(change): \(failure?.message ?? "")")
        }
        // the catalog itself refuses a value of the wrong kind
        for (key, value, said) in [
            ("epsg", JSONValue.string("32610"), "epsg must be an integer."),
            ("epsg", .double(32610.5), "epsg must be an integer."),
            ("bbox", .string("-121.6,40.3,-121.2,40.6"), "bbox must be a list of strings."),
            ("bbox", .array([.double(-121.6), .double(40.3), .double(-121.2), .double(40.6)]),
             "bbox must be a list of strings."),
            ("resolution", .int(10), "resolution must be a string."),
        ] {
            var arguments = build
            arguments[key] = value
            let (_, failure) = await call("plate_build", world, arguments)
            XCTAssertEqual(failure, TecopaFailure(.usage, said), key)
        }
        assertNothingHappened(world)
    }

    // MARK: plate labels and plate playa

    func testPlateLabelsStartsBuildLabelsInTheAppVenvAsATrackedRun() async throws {
        let world = FakeWorld()
        plate(world, assets: ["dem.tif", "hydro.json", "playa.json"])
        let (data, failure) = await call("plate_labels", world, ["id": .string("lassen_ca")])
        XCTAssertNil(failure)
        XCTAssertEqual(started(world), [[app, "scripts/build_labels.py", "lassen_ca"]])
        XCTAssertEqual(world.detached.first?.cwd, "/repo")
        let written = try record(world)
        XCTAssertEqual(written["command"]?.stringValue, "plate_labels")
        XCTAssertEqual(written["failure_text"], .null)
        XCTAssertEqual(data, startResult)
        XCTAssertEqual(world.commands, [])
    }

    func testPlatePlayaStartsBakePlayaInThePrepVenvWithItsFailureText() async throws {
        let world = FakeWorld()
        plate(world, assets: ["dem.tif", "labels.json"])
        let (data, failure) = await call("plate_playa", world, ["id": .string("lassen_ca")])
        XCTAssertNil(failure)
        XCTAssertEqual(started(world), [[prep, "scripts/bake_playa.py", "lassen_ca"]])
        XCTAssertEqual(world.detached.first?.cwd, "/repo")
        let written = try record(world)
        XCTAssertEqual(written["command"]?.stringValue, "plate_playa")
        // plan decision 16: the script exits 0 when a plate fails, and prints this
        XCTAssertEqual(written["failure_text"]?.stringValue, "FAILED")
        XCTAssertEqual(data, startResult)
        XCTAssertEqual(world.commands, [])
    }

    func testABakeRefusesAPlateThatIsNotBuilt() async {
        for name in ["plate_labels", "plate_playa"] {
            // no folder at all, and a folder that a failed build left with no sources.json
            let none = FakeWorld()
            let partial = FakeWorld()
            partial.folder("/repo/regions/lassen_ca")
            partial.file("/repo/regions/lassen_ca/region.json", "{}")
            for world in [none, partial] {
                let (data, failure) = await call(name, world, ["id": .string("lassen_ca")])
                XCTAssertNil(data, name)
                XCTAssertEqual(failure?.kind, .refused, name)
                XCTAssertEqual(failure?.message, "The plate lassen_ca is not built.", name)
                assertNothingHappened(world, name)
            }
        }
    }

    func testABakeRefusesASourcesFileThatItCannotRead() async {
        // a file the tool cannot read is a refusal, never a pass: it could list the asset
        let unreadable = [
            "", "not json", #"{"assets": {"dem.tif": "#, "[]", #""assets""#, "null", "7",
            #"{"region_id": "lassen_ca"}"#, #"{"assets": null}"#, #"{"assets": []}"#,
            #"{"assets": "labels.json"}"#, #"{"assets": ["labels.json", "playa.json"]}"#,
        ]
        for name in ["plate_labels", "plate_playa"] {
            for text in unreadable {
                let world = FakeWorld()
                world.folder("/repo/regions/lassen_ca")
                world.file("/repo/regions/lassen_ca/sources.json", text)
                let (data, failure) = await call(name, world, ["id": .string("lassen_ca")])
                XCTAssertNil(data, "\(name) \(text)")
                XCTAssertEqual(failure?.kind, .refused, "\(name) \(text)")
                XCTAssertTrue(failure?.message.contains("/repo/regions/lassen_ca/sources.json") ?? false,
                              "\(name) \(text): \(failure?.message ?? "")")
                assertNothingHappened(world, "\(name) \(text)")
            }
            // a file that is there and gives no text
            let world = FakeWorld()
            world.existingFile("/repo/regions/lassen_ca/sources.json")
            let (_, failure) = await call(name, world, ["id": .string("lassen_ca")])
            XCTAssertEqual(failure?.kind, .refused, name)
            XCTAssertEqual(failure?.message,
                           "The file /repo/regions/lassen_ca/sources.json cannot be read.", name)
            assertNothingHappened(world, name)
        }
    }

    func testABakeRefusesAnEntryThatSourcesAlreadyLists() async {
        // plan decision 11: a command creates an entry of sources.json and never
        // replaces one, so a drifted asset stays drifted (CLAUDE.md, invariant 12)
        for (name, asset, other) in [("plate_labels", "labels.json", "plate_playa"),
                                     ("plate_playa", "playa.json", "plate_labels")] {
            let world = FakeWorld()
            plate(world, assets: ["dem.tif", asset])
            let (data, failure) = await call(name, world, ["id": .string("lassen_ca")])
            XCTAssertNil(data, name)
            XCTAssertEqual(failure?.kind, .refused, name)
            XCTAssertEqual(
                failure?.message,
                "The plate lassen_ca already lists \(asset). A second bake would replace the entry.", name)
            XCTAssertTrue(failure?.hint?.contains("invariant 12") ?? false, failure?.hint ?? "")
            assertNothingHappened(world, name)

            // the other bake reads only its own entry
            let (_, passed) = await call(other, world, ["id": .string("lassen_ca")])
            XCTAssertNil(passed, other)
            XCTAssertEqual(world.detached.count, 1, other)
        }
        // an entry with any value is an entry, a null included
        let world = FakeWorld()
        world.file("/repo/regions/lassen_ca/sources.json", #"{"assets": {"labels.json": null, "playa.json": {}}}"#)
        for name in ["plate_labels", "plate_playa"] {
            let (_, failure) = await call(name, world, ["id": .string("lassen_ca")])
            XCTAssertEqual(failure?.kind, .refused, name)
        }
        assertNothingHappened(world)
    }

    func testEachCommandThatTakesAnIdChecksIt() async {
        // build_labels.py reads any token as a region id, a flag included
        let world = FakeWorld()
        plate(world)
        let bad = ["--root", "--root=/tmp", "Lassen", "lassen-ca", "../lassen_ca", "lassen_ca/", "", " ",
                   "lassen_ca rifle_aspen", "--resync", "é"]
        for name in ["plate_labels", "plate_playa", "plate_pack"] {
            for id in bad {
                let (data, failure) = await call(name, world, ["id": .string(id)])
                XCTAssertNil(data, "\(name) \(id)")
                XCTAssertEqual(failure?.kind, .usage, "\(name) \(id)")
            }
            let (_, failure) = await call(name, world)
            XCTAssertEqual(failure, TecopaFailure(.usage, "id is required: a region id."), name)
        }
        assertNothingHappened(world)
    }

    // MARK: plate pack

    func testPlatePackRunsPackRegionInTheCall() async {
        let world = FakeWorld()
        world.result(for: "python", ProcessResult(
            exitCode: 0, stdout: "plates/lassen_ca-1a2b3c4d5e6f.trailplate.zip\n", stderr: ""))
        var (data, failure) = await call("plate_pack", world, ["id": .string("lassen_ca")])
        XCTAssertNil(failure)
        XCTAssertEqual(data, .object([
            "packed": .bool(true), "output": .string("plates/lassen_ca-1a2b3c4d5e6f.trailplate.zip")]))
        // plan decision 13: --resync only when the caller gives it as true
        (data, failure) = await call("plate_pack", world, ["id": .string("lassen_ca"), "resync": .bool(false)])
        XCTAssertNil(failure)
        (data, failure) = await call("plate_pack", world, ["id": .string("lassen_ca"), "resync": .bool(true)])
        XCTAssertNil(failure)
        XCTAssertEqual(world.commands, [
            [app, "scripts/pack_region.py", "lassen_ca"],
            [app, "scripts/pack_region.py", "lassen_ca"],
            [app, "scripts/pack_region.py", "lassen_ca", "--resync"],
        ])
        XCTAssertEqual(world.workingDirectories, ["/repo", "/repo", "/repo"])
        // in the call: no tracked run
        XCTAssertEqual(world.detached, [])
        XCTAssertEqual(world.written, [])
    }

    func testPlatePackExit2IsRefusedWithTheScriptsOwnWords() async {
        let said = """
            refusing to pack lassen_ca: assets have drifted from sources.json:
              dem.tif  sha256 1a2b… != 9f8e…
            rerun the region build (region_prep.py) or scripts/build_labels.py to resync the sidecar
            """
        let world = FakeWorld()
        world.result(for: "python", ProcessResult(exitCode: 2, stdout: "", stderr: said + "\n"))
        let (data, failure) = await call("plate_pack", world, ["id": .string("lassen_ca")])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(failure?.message,
                       "pack_region.py refused: refusing to pack lassen_ca: assets have drifted from sources.json:")
        XCTAssertEqual(failure?.body?["stderr"]?.stringValue, said)
        XCTAssertEqual(failure?.body?["exit_code"]?.intValue, 2)
        // the tool does not try again with --resync
        XCTAssertEqual(world.commands.count, 1)
    }

    func testPlatePackThatCrashesOrExitsWithAnotherCodeIsAnEnvironmentFailure() async {
        let trace = """
            Traceback (most recent call last):
              File "scripts/pack_region.py", line 258, in <module>
                sys.exit(main())
            ModuleNotFoundError: No module named 'app'
            """
        for (code, stderr, message) in [
            (Int32(1), trace, "pack_region.py crashed: ModuleNotFoundError: No module named 'app'"),
            // a crash is a crash whatever the exit code
            (2, trace, "pack_region.py crashed: ModuleNotFoundError: No module named 'app'"),
            (1, "killed", "pack_region.py exited 1: killed"),
            (137, "", "pack_region.py exited 137."),
        ] {
            let world = FakeWorld()
            world.result(for: "python", ProcessResult(exitCode: code, stdout: "", stderr: stderr))
            let (data, failure) = await call("plate_pack", world, ["id": .string("lassen_ca")])
            XCTAssertNil(data, message)
            XCTAssertEqual(failure?.kind, .environment, message)
            XCTAssertEqual(failure?.message, message)
            XCTAssertEqual(failure?.body?["stderr"]?.stringValue, stderr, message)
        }
    }

    // MARK: plate install

    private let zip = "/dl/lassen_ca-1a2b3c4d5e6f.trailplate.zip"

    func testPlateInstallRunsTheModuleWithTheLocalFile() async {
        let world = FakeWorld()
        world.existingFile(zip)
        let said = "plate lassen_ca verified:\n  dem.tif  sha256 1a2b3c4d5e6f… ok\n"
            + "lassen_ca installed — /readyz will confirm bounds\n"
        world.result(for: "python", ProcessResult(exitCode: 0, stdout: said, stderr: ""))
        let (data, failure) = await call("plate_install", world, ["file": .string(zip)])
        XCTAssertNil(failure)
        XCTAssertEqual(data, .object([
            "installed": .bool(true),
            "output": .string(said.trimmingCharacters(in: .whitespacesAndNewlines))]))
        XCTAssertEqual(world.commands, [[app, "-m", "app.plates", "install", zip]])
        XCTAssertEqual(world.workingDirectories, ["/repo"])
        XCTAssertEqual(world.detached, [])
        XCTAssertEqual(world.written, [])
    }

    func testPlateInstallTakesALocalFileOnly() async {
        // plan decision 12: a URL makes the script download up to 2 GiB
        let world = FakeWorld()
        world.existingFile(zip)
        world.existingFile("/dl/lassen_ca.zip")
        world.existingFile("/dl/https://plates.example/lassen_ca.trailplate.zip")
        world.folder("/dl/folder.trailplate.zip")
        let urls = ["https://plates.example/lassen_ca.trailplate.zip", "http://127.0.0.1/a.trailplate.zip",
                    "HTTPS://plates.example/a.trailplate.zip", "http:/a.trailplate.zip", "https:a.trailplate.zip",
                    "file:///dl/lassen_ca-1a2b3c4d5e6f.trailplate.zip", "ftp://h/a.trailplate.zip",
                    "/dl/https://plates.example/lassen_ca.trailplate.zip"]
        for url in urls {
            let (data, failure) = await call("plate_install", world, ["file": .string(url)])
            XCTAssertNil(data, url)
            XCTAssertEqual(failure?.kind, .usage, url)
            XCTAssertTrue(failure?.message.hasPrefix("plate install takes a local file.") ?? false,
                          "\(url): \(failure?.message ?? "")")
        }
        let refused: [(String?, String)] = [
            (nil, "file is required: the path of a .trailplate.zip file."),
            ("", "file is required: the path of a .trailplate.zip file."),
            ("lassen_ca.trailplate.zip", "file must be an absolute path: lassen_ca.trailplate.zip"),
            ("--replace", "file must be an absolute path: --replace"),
            ("/dl/lassen_ca.zip", "file must be a .trailplate.zip file: /dl/lassen_ca.zip"),
            ("/dl/none.trailplate.zip", "No file at /dl/none.trailplate.zip."),
            ("/dl/folder.trailplate.zip", "/dl/folder.trailplate.zip is a folder, not a file."),
        ]
        for (file, said) in refused {
            let (data, failure) = await call("plate_install", world, file.map { ["file": .string($0)] } ?? [:])
            XCTAssertNil(data, said)
            XCTAssertEqual(failure, TecopaFailure(.usage, said))
        }
        // the entry has no argument for the flag that deletes the installed plate
        for name in ["replace", "root"] {
            let (_, failure) = await call("plate_install", world, ["file": .string(zip), name: .bool(true)])
            XCTAssertEqual(failure?.kind, .usage, name)
            XCTAssertTrue(failure?.message.hasPrefix("Unknown argument for plate_install") ?? false)
        }
        assertNothingHappened(world)
    }

    func testPlateInstallExit1IsRefusedWithTheScriptsOwnWords() async {
        let world = FakeWorld()
        world.existingFile(zip)
        let said = "regions/lassen_ca already exists — pass --replace to swap in this plate"
        world.result(for: "python", ProcessResult(exitCode: 1, stdout: "", stderr: said + "\n"))
        let (data, failure) = await call("plate_install", world, ["file": .string(zip)])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(failure?.message, "app.plates install refused: " + said)
        XCTAssertEqual(failure?.body?["stderr"]?.stringValue, said)
        // the script names a flag that the tool does not have, so the hint says so
        XCTAssertEqual(failure?.hint, "The tool never passes --replace: it deletes the installed plate.")
        // and the tool did not run the script again with it
        XCTAssertEqual(world.commands, [[app, "-m", "app.plates", "install", zip]])

        // another refusal has no such hint
        world.result(for: "python", ProcessResult(exitCode: 1, stdout: "", stderr: "the zip is empty — not a plate\n"))
        let (_, empty) = await call("plate_install", world, ["file": .string(zip)])
        XCTAssertEqual(empty?.kind, .refused)
        XCTAssertNil(empty?.hint)
    }

    func testPlateInstallThatCrashesOrExitsWithAnotherCodeIsAnEnvironmentFailure() async {
        let trace = "Traceback (most recent call last):\n  File \"app/plates.py\", line 300\nKeyError: 'assets'\n"
        for (code, stderr, message) in [
            (Int32(1), trace, "app.plates install crashed: KeyError: 'assets'"),
            (2, "usage: python -m app.plates [-h] {install,verify} ...", "app.plates install exited 2: usage: python -m app.plates [-h] {install,verify} ..."),
        ] {
            let world = FakeWorld()
            world.existingFile(zip)
            world.result(for: "python", ProcessResult(exitCode: code, stdout: "", stderr: stderr))
            let (data, failure) = await call("plate_install", world, ["file": .string(zip)])
            XCTAssertNil(data, message)
            XCTAssertEqual(failure?.kind, .environment, message)
            XCTAssertEqual(failure?.message, message)
        }
    }

    // MARK: plate check

    func testPlateCheckRunsVerifyAndReportsTheVerdictWithTheScriptsOwnWords() async {
        // the script prints one line for each asset, and its verdict last
        let verified = "  dem.tif  sha256 1a2b3c4d5e6f… ok\n  labels.json  sha256 0f9e8d7c6b5a… ok\n"
            + "verified — lassen_ca plate 1a2b3c4d5e6f is the one this poster was painted on\n"
        let mismatch = "  dem.tif  poster 1a2b3c4d5e6f != installed 9f8e7d6c5b4a\n"
            + "mismatch — this poster was painted on plate 1a2b3c4d5e6f; regions has 9f8e7d6c5b4a — "
            + "install the original plate to reprint exactly\n"
        let cases: [(Int32, String, Bool)] = [
            (0, verified, true),
            // exit 0 too, and not verified: the file is older than the block
            (0, "unverifiable (pre-pack poster)\n", false),
            // exit 1 is the answer, as drift is the answer of `regions verify`
            (1, mismatch, false),
            (1, "region 'lassen_ca' not installed — install its plate "
                + "(python -m app.plates install <plate>) and verify again\n", false),
            (1, "/p/lassen.png carries no Tecopa Plateworks manifest — only PNG finals exported "
                + "with reprint data embedded can name their plate\n", false),
            // the word in an asset line, or with a non-zero exit, is not the verdict
            (0, "verified — a\n  dem.tif  poster 1a != installed 9f\n", false),
            (1, verified, false),
        ]
        for (code, stdout, verdict) in cases {
            let world = FakeWorld()
            world.result(for: "python", ProcessResult(exitCode: code, stdout: stdout, stderr: ""))
            let (data, failure) = await call("plate_check", world, ["poster": .string("/p/lassen.png")])
            XCTAssertNil(failure, stdout)
            XCTAssertEqual(data, .object([
                "verified": .bool(verdict),
                "output": .string(stdout.trimmingCharacters(in: .newlines))]), stdout)
            XCTAssertEqual(world.commands, [[app, "-m", "app.plates", "verify", "/p/lassen.png"]])
            XCTAssertEqual(world.workingDirectories, ["/repo"])
            XCTAssertEqual(world.detached, [])
            XCTAssertEqual(world.written, [])
        }
    }

    func testPlateCheckWithNoVerdictIsNotAnAnswer() async {
        // The script catches an OSError, prints it on stderr and exits 1, with
        // nothing on stdout. That is not "the poster does not match".
        let world = FakeWorld()
        let said = "FileNotFoundError: [Errno 2] No such file or directory: '/p/none.png'"
        world.result(for: "python", ProcessResult(exitCode: 1, stdout: "", stderr: said + "\n"))
        var (data, failure) = await call("plate_check", world, ["poster": .string("/p/none.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(failure?.message, "app.plates verify refused: " + said)
        XCTAssertEqual(failure?.body?["stderr"]?.stringValue, said)

        let trace = "Traceback (most recent call last):\n  File \"app/plates.py\", line 216\nKeyError: 'spec'\n"
        world.result(for: "python", ProcessResult(exitCode: 1, stdout: "  dem.tif  sha256 1a… ok\n", stderr: trace))
        (data, failure) = await call("plate_check", world, ["poster": .string("/p/lassen.png")])
        XCTAssertNil(data)
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertEqual(failure?.message, "app.plates verify crashed: KeyError: 'spec'")

        world.result(for: "python", ProcessResult(exitCode: 2, stdout: "", stderr: "usage: python -m app.plates"))
        (data, failure) = await call("plate_check", world, ["poster": .string("/p/lassen.png")])
        XCTAssertEqual(failure?.kind, .environment)
        XCTAssertEqual(failure?.message, "app.plates verify exited 2: usage: python -m app.plates")
    }

    func testPlateCheckNeedsAnAbsolutePoster() async {
        let world = FakeWorld()
        var (_, failure) = await call("plate_check", world)
        XCTAssertEqual(failure, TecopaFailure(.usage, "poster is required: the path of a poster file."))
        (_, failure) = await call("plate_check", world, ["poster": .string("lassen.png")])
        XCTAssertEqual(failure, TecopaFailure(.usage, "poster must be an absolute path: lassen.png"))
        (_, failure) = await call("plate_check", world, ["poster": .string("--root=/tmp")])
        XCTAssertEqual(failure?.kind, .usage)
        assertNothingHappened(world)
    }

    // MARK: The catalog

    func testOnlyPlatePlanAndPlateCheckAreReadOnly() {
        let readOnly = ["plate_plan": true, "plate_build": false, "plate_labels": false, "plate_playa": false,
                        "plate_pack": false, "plate_install": false, "plate_check": true]
        XCTAssertEqual(Set(Catalog.all.map(\.name).filter { $0.hasPrefix("plate_") }), Set(readOnly.keys))
        for (name, flag) in readOnly { XCTAssertEqual(Catalog.named(name)?.readOnly, flag, name) }
        func parameters(_ name: String) -> [String] {
            (Catalog.named(name)?.parameters ?? []).map { "\($0.name):\($0.kind.rawValue)" }
        }
        XCTAssertEqual(parameters("plate_plan"), ["tracks:stringArray"])
        XCTAssertEqual(parameters("plate_build"),
                       ["id:string", "name:string", "bbox:stringArray", "epsg:integer", "resolution:string"])
        XCTAssertEqual(parameters("plate_labels"), ["id:string"])
        XCTAssertEqual(parameters("plate_playa"), ["id:string"])
        XCTAssertEqual(parameters("plate_pack"), ["id:string", "resync:boolean"])
        XCTAssertEqual(parameters("plate_install"), ["file:string"])
        XCTAssertEqual(parameters("plate_check"), ["poster:string"])
    }

    func testTheTextOfAPlateCommand() {
        // a tracked start: the run, and the command that reads it
        XCTAssertEqual(Catalog.named("plate_build")?.text?(startResult), """
            run: \(run)
            pid: 4001
            log: \(runs)/\(run).log
            Run `tecopa runs show \(run)`.
            """)
        for name in ["plate_labels", "plate_playa"] {
            XCTAssertEqual(Catalog.named(name)?.text?(startResult), Catalog.named("plate_build")?.text?(startResult))
        }
        // a script that ran in the call: its own words
        let said: JSONValue = .object(["verified": .bool(false), "output": .string("unverifiable (pre-pack poster)")])
        for name in ["plate_pack", "plate_install", "plate_check"] {
            XCTAssertEqual(Catalog.named(name)?.text?(said), "unverifiable (pre-pack poster)", name)
        }
    }

    // MARK: The flags the tool never passes

    /// One entry with arguments that pass its checks, and a machine on which it runs.
    private struct Walk {
        let arguments: [String: JSONValue]
        /// How many programs the entry runs or starts with these arguments.
        let programs: Int
        let prepare: (FakeWorld) -> Void
    }

    private var walks: [String: Walk] {
        [
            // the one entry that asks the engine and runs no program
            "plate_plan": Walk(arguments: ["tracks": .array([.string("/t/a.gpx")])], programs: 0) { world in
                world.binary("/t/a.gpx", Data("<gpx/>".utf8))
                world.serve("POST /api/regions/plan", 200, "{}")
            },
            "plate_build": Walk(arguments: build.merging(["resolution": .string("auto")]) { _, new in new },
                                programs: 1) { _ in },
            "plate_labels": Walk(arguments: ["id": .string("lassen_ca")], programs: 1) { self.plate($0) },
            "plate_playa": Walk(arguments: ["id": .string("lassen_ca")], programs: 1) { self.plate($0) },
            "plate_pack": Walk(arguments: ["id": .string("lassen_ca")], programs: 1) { _ in },
            "plate_install": Walk(arguments: ["file": .string(zip)], programs: 1) { $0.existingFile(self.zip) },
            "plate_check": Walk(arguments: ["poster": .string("/p/lassen.png")], programs: 1) { _ in },
            "order_prepare": Walk(arguments: ["folder": .string("/orders/2026-10-001-smith")], programs: 1) {
                $0.folder("/orders/2026-10-001-smith")
            },
            // it reads the order's own files and runs no program
            "order_status": Walk(arguments: ["folder": .string("/orders/2026-10-001-smith")], programs: 0) { world in
                world.folder("/orders/2026-10-001-smith")
                world.file("/orders/2026-10-001-smith/work/state.json", "{}")
            },
        ]
    }

    func testNoPlateOrOrderEntryCanPassAFlagThatWritesElsewhereOrDeletes() async {
        // --replace deletes the installed plate. The other four move a script's
        // reads or writes to another folder. The tool passes none of them, by any
        // argument: this test walks every plate and order entry.
        let flags = ["--replace", "--root", "--out-root", "--regions-root", "--out"]
        let entries = Catalog.all.filter { $0.name.hasPrefix("plate_") || $0.name.hasPrefix("order_") }
        XCTAssertEqual(Set(entries.map(\.name)), Set(walks.keys), "each entry needs a walk")

        /// Every word the tool gave to a program, on one machine.
        func words(_ world: FakeWorld) -> [String] {
            world.commands.flatMap { $0 } + world.detached.flatMap { [$0.executable] + $0.arguments }
        }
        func assertNoFlag(_ world: FakeWorld, _ message: String) {
            for word in words(world) {
                for flag in flags {
                    XCTAssertFalse(word == flag || word.hasPrefix(flag + "="), "\(message): \(word)")
                }
            }
        }

        for entry in entries {
            guard let walk = walks[entry.name] else { continue }
            // 1. Every boolean argument, both ways and not given.
            let booleans = entry.parameters.filter { $0.kind == .boolean }.map(\.name)
            var choices: [[String: JSONValue]] = [[:]]
            for name in booleans {
                choices = choices.flatMap { choice in
                    [nil, false, true].map { value -> [String: JSONValue] in
                        var next = choice
                        if let value { next[name] = .bool(value) }
                        return next
                    }
                }
            }
            for choice in choices {
                let world = FakeWorld()
                walk.prepare(world)
                let arguments = walk.arguments.merging(choice) { _, new in new }
                let (_, failure) = await call(entry.name, world, arguments)
                XCTAssertNil(failure, "\(entry.name) \(choice)")
                // the walk is not empty: the entry did run what it runs
                XCTAssertEqual(world.commands.count + world.detached.count, walk.programs,
                               "\(entry.name) \(choice)")
                assertNoFlag(world, "\(entry.name) \(choice)")
            }
            // 2. Each flag as the value of each text argument: alone, with a value,
            //    and as one of a list.
            for parameter in entry.parameters where parameter.kind == .string || parameter.kind == .stringArray {
                for flag in flags {
                    for text in [flag, flag + "=/tmp/x"] {
                        var values: [JSONValue] = []
                        if parameter.kind == .string {
                            values = [.string(text)]
                        } else {
                            let given = walk.arguments[parameter.name]?.arrayValue ?? []
                            values = [.array([.string(text)]), .array(given + [.string(text)])]
                                + given.indices.map { index in
                                    var list = given
                                    list[index] = .string(text)
                                    return .array(list)
                                }
                        }
                        for value in values {
                            let world = FakeWorld()
                            walk.prepare(world)
                            var arguments = walk.arguments
                            arguments[parameter.name] = value
                            let (_, failure) = await call(entry.name, world, arguments)
                            XCTAssertEqual(failure?.kind, .usage, "\(entry.name) \(parameter.name)=\(text)")
                            assertNoFlag(world, "\(entry.name) \(parameter.name)=\(text)")
                            XCTAssertEqual(words(world), [], "\(entry.name) \(parameter.name)=\(text)")
                        }
                    }
                }
            }
        }
    }
}
