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
        // an option that is not given is not an argument
        XCTAssertNil(try RenderJob.parse([]).arguments["out"])
        XCTAssertNil(try RenderPicture.parse(["--session", "ab12"]).arguments["spec"])
    }
}
