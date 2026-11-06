import CryptoKit
import Foundation

public enum PlateSeederError: Error, Equatable {
    /// The bundle holds a DEM at this path under its plates folder. A build fault:
    /// the bundle is assembled from `git ls-files`, and `dem.tif` is never tracked.
    case bundleCarriesDEM(String)
    case copyFailed(String)
}

/// `<regions>/.seeded.json`: what the last seed wrote, by plate and by file.
public struct SeedRecord: Codable, Equatable {
    public var schema: Int
    public var bundleVersion: String
    public var seededAt: String
    /// Plate id, then the file's path under the plate, then its sha256.
    public var plates: [String: [String: String]]

    enum CodingKeys: String, CodingKey {
        case schema
        case bundleVersion = "bundle_version"
        case seededAt = "seeded_at"
        case plates
    }
}

/// What one seed did. Every list is sorted.
public struct SeedReport: Equatable, Sendable {
    /// Plates that did not exist and were copied whole.
    public var created: [String]
    /// Per plate, the files that were missing or differed and were replaced.
    public var replaced: [String: [String]]
    /// Plates the bundle carries that needed nothing.
    public var unchanged: [String]
    /// Plates whose `region.json` changed under a cached `dem.tif`: they can be
    /// ORPHAN now, and `/readyz` reports it.
    public var regionChangedUnderDEM: [String]
    /// Per plate, files a previous bundle seeded that this bundle no longer carries.
    /// They stay where they are.
    public var leftBehind: [String: [String]]

    public init(created: [String] = [], replaced: [String: [String]] = [:], unchanged: [String] = [],
                regionChangedUnderDEM: [String] = [], leftBehind: [String: [String]] = [:]) {
        self.created = created
        self.replaced = replaced
        self.unchanged = unchanged
        self.regionChangedUnderDEM = regionChangedUnderDEM
        self.leftBehind = leftBehind
    }
}

/// Copies the bundle's plate files into the engine's regions root (spec 5.6). By
/// copy, never symlink: Starlette's StaticFiles refuses a link that leaves its root.
/// It never touches `dem.tif`, and never touches a plate the bundle does not carry.
public enum PlateSeeder {
    public static let stagingName = ".seed-tmp"
    public static let recordName = ".seeded.json"
    static let demName = "dem.tif"
    static let schema = 1

    public static func seed(bundlePlates: URL, regionsRoot: URL, bundleVersion: String,
                            now: Date = Date(), fileManager: FileManager = .default) throws -> SeedReport {
        let fm = fileManager
        let staging = regionsRoot.appendingPathComponent(stagingName)
        let recordURL = regionsRoot.appendingPathComponent(recordName)

        // 1. A staging folder left by a seed that did not finish.
        if fm.fileExists(atPath: staging.path) {
            try attempt("remove \(staging.path)") { try fm.removeItem(at: staging) }
        }

        // 2. Read the bundle, and refuse a DEM before anything is written.
        let bundle = try hashes(of: bundlePlates, fileManager: fm)
        for (id, files) in bundle.sorted(by: { $0.key < $1.key }) {
            if let dem = files.keys.sorted().first(where: { ($0 as NSString).lastPathComponent == demName }) {
                throw PlateSeederError.bundleCarriesDEM(id + "/" + dem)
            }
        }

        let previous = (try? Data(contentsOf: recordURL))
            .flatMap { try? JSONDecoder().decode(SeedRecord.self, from: $0) }
        var report = SeedReport()

        for id in bundle.keys.sorted() {
            let files = bundle[id]!
            let source = bundlePlates.appendingPathComponent(id)
            let target = regionsRoot.appendingPathComponent(id)
            if !fm.fileExists(atPath: target.path) {
                // 3. A missing plate: copy it whole into staging, then one rename.
                let staged = staging.appendingPathComponent(id)
                for rel in files.keys.sorted() {
                    try copy(source.appendingPathComponent(rel), to: staged.appendingPathComponent(rel), fm)
                }
                try move(staged, over: target)
                report.created.append(id)
            } else {
                // 4. A file that is missing or differs: staging, then a rename over it.
                var changed: [String] = []
                for rel in files.keys.sorted() {
                    let dest = target.appendingPathComponent(rel)
                    if (try? sha256(of: dest)) == files[rel] { continue }
                    let staged = staging.appendingPathComponent(id).appendingPathComponent(rel)
                    try copy(source.appendingPathComponent(rel), to: staged, fm)
                    try attempt("make \(dest.deletingLastPathComponent().path)") {
                        try fm.createDirectory(at: dest.deletingLastPathComponent(),
                                               withIntermediateDirectories: true)
                    }
                    try move(staged, over: dest)
                    changed.append(rel)
                }
                if changed.isEmpty {
                    report.unchanged.append(id)
                } else {
                    report.replaced[id] = changed
                    if changed.contains("region.json"),
                       fm.fileExists(atPath: target.appendingPathComponent(demName).path) {
                        report.regionChangedUnderDEM.append(id)
                    }
                }
            }
        }

        // 6. Files a previous bundle seeded and this one dropped stay, and are named.
        for (id, seeded) in previous?.plates ?? [:] {
            let target = regionsRoot.appendingPathComponent(id)
            let dropped = seeded.keys.filter {
                bundle[id]?[$0] == nil && fm.fileExists(atPath: target.appendingPathComponent($0).path)
            }.sorted()
            if !dropped.isEmpty { report.leftBehind[id] = dropped }
        }

        // 7. The record, through a temporary file and a rename. A seed that changed
        // nothing for the same bundle leaves the record as it was.
        if previous?.plates != bundle || previous?.bundleVersion != bundleVersion
            || previous?.schema != schema {
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime]
            let record = SeedRecord(schema: schema, bundleVersion: bundleVersion,
                                    seededAt: formatter.string(from: now), plates: bundle)
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            let temp = regionsRoot.appendingPathComponent(recordName + ".tmp")
            try attempt("write \(temp.path)") {
                try fm.createDirectory(at: regionsRoot, withIntermediateDirectories: true)
                try encoder.encode(record).write(to: temp)
            }
            try move(temp, over: recordURL)
        }

