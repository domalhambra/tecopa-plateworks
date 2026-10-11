import Foundation

/// The entries that make a plate and read one: plan, build, labels, playa, pack,
/// install and check.
///
/// The tool holds no plate logic. `plate_plan` asks the engine. Each other entry
/// runs one row of the script table, in the venv that the row names.
///
/// Three of the scripts write `sources.json`: `region_prep.py` writes it whole, and
/// `scripts/build_labels.py` and `scripts/bake_playa.py` each add one asset entry.
/// The rule (plan decision 11) is that a command creates an entry and never
/// replaces one. So `plate_build` refuses a plate that exists, and each bake
/// refuses an asset that `sources.json` lists. A drifted asset stays drifted:
/// CLAUDE.md, invariant 12.
///
/// The scripts have flags that write to another folder, or delete: `--replace`,
/// `--root`, `--out-root`, `--regions-root`, `--out`. No entry has an argument for
/// one, and no value of an argument can be read as one.
enum Plates {
    static let entries: [CatalogEntry] = [
        planEntry, buildEntry, labelsEntry, playaEntry, packEntry, installEntry, checkEntry]

    // MARK: Entries

    private enum Parameter {
        static let id = EntryParameter(
            "id", .string, "The region id of the plate: lower-case letters, digits and underscores. Required.")
    }

    static let planEntry = CatalogEntry(
        name: "plate_plan",
        summary: "Price a new plate for these tracks: the bbox, the EPSG code, an id, the grid and the size of "
            + "the DEM. The engine fetches nothing and writes nothing.",
        readOnly: true,
        parameters: [
            EntryParameter("tracks", .stringArray, "Absolute GPX, KML or KMZ paths. Required."),
        ]
    ) { runtime, arguments in
        let paths = Render.strings(arguments["tracks"])
        guard !paths.isEmpty else {
            throw TecopaFailure(.usage, "tracks is required: one GPX, KML or KMZ path or more.")
        }
        // each file is read before the request, so a path that cannot be read sends nothing
        let files = try Render.uploads(paths, runtime)
        // this route takes the files and no field: no session, no region
        var form = Multipart()
        for file in files { try form.file("files", filename: file.filename, file.data) }
        let path = "/api/regions/plan"
        return try runtime.client.json(try await runtime.client.post(path, form), for: path)
    }

    static let buildEntry = CatalogEntry(
        name: "plate_build",
        summary: "Start the build of a new plate with region_prep.py, as a tracked run. It takes minutes and "
            + "reads the network. Refuses a plate that exists. plate_plan gives the values.",
        readOnly: false,
        parameters: [
            Parameter.id,
            EntryParameter("name", .string, "The plate's name, for example \"Lassen Volcanic\". Required."),
            EntryParameter("bbox", .stringArray,
                           "Four numbers as strings: west, south, east, north, in degrees. Required."),
            EntryParameter("epsg", .integer, "The EPSG code of the plate's projection. Required."),
            EntryParameter("resolution", .string,
                           "The cell size in metres, or auto. Without it, the script's own default applies."),
        ],
        text: Runs.startedText
    ) { runtime, arguments in
        // Form checks only, here and in each entry below. Each value is one
        // argument of the script, so none can be split into two, and these checks
        // make sure that none can be read as a flag. The tool sends the caller's
        // text unchanged and owns no range: the script and the engine do.
        let id = try regionID(arguments)
        guard let name = arguments["name"]?.stringValue, !name.isEmpty else {
            throw TecopaFailure(.usage, "name is required: the plate's name.")
        }
        guard !name.hasPrefix("-") else {
            throw TecopaFailure(.usage, "name cannot start with a hyphen: \(name)")
        }
        let bbox = Render.strings(arguments["bbox"])
        guard bbox.count == 4, bbox.allSatisfy(Render.isNumber) else {
            throw TecopaFailure(
                .usage, "bbox is four numbers, west south east north: \(bbox.map(\.debugDescription).joined(separator: " "))")
        }
        guard let epsg = arguments["epsg"]?.intValue else {
            throw TecopaFailure(.usage, "epsg is required: the EPSG code of the plate's projection.")
        }
        var command = ["--id", id, "--name", name, "--bbox"] + bbox + ["--epsg", String(epsg)]
        if let resolution = arguments["resolution"]?.stringValue {
            guard resolution == "auto" || Render.isNumber(resolution) else {
                throw TecopaFailure(.usage, "resolution is auto or a number: \(resolution.debugDescription)")
            }
            command += ["--resolution", resolution]
        }

        // region_prep.py writes sources.json whole. Anything at the path counts: a
        // failed build leaves a part of a plate, and a build over it is no new plate.
        guard runtime.pathKind(try folder(id, runtime)) == nil else {
            throw TecopaFailure(
                .refused, "The plate \(id) exists. A build would write its sources.json again.",
                hint: "CLAUDE.md, invariant 12: sources.json is never re-stamped. Give a new plate another id.")
        }
        return try ScriptRunner.start("region_prep.py", command, command: "plate_build", runtime)
    }

