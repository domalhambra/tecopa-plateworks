import ArgumentParser
import TecopaKit
import XCTest
@testable import tecopa

/// The command line takes a path as a person writes it. The catalog takes an
/// absolute path only, so the CLI makes each path absolute before the call.
final class CommandPathTests: XCTestCase {
    private func absolute(_ path: String) -> String {
        absolutePath(path, home: "/Users/dom", directory: "/work/posters")
    }

    func testAnAbsolutePathIsNotChanged() {
        XCTAssertEqual(absolute("/tracks/a.gpx"), "/tracks/a.gpx")
        XCTAssertEqual(absolute("/"), "/")
        // the tool does not read `..`: the system does, and a link can change its meaning
        XCTAssertEqual(absolute("/tracks/../a.gpx"), "/tracks/../a.gpx")
    }

    func testARelativePathIsUnderTheCurrentDirectory() {
        XCTAssertEqual(absolute("a.gpx"), "/work/posters/a.gpx")
        XCTAssertEqual(absolute("tracks/day one.gpx"), "/work/posters/tracks/day one.gpx")
        XCTAssertEqual(absolute("./a.gpx"), "/work/posters/./a.gpx")
        XCTAssertEqual(absolute("../a.gpx"), "/work/posters/../a.gpx")
        XCTAssertEqual(absolutePath("a.gpx", home: "/Users/dom", directory: "/"), "/a.gpx")
    }

    func testALeadingTildeIsTheHomeFolder() {
        // a shell does not expand the tilde of `--out=~/p.png`
        XCTAssertEqual(absolute("~/Desktop/p.png"), "/Users/dom/Desktop/p.png")
        XCTAssertEqual(absolute("~"), "/Users/dom")
        // only at the start, and only the caller's own home
        XCTAssertEqual(absolute("a~/b.gpx"), "/work/posters/a~/b.gpx")
        XCTAssertEqual(absolute("~other/b.gpx"), "/work/posters/~other/b.gpx")
    }

    func testWithNoCurrentDirectoryARelativePathIsNotChanged() {
        // a working directory that was deleted reads as "". "/a.png" would be a
        // file in the root folder, which the caller did not name: the catalog
        // refuses the relative path instead.
        XCTAssertEqual(absolutePath("a.png", home: "/Users/dom", directory: ""), "a.png")
        XCTAssertEqual(absolutePath("out/a.png", home: "/Users/dom", directory: "gone"), "out/a.png")
        // the other two forms do not need the directory
        XCTAssertEqual(absolutePath("~/a.png", home: "/Users/dom", directory: ""), "/Users/dom/a.png")
        XCTAssertEqual(absolutePath("/o/a.png", home: "/Users/dom", directory: ""), "/o/a.png")
    }

    func testAnEmptyPathStaysEmpty() {
        // the catalog then says which argument is missing
        XCTAssertEqual(absolute(""), "")
    }

    func testTheDefaultsAreThisProcess() {
        XCTAssertEqual(absolutePath("a.gpx"), FileManager.default.currentDirectoryPath + "/a.gpx")
        XCTAssertEqual(absolutePath("~/a.gpx"), NSHomeDirectory() + "/a.gpx")
    }

    func testEveryPathOptionOfARenderIsMadeAbsolute() throws {
        let here = FileManager.default.currentDirectoryPath
        let picture = try RenderPicture.parse(["--tracks", "a.gpx", "/t/b.kml", "--spec", "look.json"])
        XCTAssertEqual(picture.arguments["tracks"],
                       .array([.string(here + "/a.gpx"), .string("/t/b.kml")]))
        XCTAssertEqual(picture.arguments["spec"], .string(here + "/look.json"))
        let job = try RenderJob.parse(["--out", "final.png"])
        XCTAssertEqual(job.arguments["out"], .string(here + "/final.png"))
        // the two commands with an --out of their own
        let proof = try XCTUnwrap(try Tecopa.parseAsRoot(
            ["render", "proof", "--tracks", "a.gpx", "--out", "proof.png"]) as? RenderCommand.Proof)
        XCTAssertEqual(proof.arguments, [
            "tracks": .array([.string(here + "/a.gpx")]), "out": .string(here + "/proof.png")])
        let fetch = try XCTUnwrap(try Tecopa.parseAsRoot(
            ["render", "fetch", "--job", "cd34", "--out", "~/final.png"]) as? RenderCommand.Fetch)
        XCTAssertEqual(fetch.arguments, [
            "job": .string("cd34"), "out": .string(NSHomeDirectory() + "/final.png")])
        XCTAssertEqual(try XCTUnwrap(try Tecopa.parseAsRoot(["render", "fetch"]) as? RenderCommand.Fetch)
            .arguments, [:])
        // an option that is not given is not an argument
        XCTAssertNil(try XCTUnwrap(try Tecopa.parseAsRoot(["render", "proof", "--session", "ab12"])
            as? RenderCommand.Proof).arguments["out"])
        XCTAssertNil(try RenderJob.parse([]).arguments["out"])
        XCTAssertNil(try RenderPicture.parse(["--session", "ab12"]).arguments["spec"])
    }

