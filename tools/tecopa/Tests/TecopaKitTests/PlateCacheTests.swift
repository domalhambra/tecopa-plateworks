import XCTest
@testable import TecopaKit

/// Restore a DEM from the Dropbox archive (phase 1 spec, section 6; phase 2 spec,
/// decision 12) on the fake machine.
final class PlateCacheTests: XCTestCase {
    private let archive = "/home/Library/CloudStorage/Dropbox/Tecopa Plateworks/Plates"
    private let regions = "/repo/regions"
    private let dem = Data("the lanczos DEM".utf8)
    private var sha: String { FakeWorld.sha256(dem) }
    private let sourcesSha = String(repeating: "5", count: 64)

    /// A seeded plate, and an archive whose index names the DEM as current. The
    /// archive also holds the sources.json generation, which a restore never takes.
    private func world(index: String? = nil) -> FakeWorld {
        let w = FakeWorld()
        w.existingFile(regions + "/lassen_ca/region.json")
        w.file(archive + "/lassen_ca/index.json",
               index ?? #"{"current": "\#(sha)", "generations": [{"sha256": "\#(sourcesSha)", "label": "sidecar-original"}]}"#)
        put(w, archive + "/lassen_ca/" + sha + "/dem.tif", dem)
        put(w, archive + "/lassen_ca/" + sourcesSha + "/dem.tif", Data("the striped DEM".utf8))
        return w
    }

    private func put(_ w: FakeWorld, _ path: String, _ data: Data) {
        w.existingFile(path)
        w.binary(path, data)
    }

    private func restore(_ w: FakeWorld, _ runtime: Runtime? = nil,
                         id: String = "lassen_ca") async -> (data: JSONValue?, failure: TecopaFailure?) {
        let (envelope, failure) = await Catalog.call("plate_restore", runtime ?? w.runtime(), ["id": .string(id)])
        return (envelope["data"], failure)
    }

    func testARestoreCopiesTheCurrentShaThroughAPartialAndRenamesIt() async throws {
        let w = world()
        let (data, failure) = await restore(w)
        XCTAssertNil(failure)
        let partial = regions + "/lassen_ca/dem.tif.partial"
        XCTAssertEqual(w.copies, [[archive + "/lassen_ca/" + sha + "/dem.tif", partial]])
        XCTAssertEqual(w.moves, [[partial, regions + "/lassen_ca/dem.tif"]])
        XCTAssertEqual(w.runtime().readData(regions + "/lassen_ca/dem.tif"), dem)
        XCTAssertTrue(data?["output"]?.stringValue?.hasSuffix("restored lassen_ca \(sha)") ?? false,
                      "\(String(describing: data))")
        // nothing ran, and sources.json was not touched
        XCTAssertEqual(w.commands, [])
        XCTAssertEqual(w.written, [])
    }

    func testTheArchiveRootCanBeMovedAndTheAppRestoresUnderItsDataRoot() async {
        let w = world()
        let moved = "/Volumes/Old Drive/Plates"
        w.file(moved + "/lassen_ca/index.json", #"{"current": "\#(sha)"}"#)
        put(w, moved + "/lassen_ca/" + sha + "/dem.tif", dem)
        let data = "/home/Library/Application Support/Tecopa Plateworks/regions"
        w.existingFile(data + "/lassen_ca/region.json")
        var runtime = w.runtime(repo: nil)
        runtime.layout = .bundle(URL(fileURLWithPath: "/Applications/Tecopa Plateworks.app"))
        runtime.environment = ["TECOPA_DEM_ARCHIVE": moved]
        let (_, failure) = await restore(w, runtime)
        XCTAssertNil(failure)
        XCTAssertEqual(w.copies, [[moved + "/lassen_ca/" + sha + "/dem.tif", data + "/lassen_ca/dem.tif.partial"]])
        XCTAssertEqual(w.moves.last?.last, data + "/lassen_ca/dem.tif")
    }

    func testARestoreRefusesAPlateThatIsNotSeeded() async {
        let w = world()
        let (_, failure) = await restore(w, id: "rifle_aspen")
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(w.copies, [])
    }

    func testARestoreRefusesAMissingIndexOrAnIndexWithNoCurrentSha() async {
        for index in ["", "not json", #"{"generations": []}"#, #"{"current": "../../etc"}"#,
                      #"{"current": "\#(String(repeating: "A", count: 64))"}"#] {
            let w = world(index: index)
            let (_, failure) = await restore(w)
            XCTAssertEqual(failure?.kind, .refused, index)
            XCTAssertEqual(w.copies, [], index)
        }
        let w = FakeWorld()
        w.existingFile(regions + "/lassen_ca/region.json")
        let (_, failure) = await restore(w)
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertTrue(failure?.message.contains("index.json") ?? false, failure?.message ?? "")
    }

    func testARestoreRefusesAMissingArchivedFile() async {
        let other = String(repeating: "c", count: 64)
        let w = world(index: #"{"current": "\#(other)"}"#)
        let (_, failure) = await restore(w)
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(w.copies, [])
    }

    func testAHashThatDiffersRemovesThePartialAndRefuses() async {
        let w = world()
        // the archive's bytes changed after they were filed
        w.binary(archive + "/lassen_ca/" + sha + "/dem.tif", Data("damaged".utf8))
        let (_, failure) = await restore(w)
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(w.removed, [regions + "/lassen_ca/dem.tif.partial"])
        XCTAssertEqual(w.moves, [])
        XCTAssertNil(w.runtime().pathKind(regions + "/lassen_ca/dem.tif"))
    }

    func testARestoreNeverOverwritesADEMWithAnotherSha() async {
        let w = world()
        put(w, regions + "/lassen_ca/dem.tif", Data("another DEM".utf8))
        let (_, failure) = await restore(w)
        XCTAssertEqual(failure?.kind, .refused)
        XCTAssertEqual(w.copies, [])
        XCTAssertEqual(w.runtime().readData(regions + "/lassen_ca/dem.tif"), Data("another DEM".utf8))
    }

    func testARestoreOfADEMThatIsAlreadyThereChangesNothing() async {
        let w = world()
        put(w, regions + "/lassen_ca/dem.tif", dem)
        let (data, failure) = await restore(w)
        XCTAssertNil(failure)
        XCTAssertEqual(w.copies, [])
        XCTAssertTrue(data?["output"]?.stringValue?.contains("already") ?? false)
    }

    func testTheRealCopyHashAndRenameNeverReplaceAFile() throws {
        let folder = FileManager.default.temporaryDirectory
            .appendingPathComponent("tecopa-cache-\(UUID().uuidString)").path
        try FileManager.default.createDirectory(atPath: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(atPath: folder) }
        // more than one 8 MiB chunk, so the streamed hash crosses a chunk edge
        let bytes = Data((0..<(9 << 20)).map { UInt8(truncatingIfNeeded: $0 &* 31) })
        let source = folder + "/source dem.tif"
        try bytes.write(to: URL(fileURLWithPath: source))
        XCTAssertEqual(Runtime.sha256OfFile(source), FakeWorld.sha256(bytes))
        XCTAssertNil(Runtime.sha256OfFile(folder + "/missing"))

        try Runtime.copyNewFile(source, folder + "/dem.tif.partial")
        XCTAssertThrowsError(try Runtime.copyNewFile(source, folder + "/dem.tif.partial")) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .usage)
        }
        try Data("kept".utf8).write(to: URL(fileURLWithPath: folder + "/dem.tif"))
        XCTAssertThrowsError(try Runtime.renameExclusive(folder + "/dem.tif.partial", folder + "/dem.tif")) { error in
            XCTAssertEqual((error as? TecopaFailure)?.kind, .usage)
        }
        XCTAssertEqual(try Data(contentsOf: URL(fileURLWithPath: folder + "/dem.tif")), Data("kept".utf8))
        try Runtime.renameExclusive(folder + "/dem.tif.partial", folder + "/other.tif")
        XCTAssertEqual(Runtime.sha256OfFile(folder + "/other.tif"), FakeWorld.sha256(bytes))
    }

    func testARestoreTakesOnlyARegionId() async {
        let w = world()
        for id in ["", "../lassen_ca", "--root", "Lassen"] {
            let (_, failure) = await restore(w, id: id)
            XCTAssertEqual(failure?.kind, .usage, id)
        }
        XCTAssertEqual(w.copies, [])
    }
}