    static let labelsEntry = CatalogEntry(
        name: "plate_labels",
        summary: "Start the label bake of a built plate with scripts/build_labels.py, as a tracked run. It reads "
            + "GNIS from the network. Refuses a plate whose sources.json already lists labels.json.",
        readOnly: false,
        parameters: [Parameter.id],
        text: Runs.startedText
    ) { runtime, arguments in
        let id = try regionID(arguments)
        try checkNotListed("labels.json", id: id, runtime)
        return try ScriptRunner.start("scripts/build_labels.py", [id], command: "plate_labels", runtime)
    }

    static let playaEntry = CatalogEntry(
        name: "plate_playa",
        summary: "Start the playa bake of a built plate with scripts/bake_playa.py, as a tracked run. It reads "
            + "NHD from the network. Refuses a plate whose sources.json already lists playa.json.",
        readOnly: false,
        parameters: [Parameter.id],
        text: Runs.startedText
    ) { runtime, arguments in
        let id = try regionID(arguments)
        try checkNotListed("playa.json", id: id, runtime)
        // The script exits 0 when a plate fails, and prints `<id>: FAILED <why>`.
        return try ScriptRunner.start("scripts/bake_playa.py", [id], command: "plate_playa",
                                      failureText: "FAILED", runtime)
    }

    static let packEntry = CatalogEntry(
        name: "plate_pack",
        summary: "Pack a built plate into plates/<id>-<hash>.trailplate.zip with scripts/pack_region.py. "
            + "A plate whose assets drifted from its sources.json is refused.",
        readOnly: false,
        parameters: [
            Parameter.id,
            EntryParameter(
                "resync", .boolean,
                "Pack a drifted plate with the true hashes in the zip's copy of sources.json. "
                    + "The plate's own sources.json is not changed. Sent only when true."),
        ],
        text: said
    ) { runtime, arguments in
        let id = try regionID(arguments)
        // plan decision 13: the flag goes only with an explicit true
        let resync = arguments["resync"]?.boolValue == true
        let result = try ScriptRunner.run("scripts/pack_region.py", [id] + (resync ? ["--resync"] : []), runtime)
        guard result.exitCode == 0 else { throw failure("pack_region.py", result, refusal: 2) }
        return .object(["packed": .bool(true), "output": .string(words(result.stdout))])
    }

    static let installEntry = CatalogEntry(
        name: "plate_install",
        summary: "Install a plate from a local .trailplate.zip file with `python -m app.plates install`. "
            + "A plate that is installed is never replaced.",
        readOnly: false,
        parameters: [
            EntryParameter("file", .string, "The absolute path of a .trailplate.zip file on this Mac. Required."),
        ],
        text: said
    ) { runtime, arguments in
        guard let file = arguments["file"]?.stringValue, !file.isEmpty else {
            throw TecopaFailure(.usage, "file is required: the path of a .trailplate.zip file.")
        }
        // plan decision 12: the script also takes a URL, and downloads up to 2 GiB from it
        let lower = file.lowercased()
        guard !lower.hasPrefix("http:"), !lower.hasPrefix("https:"), !file.contains("://") else {
            throw TecopaFailure(.usage, "plate install takes a local file.",
                                hint: "Download the plate, then give its path.")
        }
        try Render.checkAbsolute(file, "file")
        guard file.hasSuffix(".trailplate.zip") else {
            throw TecopaFailure(.usage, "file must be a .trailplate.zip file: \(file)")
        }
        switch runtime.pathKind(file) {
        case .file: break
        case .folder: throw TecopaFailure(.usage, "\(file) is a folder, not a file.")
        case nil: throw TecopaFailure(.usage, "No file at \(file).")
        }
        // Never --replace: it deletes the plate that is installed.
        let result = try ScriptRunner.run("app.plates", ["install", file], runtime)
        guard result.exitCode == 0 else {
            let hint = result.stderr.contains("--replace")
                ? "The tool never passes --replace: it deletes the installed plate." : nil
            throw failure("app.plates install", result, refusal: 1, hint: hint)
        }
        return .object(["installed": .bool(true), "output": .string(words(result.stdout))])
    }

    static let checkEntry = CatalogEntry(
        name: "plate_check",
        summary: "Check a poster file against the plate that is installed, with `python -m app.plates verify`: "
            + "is this the plate the poster was painted on? Reads only.",
        readOnly: true,
        parameters: [
            EntryParameter("poster", .string, "The absolute path of a Tecopa Plateworks poster PNG. Required."),
        ],
        text: said
    ) { runtime, arguments in
        guard let poster = arguments["poster"]?.stringValue, !poster.isEmpty else {
            throw TecopaFailure(.usage, "poster is required: the path of a poster file.")
        }
        try Render.checkAbsolute(poster, "poster")
        let result = try ScriptRunner.run("app.plates", ["verify", poster], runtime)
        let output = words(result.stdout)
        // 0: verified, or a poster too old to verify. 1 with a verdict on stdout:
        // the poster does not match, which is the answer and not a failure, as
        // drift is the answer of `regions verify`. 1 with nothing on stdout: the
        // script could not read the file, and said why on stderr.
        guard result.exitCode == 0 || (result.exitCode == 1 && !output.isEmpty && !crashed(result)) else {
            throw failure("app.plates verify", result, refusal: 1)
        }
        // The script prints one line for each asset, and its verdict last. The
        // boolean is all the tool adds: the words are the script's own.
        let verdict = output.split(whereSeparator: \.isNewline).last.map(String.init) ?? ""
        return .object([
            "verified": .bool(result.exitCode == 0 && verdict.hasPrefix("verified")),
            "output": .string(output),
        ])
    }