    // MARK: The commands that read a poster file

    func testReprintWithNoSubcommandIsTheReprintItself() throws {
        let here = FileManager.default.currentDirectoryPath
        let command = try Tecopa.parseAsRoot([
            "reprint", "lassen.png", "--out", "~/again.pdf", "--opt", "format=pdf", "embed_spec=false",
            "--allow-plate-mismatch", "--no-wait"])
        let run = try XCTUnwrap(command as? ReprintCommand.Run)
        XCTAssertEqual(run.arguments, [
            "file": .string(here + "/lassen.png"), "out": .string(NSHomeDirectory() + "/again.pdf"),
            "opt": .array([.string("format=pdf"), .string("embed_spec=false")]),
            "allow_plate_mismatch": .bool(true), "no_wait": .bool(true),
        ])
        // a flag that is not given is not an argument: the entry then sends no field
        let plain = try XCTUnwrap(try Tecopa.parseAsRoot(["reprint", "/p/lassen.png", "--out", "/o/a.png"])
            as? ReprintCommand.Run)
        XCTAssertEqual(plain.arguments, ["file": .string("/p/lassen.png"), "out": .string("/o/a.png")])
        // the same command by its own name
        XCTAssertNotNil(try Tecopa.parseAsRoot(["reprint", "run", "/p/lassen.png"]) as? ReprintCommand.Run)
    }

    func testTheHelpOfReprintSaysTheFileComesFirst() {
        // --opt takes each word up to the next option, so a file after it is read as an opt
        // the help text is wrapped, so each line end is read as a space
        func words(_ help: String) -> String {
            help.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        }
        let help = words(ReprintCommand.Run.helpMessage())
        XCTAssertTrue(help.contains("The poster file. Give it before the options."), help)
        XCTAssertTrue(help.contains("`tecopa reprint <file> --out <path>`: the file comes first"), help)
        let group = words(ReprintCommand.helpMessage())
        XCTAssertTrue(group.contains("`tecopa reprint <file> --out <path>` is `tecopa reprint run`."), group)
        XCTAssertTrue(group.contains("The file comes first, before the options."), group)
        // as `continue` says it
        XCTAssertTrue(words(ContinueCommand.helpMessage()).contains("Give it before the options."))
    }

    func testReprintInspectTakesTheFile() throws {
        let here = FileManager.default.currentDirectoryPath
        let command = try Tecopa.parseAsRoot(["reprint", "inspect", "lassen.png", "--json"])
        let inspect = try XCTUnwrap(command as? ReprintCommand.Inspect)
        XCTAssertEqual(inspect.arguments, ["file": .string(here + "/lassen.png")])
        XCTAssertNil(try? Tecopa.parseAsRoot(["reprint", "inspect", "lassen.png", "--out", "a.png"]))
    }

    // MARK: The tracked runs

    func testRunsWithNoSubcommandIsTheList() throws {
        XCTAssertNotNil(try Tecopa.parseAsRoot(["runs"]) as? RunsCommand.List)
        XCTAssertNotNil(try Tecopa.parseAsRoot(["runs", "--json"]) as? RunsCommand.List)
        XCTAssertNotNil(try Tecopa.parseAsRoot(["runs", "list"]) as? RunsCommand.List)
    }

    func testRunsShowAndRunsCancelTakeTheRunId() throws {
        let show = try XCTUnwrap(try Tecopa.parseAsRoot(
            ["runs", "show", "20261010-185515-a1b2c3", "--lines", "5"]) as? RunsCommand.Show)
        XCTAssertEqual(show.arguments, ["run": .string("20261010-185515-a1b2c3"), "lines": .int(5)])
        // the default is the entry's own, so the command does not send one
        let plain = try XCTUnwrap(try Tecopa.parseAsRoot(["runs", "show", "20261010-185515-a1b2c3"])
            as? RunsCommand.Show)
        XCTAssertEqual(plain.arguments, ["run": .string("20261010-185515-a1b2c3")])
        // without an id, the entry says that it is missing
        XCTAssertEqual(try XCTUnwrap(try Tecopa.parseAsRoot(["runs", "show"]) as? RunsCommand.Show).arguments,
                       [:])

        let cancel = try XCTUnwrap(try Tecopa.parseAsRoot(["runs", "cancel", "20261010-185515-a1b2c3"])
            as? RunsCommand.Cancel)
        XCTAssertEqual(cancel.arguments, ["run": .string("20261010-185515-a1b2c3")])
        XCTAssertNil(try? Tecopa.parseAsRoot(["runs", "cancel", "20261010-185515-a1b2c3", "--lines", "5"]))
    }

