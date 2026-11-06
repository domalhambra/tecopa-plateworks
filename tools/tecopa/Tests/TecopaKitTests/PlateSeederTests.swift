import CryptoKit
import XCTest
@testable import TecopaKit

/// A real temporary folder: the seeder's work is renames and copies, and a fake
/// file system would prove nothing about them. Both roots hold a space.
final class PlateSeederTests: XCTestCase {
    private var top: URL!
    private var bundle: URL!
    private var regions: URL!
    private let fm = FileManager.default
    private let now = FakeWorld.date("2026-11-05T12:00:00Z")

    override func setUpWithError() throws {
        top = fm.temporaryDirectory.appendingPathComponent("Plate Seeder \(UUID().uuidString)")
        bundle = top.appendingPathComponent("Tecopa Plateworks.app/Contents/Resources/plates")
        regions = top.appendingPathComponent("Application Support/Tecopa Plateworks/regions")
        try fm.createDirectory(at: bundle, withIntermediateDirectories: true)
        try fm.createDirectory(at: regions, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? fm.removeItem(at: top)
    }

    private func put(_ root: URL, _ path: String, _ text: String) throws {
        let url = root.appendingPathComponent(path)
        try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(text.utf8).write(to: url)
    }

    private func read(_ root: URL, _ path: String) -> String? {
        (try? Data(contentsOf: root.appendingPathComponent(path))).map { String(decoding: $0, as: UTF8.self) }
    }

    private func exists(_ root: URL, _ path: String) -> Bool {
        fm.fileExists(atPath: root.appendingPathComponent(path).path)
    }

    private func modified(_ root: URL, _ path: String) throws -> Date {
        try fm.attributesOfItem(atPath: root.appendingPathComponent(path).path)[.modificationDate] as! Date
    }

    private func seed(_ version: String = "74cbc38") throws -> SeedReport {
        try PlateSeeder.seed(bundlePlates: bundle, regionsRoot: regions, bundleVersion: version, now: now)
    }

    private func record() throws -> [String: Any] {
        let data = try Data(contentsOf: regions.appendingPathComponent(".seeded.json"))
        return try JSONSerialization.jsonObject(with: data) as! [String: Any]
    }

    private func sha(_ text: String) -> String {
        SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    func testSeedsAMissingPlateThroughStaging() throws {
        try put(bundle, "lassen_ca/region.json", "{\"id\":\"lassen_ca\"}")
        try put(bundle, "lassen_ca/labels/peaks.json", "[]")
        let report = try seed()
        XCTAssertEqual(report.created, ["lassen_ca"])
        XCTAssertEqual(report.replaced, [:])
        XCTAssertEqual(read(regions, "lassen_ca/region.json"), "{\"id\":\"lassen_ca\"}")
        XCTAssertEqual(read(regions, "lassen_ca/labels/peaks.json"), "[]")
        XCTAssertFalse(exists(regions, ".seed-tmp"))
        // copies, never links
        let kind = try fm.attributesOfItem(atPath: regions.appendingPathComponent("lassen_ca/region.json").path)[.type]
        XCTAssertEqual(kind as? FileAttributeType, .typeRegular)
        let rec = try record()
        XCTAssertEqual(Set(rec.keys), ["schema", "bundle_version", "seeded_at", "plates"])
        XCTAssertEqual(rec["schema"] as? Int, 1)
        XCTAssertEqual(rec["bundle_version"] as? String, "74cbc38")
        XCTAssertEqual(rec["seeded_at"] as? String, "2026-11-05T12:00:00Z")
        XCTAssertEqual(rec["plates"] as? [String: [String: String]], [
            "lassen_ca": ["region.json": sha("{\"id\":\"lassen_ca\"}"), "labels/peaks.json": sha("[]")]])
    }

    func testReplacesAChangedFileAndNeverTouchesTheDEM() throws {
        try put(bundle, "lassen_ca/region.json", "new")
        try put(bundle, "lassen_ca/overview.png", "png")
        try put(regions, "lassen_ca/region.json", "old")
        try put(regions, "lassen_ca/overview.png", "png")
        try put(regions, "lassen_ca/dem.tif", "dem bytes")
        let demDate = try modified(regions, "lassen_ca/dem.tif")
        let report = try seed()
        XCTAssertEqual(report.replaced, ["lassen_ca": ["region.json"]])
        XCTAssertEqual(report.created, [])
        XCTAssertEqual(report.regionChangedUnderDEM, ["lassen_ca"])
        XCTAssertEqual(read(regions, "lassen_ca/region.json"), "new")
        XCTAssertEqual(read(regions, "lassen_ca/dem.tif"), "dem bytes")
        XCTAssertEqual(try modified(regions, "lassen_ca/dem.tif"), demDate)
        XCTAssertFalse(exists(regions, ".seed-tmp"))
    }

    func testCopiesAFileMissingFromAnExistingPlate() throws {
        try put(bundle, "lassen_ca/region.json", "r")
        try put(bundle, "lassen_ca/labels/peaks.json", "[]")
        try put(regions, "lassen_ca/region.json", "r")
        let report = try seed()
        XCTAssertEqual(report.replaced, ["lassen_ca": ["labels/peaks.json"]])
        XCTAssertEqual(report.regionChangedUnderDEM, [])
        XCTAssertEqual(read(regions, "lassen_ca/labels/peaks.json"), "[]")
    }

    func testLeavesAPlateTheBundleDoesNotCarry() throws {
        try put(bundle, "lassen_ca/region.json", "r")
        try put(regions, "my_order_plate/region.json", "built in the app")
        try put(regions, "my_order_plate/dem.tif", "dem")
        let report = try seed()
        XCTAssertEqual(read(regions, "my_order_plate/region.json"), "built in the app")
        XCTAssertEqual(read(regions, "my_order_plate/dem.tif"), "dem")
        XCTAssertEqual(report.created, ["lassen_ca"])
        XCTAssertEqual(report.leftBehind, [:])
    }

    func testRefusesABundleThatCarriesADEM() throws {
        try put(bundle, "lassen_ca/region.json", "r")
        try put(bundle, "zion_ut/region.json", "z")
        try put(bundle, "zion_ut/dem.tif", "dem")
        XCTAssertThrowsError(try seed()) { error in
            XCTAssertEqual(error as? PlateSeederError, .bundleCarriesDEM("zion_ut/dem.tif"))
        }
        XCTAssertEqual(try fm.contentsOfDirectory(atPath: regions.path), [])
    }

    func testSecondRunChangesNothing() throws {
        try put(bundle, "lassen_ca/region.json", "r")
        try put(bundle, "lassen_ca/labels/peaks.json", "[]")
        _ = try seed()
        let fileDate = try modified(regions, "lassen_ca/region.json")
        let recordDate = try modified(regions, ".seeded.json")
        let report = try PlateSeeder.seed(bundlePlates: bundle, regionsRoot: regions, bundleVersion: "74cbc38",
                                          now: now.addingTimeInterval(3600))
        XCTAssertEqual(report, SeedReport(created: [], replaced: [:], unchanged: ["lassen_ca"],
                                          regionChangedUnderDEM: [], leftBehind: [:]))
        XCTAssertEqual(try modified(regions, "lassen_ca/region.json"), fileDate)
        XCTAssertEqual(try modified(regions, ".seeded.json"), recordDate)
        XCTAssertEqual(try record()["seeded_at"] as? String, "2026-11-05T12:00:00Z")
    }

    func testClearsAStaleStagingFolderFirst() throws {
        try put(bundle, "lassen_ca/region.json", "r")
        try put(regions, ".seed-tmp/lassen_ca/region.json", "half a copy")
        try put(regions, ".seed-tmp/junk/file", "junk")
        let report = try seed()
        XCTAssertEqual(report.created, ["lassen_ca"])
        XCTAssertEqual(read(regions, "lassen_ca/region.json"), "r")
        XCTAssertFalse(exists(regions, ".seed-tmp"))
        XCTAssertFalse(exists(regions, "junk"))
    }

    func testAFileTheBundleDroppedIsLeftAndReported() throws {
        try put(bundle, "lassen_ca/region.json", "r")
        try put(bundle, "lassen_ca/old_labels.json", "old")
        _ = try seed("aaaaaaa")
        try fm.removeItem(at: bundle.appendingPathComponent("lassen_ca/old_labels.json"))
        let report = try seed("bbbbbbb")
        XCTAssertEqual(report.leftBehind, ["lassen_ca": ["old_labels.json"]])
        XCTAssertEqual(report.unchanged, ["lassen_ca"])
        XCTAssertEqual(read(regions, "lassen_ca/old_labels.json"), "old")
        XCTAssertEqual(try record()["bundle_version"] as? String, "bbbbbbb")
        XCTAssertEqual(try record()["plates"] as? [String: [String: String]],
                       ["lassen_ca": ["region.json": sha("r")]])
    }

    func testStagingAndRecordNamesStartWithADot() {
        // plate tools and the engine skip dot names, so neither is read as a plate
        XCTAssertEqual(PlateSeeder.stagingName, ".seed-tmp")
        XCTAssertEqual(PlateSeeder.recordName, ".seeded.json")
    }
}