    // MARK: Arguments

    /// The `id` of a call. An id is a folder name under regions/, and
    /// `scripts/build_labels.py` reads any word as an id, a flag included.
    static func regionID(_ arguments: [String: JSONValue]) throws -> String {
        guard let id = arguments["id"]?.stringValue, !id.isEmpty else {
            throw TecopaFailure(.usage, "id is required: a region id.")
        }
        guard ScriptRunner.isRegionID(id) else {
            throw TecopaFailure(.usage, "Not a region id: \(id)")
        }
        return id
    }

    /// The folder of one plate under the repo.
    static func folder(_ id: String, _ runtime: Runtime) throws -> String {
        try runtime.repo() + "/regions/" + id
    }

    // MARK: The guard of the two bakes

    /// Refuse a bake whose asset `sources.json` already lists (plan decision 11).
    /// Each bake adds its asset's hash to `sources.json`. For an asset that is
    /// listed, that replaces the entry, and the new hash hides a drift.
    ///
    /// A file that is missing is a plate that is not built. A file that the tool
    /// cannot read as an object with an `assets` object is a refusal too, never a
    /// pass: it can list the asset.
    static func checkNotListed(_ asset: String, id: String, _ runtime: Runtime) throws {
        let path = try folder(id, runtime) + "/sources.json"
        guard let text = runtime.readFile(path) else {
            guard runtime.pathKind(path) == nil else {
                throw TecopaFailure(.refused, "The file \(path) cannot be read.")
            }
            throw TecopaFailure(.refused, "The plate \(id) is not built.",
                                hint: "It has no sources.json. Run `tecopa regions` for the plates that exist.")
        }
        guard case .object(let sources)? = try? JSONValue.parse(Data(text.utf8)) else {
            throw TecopaFailure(
                .refused, "The file \(path) is not a JSON object, so the tool cannot tell if it lists \(asset).")
        }
        guard case .object(let assets)? = sources["assets"] else {
            throw TecopaFailure(
                .refused, "The file \(path) has no assets object, so the tool cannot tell if it lists \(asset).")
        }
        guard assets[asset] == nil else {
            throw TecopaFailure(
                .refused, "The plate \(id) already lists \(asset). A second bake would replace the entry.",
                hint: "CLAUDE.md, invariant 12: sources.json is never re-stamped. "
                    + "A drifted asset stays drifted, and `tecopa regions verify` reports it.")
        }
    }

    // MARK: A script that ran in the call

    /// The data of such an entry as text: the script's own words.
    static let said: @Sendable (JSONValue) -> String = { data in data["output"]?.stringValue ?? "" }

    /// What a script printed, without the line ends around it. The indent of its
    /// first line stays: it is the script's own.
    static func words(_ text: String) -> String {
        text.trimmingCharacters(in: .newlines)
    }

    /// True when an exception ended the script. Python exits 1 for it, and a
    /// script also exits 1 or 2 to say no, so the exit code alone does not tell.
    static func crashed(_ result: ProcessResult) -> Bool {
        result.stderr.contains(ScriptRunner.tracebackMarker)
    }

    /// The failure of a script that did not exit 0. `what` names it.
    ///
    /// - A traceback on stderr: the script crashed. An environment fault.
    /// - The exit code `refusal`: the script said no. `refused`, and the script's
    ///   own words are in the body.
    /// - Any other exit code: the script could not do its work. An environment fault.
    static func failure(_ what: String, _ result: ProcessResult, refusal: Int32,
                        hint: String? = nil) -> TecopaFailure {
        let stderr = result.stderr.trimmingCharacters(in: .whitespacesAndNewlines)
        let lines = stderr.split(whereSeparator: \.isNewline)
            .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        let body: JSONValue = .object([
            "exit_code": .int(Int64(result.exitCode)), "stderr": .string(stderr),
            "stdout": .string(words(result.stdout)),
        ])
        if crashed(result) {
            // the last line of a traceback names the exception
            return TecopaFailure(.environment, "\(what) crashed: \(lines.last ?? "")", body: body)
        }
        guard result.exitCode == refusal else {
            let said = lines.first.map { ": " + $0 } ?? "."
            return TecopaFailure(.environment, "\(what) exited \(result.exitCode)\(said)", body: body)
        }
        return TecopaFailure(.refused, "\(what) refused: \(lines.first ?? "It gave no reason.")",
                             hint: hint, body: body)
    }
}