    // MARK: The plate commands

    func testPlateBuildTakesTheBboxAsOneWordWithCommas() throws {
        // a western longitude starts with a minus sign
        let expected: [String: JSONValue] = [
            "id": .string("lassen_ca"), "name": .string("Lassen Volcanic"),
            "bbox": .array([.string("-121.6"), .string("40.3"), .string("-121.2"), .string("40.6")]),
            "epsg": .int(32610),
        ]
        let build = try XCTUnwrap(try Tecopa.parseAsRoot([
            "plate", "build", "--id", "lassen_ca", "--name", "Lassen Volcanic",
            "--bbox", "-121.6,40.3,-121.2,40.6", "--epsg", "32610"]) as? PlateCommand.Build)
        XCTAssertEqual(build.arguments, expected)
        // the same with an equals sign, and in another order
        let joined = try XCTUnwrap(try Tecopa.parseAsRoot([
            "plate", "build", "--epsg", "32610", "--bbox=-121.6,40.3,-121.2,40.6", "--name", "Lassen Volcanic",
            "--id", "lassen_ca", "--json"]) as? PlateCommand.Build)
        XCTAssertEqual(joined.arguments, expected)
        // the southern hemisphere, and the texts are the caller's own
        let south = try XCTUnwrap(try Tecopa.parseAsRoot([
            "plate", "build", "--bbox", "-70.50,-33.6,-.5,+1e1", "--resolution", "auto"]) as? PlateCommand.Build)
        XCTAssertEqual(south.arguments, [
            "bbox": .array([.string("-70.50"), .string("-33.6"), .string("-.5"), .string("+1e1")]),
            "resolution": .string("auto")])
        // The command does not count the numbers: the entry does, and says so.
        let three = try XCTUnwrap(try Tecopa.parseAsRoot(["plate", "build", "--bbox", "1,2,,4,5"])
            as? PlateCommand.Build)
        XCTAssertEqual(three.arguments, [
            "bbox": .array([.string("1"), .string("2"), .string(""), .string("4"), .string("5")])])
        // an option that is not given is not an argument
        XCTAssertEqual(try XCTUnwrap(try Tecopa.parseAsRoot(["plate", "build"]) as? PlateCommand.Build).arguments,
                       [:])
    }

    func testFourSeparateBboxNumbersAreNotParsed() {
        // The parser reads `-121.2` as an option, so four words cannot work for a
        // western plate. The command has one form, and it does not half-work.
        XCTAssertNil(try? Tecopa.parseAsRoot([
            "plate", "build", "--id", "x", "--bbox", "-121.6", "40.3", "-121.2", "40.6", "--epsg", "32610"]))
        XCTAssertNil(try? Tecopa.parseAsRoot([
            "plate", "build", "--id", "x", "--bbox", "121.6", "40.3", "121.2", "40.6", "--epsg", "32610"]))
        let help = PlateCommand.Build.helpMessage().split(whereSeparator: \.isWhitespace).joined(separator: " ")
        XCTAssertTrue(help.contains("--bbox -121.6,40.3,-121.2,40.6"), help)
    }

    func testThePlateCommandsThatNameAPlateTakeTheId() throws {
        let labels = try XCTUnwrap(try Tecopa.parseAsRoot(["plate", "labels", "lassen_ca"]) as? PlateCommand.Labels)
        XCTAssertEqual(labels.plate.arguments, ["id": .string("lassen_ca")])
        let playa = try XCTUnwrap(try Tecopa.parseAsRoot(["plate", "playa", "lassen_ca", "--json"])
            as? PlateCommand.Playa)
        XCTAssertEqual(playa.plate.arguments, ["id": .string("lassen_ca")])
        // without an id, the entry says that it is missing
        XCTAssertEqual(try XCTUnwrap(try Tecopa.parseAsRoot(["plate", "playa"]) as? PlateCommand.Playa)
            .plate.arguments, [:])

        // the flag is an argument only when it is given
        let pack = try XCTUnwrap(try Tecopa.parseAsRoot(["plate", "pack", "lassen_ca"]) as? PlateCommand.Pack)
        XCTAssertEqual(pack.arguments, ["id": .string("lassen_ca")])
        let resync = try XCTUnwrap(try Tecopa.parseAsRoot(["plate", "pack", "lassen_ca", "--resync"])
            as? PlateCommand.Pack)
        XCTAssertEqual(resync.arguments, ["id": .string("lassen_ca"), "resync": .bool(true)])
        // a bake has no flag at all
        XCTAssertNil(try? Tecopa.parseAsRoot(["plate", "labels", "lassen_ca", "--resync"]))
        XCTAssertNil(try? Tecopa.parseAsRoot(["plate", "labels", "lassen_ca", "--root", "/tmp"]))
    }

