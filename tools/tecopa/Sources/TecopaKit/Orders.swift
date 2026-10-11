import Foundation

/// The three entries of an order: Prepare and the size preview as tracked runs,
/// and the order's own state read back.
///
/// The tool holds no order logic. `scripts/order.py` builds or reuses the plate,
/// frames the tracks, and writes `work/state.json` and `work/report.txt`. Its
/// preview frames every size and writes the PDF under `out/preview/`. No entry
/// writes under the order folder: only the script does.
enum Orders {
    static let entries: [CatalogEntry] = [prepareEntry, previewEntry, statusEntry]

    // MARK: Entries

    private static let folderParameter = EntryParameter(
        "folder", .string, "The absolute path of the order folder, which holds in/ and order.toml. Required.")

    static let prepareEntry = CatalogEntry(
        name: "order_prepare",
        summary: "Start Prepare for one order folder with scripts/order.py, as a tracked run: build or reuse "
            + "the order's plate and frame the tracks. It takes minutes and reads the network.",
        readOnly: false,
        parameters: [folderParameter],
        text: Runs.startedText
    ) { runtime, arguments in
        let folder = try folder(arguments, runtime)
        // The tool does not judge where the folder is. The script refuses a folder
        // inside the repo, with exit 1 and its reason in the run's log.
        return try ScriptRunner.start("scripts/order.py", ["prepare", folder], command: "order_prepare", runtime)
    }

    static let previewEntry = CatalogEntry(
        name: "order_preview",
        summary: "Start the size preview for one order folder with scripts/order.py, as a tracked run: "
            + "frame the tracks at every size, build one coarse plate, and write the preview PDF under "
            + "out/preview/. It takes minutes and reads the network.",
        readOnly: false,
        parameters: [folderParameter],
        text: Runs.startedText
    ) { runtime, arguments in
        let folder = try folder(arguments, runtime)
        // The same script as Prepare, and the same rule: the script judges the folder.
        return try ScriptRunner.start("scripts/order.py", ["preview", folder], command: "order_preview", runtime)
    }

    static let statusEntry = CatalogEntry(
        name: "order_status",
        summary: "Read what Prepare decided for one order folder: all of work/state.json, and the text of "
            + "work/report.txt. Reads only.",
        readOnly: true,
        parameters: [folderParameter],
        text: statusText
    ) { runtime, arguments in
        let folder = try folder(arguments, runtime)
        let path = folder + "/work/state.json"
        guard let data = runtime.readData(path) else {
            // a file that is there and cannot be read is not an order with no state
            guard runtime.pathKind(path) == nil else {
                throw TecopaFailure(.refused, "The file \(path) cannot be read.")
            }
            return .object(["prepared": .bool(false)])
        }
        // The state goes back whole. The tool has no model of it, so a key that
        // the script adds next year is in the answer too.
        guard let state = try? JSONValue.parse(data), case .object = state else {
            throw TecopaFailure(.refused, "The file \(path) is not a JSON object.")
        }
        let report = runtime.readFile(folder + "/work/report.txt")
        return .object([
            "prepared": .bool(true), "state": state, "report": report.map { .string($0) } ?? .null,
        ])
    }

    // MARK: Arguments

    /// The order folder of a call: an absolute path to a folder that exists.
    static func folder(_ arguments: [String: JSONValue], _ runtime: Runtime) throws -> String {
        guard let folder = arguments["folder"]?.stringValue, !folder.isEmpty else {
            throw TecopaFailure(.usage, "folder is required: the path of an order folder.")
        }
        try Render.checkAbsolute(folder, "folder")
        switch runtime.pathKind(folder) {
        case .folder: return folder
        case .file: throw TecopaFailure(.usage, "\(folder) is not a folder.")
        case nil: throw TecopaFailure(.usage, "The folder \(folder) does not exist.")
        }
    }

    // MARK: The text

    /// An order's status as text: the script's own report when there is one. If
    /// not, a few lines from the state: the plate and how many warnings.
    static let statusText: @Sendable (JSONValue) -> String = { data in
        guard data["prepared"]?.boolValue == true else {
            return "Not prepared: the order has no work/state.json. Run `tecopa order prepare`."
        }
        if let report = data["report"]?.stringValue?.trimmingCharacters(in: .newlines), !report.isEmpty {
            return report
        }
        var lines = ["Prepared. The order has no work/report.txt."]
        let plate = data["state"]?["plate"]
        if let id = plate?["id"]?.stringValue {
            lines.append("Plate: \(id)" + (plate?["kind"]?.stringValue.map { " (\($0))" } ?? ""))
        }
        if let warnings = data["state"]?["warnings"]?.arrayValue {
            lines.append("Warnings: \(warnings.count)")
        }
        return lines.joined(separator: "\n")
    }
}
