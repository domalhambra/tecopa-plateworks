import Foundation

/// The five entries of an order: `order new` from the intake's job folder, Prepare,
/// the size preview and Finish as tracked runs, and the order's own state read back.
///
/// The tool holds no order logic. `scripts/order.py` copies the job folder into a new
/// order folder, builds or reuses the plate, frames the tracks, and writes
/// `work/state.json` and `work/report.txt`. Its preview frames every size and writes
/// the PDF and the email under `out/preview/`. No entry writes under the order
/// folder: only the script does.
enum Orders {
    static let entries: [CatalogEntry] = [newEntry, prepareEntry, previewEntry, finishEntry, statusEntry]

    // MARK: Entries

    private static let folderParameter = EntryParameter(
        "folder", .string, "The absolute path of the order folder, which holds in/ and order.toml. Required.")

    /// The intake's order number, `TP-YY-NNN` (the client intake spec, 2026-10-12),
    /// the rule of `ORDER_NUMBER` in app/order.py. The check is on the UTF-8 bytes, so
    /// a number can never be read as a flag or a path.
    static func isOrderNumber(_ text: String) -> Bool {
        let bytes = Array(text.utf8)
        let digit = { (byte: UInt8) in (UInt8(ascii: "0")...UInt8(ascii: "9")).contains(byte) }
        guard (9...11).contains(bytes.count), bytes.starts(with: Array("TP-".utf8)),
              bytes[5] == UInt8(ascii: "-") else { return false }
        return digit(bytes[3]) && digit(bytes[4]) && bytes[6...].allSatisfy(digit)
    }

    static let newEntry = CatalogEntry(
        name: "order_new",
        summary: "Make the order folder of one order from the intake's job folder in Dropbox with "
            + "scripts/order.py new: copy the client's files into in/ and write order.toml, and report the "
            + "tracks, the photos and the files of a type it does not know. It never writes to Dropbox, and "
            + "a second run adds only the files that arrived since.",
        readOnly: false,
        parameters: [EntryParameter("number", .string, "The order number, like TP-26-001. Required.")],
        text: Plates.said
    ) { runtime, arguments in
        guard let number = arguments["number"]?.stringValue, !number.isEmpty else {
            throw TecopaFailure(.usage, "number is required: an order number like TP-26-001.")
        }
        guard isOrderNumber(number) else {
            throw TecopaFailure(.usage, "Not an order number: \(number). It is like TP-26-001.")
        }
        // It copies files and reads no network, so it runs in the call. The script
        // judges the folders, and refuses with exit 1 and its reason on stderr.
        let result = try ScriptRunner.run("scripts/order.py", ["new", number], runtime)
        guard result.exitCode == 0 else { throw Plates.failure("order.py new", result, refusal: 1) }
        return .object(["output": .string(Plates.words(result.stdout))])
    }

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

    static let finishEntry = CatalogEntry(
        name: "order_finish",
        summary: "Start Finish for one order folder with scripts/order.py, as a tracked run: render the "
            + "order's approved sizes and write the print files. It takes minutes and reads the network.",
        readOnly: false,
        parameters: [folderParameter],
        text: Runs.startedText
    ) { runtime, arguments in
        let folder = try folder(arguments, runtime)
        // The same script as Prepare, and the same rule: the script judges the folder.
        return try ScriptRunner.start("scripts/order.py", ["finish", folder], command: "order_finish", runtime)
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
