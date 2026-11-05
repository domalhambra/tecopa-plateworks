import Foundation

/// The DEM cache of the plates: restore a DEM from the Dropbox archive, and free
/// one's space (phase 1 spec, section 6; phase 2 spec, decision 12).
///
/// The archive is keyed by each DEM's own sha256, and `<id>/index.json` names the
/// `current` one. A restore takes that sha and never the one in `sources.json`:
/// six plates drifted on purpose with the Lanczos swap, and the `sources.json` sha
/// is the striped DEM before it. Nothing here writes `sources.json` (invariant 12).
enum PlateCache {
    static let entries: [CatalogEntry] = [restoreEntry, evictEntry]

    /// The archive's default folder, under the home folder.
    static let archiveFolder = "/Library/CloudStorage/Dropbox/Tecopa Plateworks/Plates"

    /// The archive root: `TECOPA_DEM_ARCHIVE` when it is set, else Dropbox's.
    static func archiveRoot(_ runtime: Runtime) -> String {
        if let root = runtime.environment["TECOPA_DEM_ARCHIVE"], !root.isEmpty { return root }
        return runtime.home + archiveFolder
    }

    /// A sha256 as the archive names its folders: 64 lower-case hexadecimal digits.
    /// It goes into a path, so nothing else passes.
    static func isSha256(_ text: String) -> Bool {
        let bytes = Array(text.utf8)
        return bytes.count == 64 && bytes.allSatisfy { byte in
            (UInt8(ascii: "0")...UInt8(ascii: "9")).contains(byte)
                || (UInt8(ascii: "a")...UInt8(ascii: "f")).contains(byte)
        }
    }

    static let restoreEntry = CatalogEntry(
        name: "plate_restore",
        summary: "Restore a plate's dem.tif from the Dropbox archive: the sha that the archive's index.json "
            + "names as current, never the sources.json sha. The copy is checked against its sha256 before it "
            + "takes the name dem.tif. Refuses a plate that is not seeded, and never replaces a DEM.",
        readOnly: false,
        parameters: [EntryParameter("id", .string, "The region id of the plate. Required.")],
        text: Plates.said
    ) { runtime, arguments in
        let id = try Plates.regionID(arguments)
        let plate = try Plates.folder(id, runtime)
        guard runtime.pathKind(plate + "/region.json") == .file else {
            throw TecopaFailure(.refused, "The plate \(id) is not seeded: \(plate) has no region.json.",
                                hint: "Run `tecopa regions` for the plates that exist.")
        }

        let root = archiveRoot(runtime)
        let indexPath = root + "/" + id + "/index.json"
        guard let data = runtime.readData(indexPath) else {
            throw TecopaFailure(.refused, "The archive has no index.json for \(id): \(indexPath)",
                                hint: "Set TECOPA_DEM_ARCHIVE if the archive is in another folder.")
        }
        guard let index = try? JSONValue.parse(data), let sha = index["current"]?.stringValue else {
            throw TecopaFailure(.refused, "The archive's \(indexPath) names no current sha.")
        }
        guard isSha256(sha) else {
            throw TecopaFailure(.refused, "The current sha in \(indexPath) is not a sha256: \(sha)")
        }
        let source = root + "/" + id + "/" + sha + "/dem.tif"
        guard runtime.pathKind(source) == .file else {
            throw TecopaFailure(.refused, "The archive has no file at \(source).")
        }

        let target = plate + "/dem.tif"
        if runtime.pathKind(target) != nil {
            // never overwrite: the DEM there may be the only record of a swap
            guard runtime.sha256File(target) == sha else {
                throw TecopaFailure(
                    .refused, "The plate \(id) has a dem.tif whose sha is not \(sha). A restore never replaces it.",
                    hint: "Free its space first with `tecopa plate evict \(id)`, which moves it to the Trash.")
            }
            return .object(["output": .string("\(id) already has dem.tif \(sha). Nothing changed.")])
        }

        // A partial is the tool's own, left by a restore that was cut off.
        let partial = target + ".partial"
        runtime.removeFile(partial)
        try runtime.copyFile(source, partial)
        guard let found = runtime.sha256File(partial), found == sha else {
            runtime.removeFile(partial)
            throw TecopaFailure(
                .refused, "The archived DEM at \(source) does not hash to \(sha). Nothing was restored.")
        }
        try runtime.moveFile(partial, target)
        return .object(["output": .string("\(target): restored \(id) \(sha)")])
    }

    static let evictEntry = CatalogEntry(
        name: "plate_evict",
        summary: "Free a plate's space: move its dem.tif to the Trash, and nothing else. Refuses while an order "
            + "run is going, since a plate with no DEM drops out of Preview and Prepare. plate_restore puts it back.",
        readOnly: false,
        parameters: [EntryParameter("id", .string, "The region id of the plate. Required.")],
        text: Plates.said
    ) { runtime, arguments in
        let id = try Plates.regionID(arguments)
        // phase 1 spec, section 6: never evict a DEM under an order verb
        let orders = try Runs.running(runtime).filter { $0.command.hasPrefix("order_") }
        guard orders.isEmpty else {
            let named = orders.map { "\($0.command) (\($0.id))" }.joined(separator: ", ")
            throw TecopaFailure(.refused, "An order run is going: \(named). A plate's DEM stays while it runs.",
                                hint: "Wait for it to end, or stop it with `tecopa runs cancel`.")
        }
        let plate = try Plates.folder(id, runtime)
        guard runtime.pathKind(plate) == .folder else {
            throw TecopaFailure(.refused, "No plate \(id) in \(try Plates.regionsRoot(runtime)).",
                                hint: "Run `tecopa regions` for the plates that exist.")
        }
        let dem = plate + "/dem.tif"
        guard runtime.pathKind(dem) == .file else {
            throw TecopaFailure(.refused, "The plate \(id) has no dem.tif. Nothing to free.")
        }
        try runtime.trashItem(dem)
        return .object(["output": .string(
            "Moved \(dem) to the Trash. `tecopa plate restore \(id)` puts the archived DEM back.")])
    }
}