    func testEveryPathOfAPlateCommandIsMadeAbsolute() throws {
        let here = FileManager.default.currentDirectoryPath
        let plan = try XCTUnwrap(try Tecopa.parseAsRoot(["plate", "plan", "--tracks", "a.gpx", "/t/b.kml", "~/c.kmz"])
            as? PlateCommand.Plan)
        XCTAssertEqual(plan.arguments, ["tracks": .array([
            .string(here + "/a.gpx"), .string("/t/b.kml"), .string(NSHomeDirectory() + "/c.kmz")])])
        XCTAssertEqual(try XCTUnwrap(try Tecopa.parseAsRoot(["plate", "plan"]) as? PlateCommand.Plan).arguments, [:])

        let install = try XCTUnwrap(try Tecopa.parseAsRoot(["plate", "install", "lassen_ca-1a2b.trailplate.zip"])
            as? PlateCommand.Install)
        XCTAssertEqual(install.arguments, ["file": .string(here + "/lassen_ca-1a2b.trailplate.zip")])
        XCTAssertEqual(try XCTUnwrap(try Tecopa.parseAsRoot(["plate", "install"]) as? PlateCommand.Install)
            .arguments, [:])
        // the command has no flag that replaces an installed plate, and none that moves the folder
        for flag in ["--replace", "--root", "--out"] {
            XCTAssertNil(try? Tecopa.parseAsRoot(["plate", "install", "/dl/a.trailplate.zip", flag]), flag)
            XCTAssertNil(try? Tecopa.parseAsRoot(["plate", "pack", "lassen_ca", flag]), flag)
        }

        let check = try XCTUnwrap(try Tecopa.parseAsRoot(["plate", "check", "~/Desktop/lassen.png"])
            as? PlateCommand.Check)
        XCTAssertEqual(check.arguments, ["poster": .string(NSHomeDirectory() + "/Desktop/lassen.png")])
    }

    func testAURLGivenToPlateInstallIsStillRefusedAsAURL() async {
        // The command line joins a relative word to the current directory. The
        // entry still sees the `://`, so the caller reads the true reason.
        let url = "https://plates.example/lassen_ca-1a2b.trailplate.zip"
        let install = try? Tecopa.parseAsRoot(["plate", "install", url]) as? PlateCommand.Install
        let (_, failure) = await Catalog.call("plate_install", Runtime(repoFlag: "/no/such/repo"),
                                              install?.arguments ?? [:])
        XCTAssertEqual(failure?.kind, .usage)
        XCTAssertEqual(failure?.message, "plate install takes a local file.")
    }

    func testContinueTakesTheFileThenItsOptions() throws {
        let here = FileManager.default.currentDirectoryPath
        let command = try Tecopa.parseAsRoot([
            "continue", "lassen.png", "--tracks", "new.gpx", "/t/more.kml", "--set", "title=Two",
            "--opt", "format=pdf", "--crop", "-1,2,3,4", "--out", "two.pdf", "--allow-plate-mismatch"])
        let next = try XCTUnwrap(command as? ContinueCommand)
        XCTAssertEqual(next.arguments, [
            "file": .string(here + "/lassen.png"),
            "tracks": .array([.string(here + "/new.gpx"), .string("/t/more.kml")]),
            "set": .array([.string("title=Two")]), "opt": .array([.string("format=pdf")]),
            "crop": .string("-1,2,3,4"), "out": .string(here + "/two.pdf"),
            "allow_plate_mismatch": .bool(true),
        ])
        let plain = try XCTUnwrap(try Tecopa.parseAsRoot(["continue", "/p/lassen.png", "--no-wait"])
            as? ContinueCommand)
        XCTAssertEqual(plain.arguments, ["file": .string("/p/lassen.png"), "no_wait": .bool(true)])
    }
}