        // 8. The staging folder goes.
        if fm.fileExists(atPath: staging.path) {
            try attempt("remove \(staging.path)") { try fm.removeItem(at: staging) }
        }
        return report
    }

    /// Plate id, then each regular file's path under the plate, then its sha256.
    /// Dot names at the plate level are not plates. A link is read through, so
    /// what lands in the regions root is always the bytes.
    static func hashes(of plates: URL, fileManager fm: FileManager) throws -> [String: [String: String]] {
        guard let ids = try? fm.contentsOfDirectory(atPath: plates.path) else {
            throw PlateSeederError.copyFailed("cannot read \(plates.path)")
        }
        var out: [String: [String: String]] = [:]
        for id in ids where !id.hasPrefix(".") {
            let root = plates.appendingPathComponent(id)
            var isFolder: ObjCBool = false
            guard fm.fileExists(atPath: root.path, isDirectory: &isFolder), isFolder.boolValue else { continue }
            var files: [String: String] = [:]
            for case let rel as String in fm.enumerator(atPath: root.path) ?? NSEnumerator() {
                if (rel as NSString).lastPathComponent == ".DS_Store" { continue }
                let url = root.appendingPathComponent(rel)
                var folder: ObjCBool = false
                guard fm.fileExists(atPath: url.path, isDirectory: &folder), !folder.boolValue else { continue }
                files[rel] = try attempt("read \(url.path)") { try sha256(of: url) }
            }
            out[id] = files
        }
        return out
    }

    static func sha256(of url: URL) throws -> String {
        SHA256.hash(data: try Data(contentsOf: url)).map { String(format: "%02x", $0) }.joined()
    }

    /// The bytes, never the link: a write of what was read.
    private static func copy(_ source: URL, to dest: URL, _ fm: FileManager) throws {
        try attempt("copy \(source.path) to \(dest.path)") {
            try fm.createDirectory(at: dest.deletingLastPathComponent(), withIntermediateDirectories: true)
            try Data(contentsOf: source).write(to: dest)
        }
    }

    /// `rename(2)`: atomic, and it replaces a file at the target.
    private static func move(_ source: URL, over dest: URL) throws {
        guard rename(source.path, dest.path) == 0 else {
            throw PlateSeederError.copyFailed(
                "rename \(source.path) to \(dest.path): \(String(cString: strerror(errno)))")
        }
    }

    @discardableResult
    private static func attempt<T>(_ what: String, _ body: () throws -> T) throws -> T {
        do {
            return try body()
        } catch let error as PlateSeederError {
            throw error
        } catch {
            throw PlateSeederError.copyFailed("\(what): \(error.localizedDescription)")
        }
    }
}
