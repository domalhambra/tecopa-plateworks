import CryptoKit
import Foundation

/// The entries that render: a proof, a final, a wallpaper bundle, a film, and the
/// file of a job that is done.
///
/// The tool sends each value as the caller wrote it. It has no default for a field,
/// no range check and no copy of the engine's field names: the engine names its
/// fields at /api/debug/forms, and the engine frames a crop. Each step below is one
/// small function, so `reprint` and `continue` use the same steps.
enum Render {
    static let entries: [CatalogEntry] = [proofEntry, finalEntry, wallpaperEntry, filmEntry, fetchEntry]

    // MARK: Entries

    /// The arguments of the entries. Each entry takes the ones that apply to it.
    private enum Parameter {
        static let tracks = EntryParameter(
            "tracks", .stringArray, "Absolute GPX, KML or KMZ paths. Give tracks or session, never both.")
        static let session = EntryParameter(
            "session", .string, "A session id. The tool sends no upload, and renders the session.")
        static let region = EntryParameter(
            "region", .string, "A region id, sent with the tracks. Without it, the engine picks the plate.")
        static let spec = EntryParameter(
            "spec", .string, "The absolute path of a JSON file: one flat object of proof form fields.")
        static let set = EntryParameter(
            "set", .stringArray,
            "key=value, one proof form field for each. Wins over spec. An unknown name is refused with the engine's list.")
        static let opt = EntryParameter(
            "opt", .stringArray,
            "key=value, one field of the output route for each. An unknown name is refused with the engine's list.")
        static let crop = EntryParameter(
            "crop", .string, "x0,y0,x1,y1 in overview pixels. Without it, the engine frames the tracks.")
        static let presets = EntryParameter("presets", .stringArray, "Wallpaper preset ids. Required.")
        static let out = EntryParameter(
            "out", .string,
            "The absolute path of the file to write. It must hold no file. Required, except with no_wait.")
        /// For an entry that has no `no_wait`.
        static let outAlways = EntryParameter(
            "out", .string, "The absolute path of the file to write. It must hold no file. Required.")
        static let noWait = EntryParameter(
            "no_wait", .boolean, "Return the job id at once and write no file. Then run render_fetch.")
        static let job = EntryParameter("job", .string, "The job id that no_wait returned. Required.")

        /// The arguments that name the picture: where it comes from, and its proof fields.
        static let picture = [tracks, session, region, spec, set]
    }

    static let proofEntry = CatalogEntry(
        name: "render_proof",
        summary: "Render a proof PNG from tracks or from a session, and write it to out.",
        readOnly: false,
        parameters: Parameter.picture + [Parameter.crop, Parameter.outAlways],
        text: text
    ) { runtime, arguments in
        try await render(runtime, arguments, to: nil)
    }

    static let finalEntry = CatalogEntry(
        name: "render_final",
        summary: "Render the final poster from tracks or from a session, and write it to out.",
        readOnly: false,
        parameters: Parameter.picture + [Parameter.opt, Parameter.crop, Parameter.out, Parameter.noWait],
        text: text
    ) { runtime, arguments in
        try await render(runtime, arguments, to: .final)
    }

    static let wallpaperEntry = CatalogEntry(
        name: "render_wallpaper",
        summary: "Render a zip of wallpapers, one for each preset, and write it to out.",
        readOnly: false,
        parameters: Parameter.picture
            + [Parameter.opt, Parameter.crop, Parameter.presets, Parameter.out, Parameter.noWait],
        text: text
    ) { runtime, arguments in
        try await render(runtime, arguments, to: .wallpaper)
    }

    static let filmEntry = CatalogEntry(
        name: "render_film",
        summary: "Render the time-lapse film from tracks or from a session, and write it to out.",
        readOnly: false,
        parameters: Parameter.picture + [Parameter.opt, Parameter.crop, Parameter.out, Parameter.noWait],
        text: text
    ) { runtime, arguments in
        try await render(runtime, arguments, to: .film)
    }

    static let fetchEntry = CatalogEntry(
        name: "render_fetch",
        summary: "Write the file of a job that is done to out. A job that is not done is refused.",
        readOnly: false,
        parameters: [Parameter.job, Parameter.outAlways],
        text: text
    ) { runtime, arguments in
        guard let job = arguments["job"]?.stringValue, !job.isEmpty else {
            throw TecopaFailure(.usage, "job is required: the job id that no_wait returned.")
        }
        try checkID(job, "A job id")
        let out = try freePath(arguments["out"]?.stringValue, runtime)
        var result = try await fetch(runtime, job: job, out: out)
        result["job"] = .string(job)
        return .object(await withEngineVersion(result, runtime))
    }

    /// A result as a few lines: the keys in one order, and one line for each device
    /// that the wallpaper route did not render.
    static let text: @Sendable (JSONValue) -> String = { data in
        var lines: [String] = []
        for key in ["out", "bytes", "sha256", "session", "job", "region", "engine_version", "frames"] {
            switch data[key] {
            case .string(let text)?: lines.append("\(key): \(text)")
            case .int(let number)?: lines.append("\(key): \(number)")
            default: break
            }
        }
        for item in data["skipped"]?.arrayValue ?? [] {
            lines.append("skipped: \(item["preset"]?.stringValue ?? "?"): \(item["reason"]?.stringValue ?? "")")
        }
        return lines.joined(separator: "\n")
    }

    // MARK: Form fields

    /// Form fields in the order they were first named. A later value for a name
    /// replaces the earlier one and keeps its place: this is how `set` wins over
    /// `spec`, and how each of them wins over a session's own fields.
    struct Fields: Equatable, Sendable {
        struct Pair: Equatable, Sendable {
            let name: String
            var value: String
        }

        private(set) var pairs: [Pair] = []

        var isEmpty: Bool { pairs.isEmpty }
        var names: [String] { pairs.map(\.name) }

        func value(_ name: String) -> String? {
            pairs.first { $0.name == name }?.value
        }

        mutating func set(_ name: String, _ value: String) {
            if let index = pairs.firstIndex(where: { $0.name == name }) {
                pairs[index].value = value
            } else {
                pairs.append(Pair(name: name, value: value))
            }
        }

        mutating func merge(_ other: Fields) {
            for pair in other.pairs { set(pair.name, pair.value) }
        }

        /// True when a field names the sheet. The crop of another sheet has another
        /// aspect, so the engine must frame it again.
        var namesPrintSize: Bool { value("print_w") != nil || value("print_h") != nil }
    }

    /// The names the tool sends from its own arguments. A caller who could set one
    /// would move the request to another session, another crop or another file.
    static let reserved: Set<String> = ["session_id", "x0", "y0", "x1", "y1", "files", "file", "presets"]

    static func checkName(_ name: String, in parameter: String) throws {
        guard !reserved.contains(name) else {
            throw TecopaFailure(
                .usage, "\(parameter) cannot name \(name).",
                hint: "The tool sends the session, the crop, the files and the presets from their own arguments.")
        }
    }

    /// The `key=value` entries of `set` or `opt`, split on the first `=`. The value
    /// is the rest of the text, unchanged, and it can be empty.
    static func pairs(_ entries: [String], _ parameter: String) throws -> Fields {
        var fields = Fields()
        for entry in entries {
            guard let equals = entry.firstIndex(of: "="), equals != entry.startIndex else {
                throw TecopaFailure(.usage, "\(parameter) takes key=value: \(entry.debugDescription)")
            }
            let name = String(entry[..<equals])
            try checkName(name, in: parameter)
            fields.set(name, String(entry[entry.index(after: equals)...]))
        }
        return fields
    }

    /// A JSON scalar as the text of a form field: a string as it is, a number as
    /// its JSON text, a boolean as `true` or `false`. Any other value has no text.
    static func formText(_ value: JSONValue) -> String? {
        switch value {
        case .string(let text): return text
        case .int(let number): return String(number)
        // the shortest text that reads back as the same number
        case .double(let number): return "\(number)"
        case .bool(let flag): return flag ? "true" : "false"
        case .null, .array, .object: return nil
        }
    }

    /// The fields of a `spec` file: one flat JSON object, each value a string, a
    /// number or a boolean. A JSON object has no order, so the fields go by name.
    static func specFields(_ path: String, _ runtime: Runtime) throws -> Fields {
        try checkAbsolute(path, "spec")
        guard let data = runtime.readData(path) else {
            throw TecopaFailure(.usage, "Cannot read the spec file: \(path)")
        }
        guard case .object(let object)? = try? JSONValue.parse(data) else {
            throw TecopaFailure(
                .usage, "The spec file is not one JSON object: \(path)",
                hint: #"Write one flat object of proof form fields, for example {"title": "Lassen"}."#)
        }
        var fields = Fields()
        for name in object.keys.sorted() {
            guard let text = object[name].flatMap(formText) else {
                throw TecopaFailure(
                    .usage, "The spec file's \(name) is not a string, a number or a boolean: \(path)")
            }
            try checkName(name, in: "spec")
            fields.set(name, text)
        }
        return fields
    }

    /// Refuse a field name that the engine does not have. FastAPI ignores a form
    /// field that it does not know, so a misspelled name would change nothing and
    /// say nothing. `form` is a key of /api/debug/forms. With no name to check, the
    /// route is not asked, and the debug gate is not needed.
    static func checkNames(_ runtime: Runtime, _ named: [(form: String, names: [String])]) async throws {
        let named = named.filter { !$0.names.isEmpty }
        guard !named.isEmpty else { return }
        let forms = try await runtime.client.debug("/forms")
        for group in named {
            guard let known = forms[group.form]?.arrayValue?.compactMap(\.stringValue) else {
                throw TecopaFailure(.environment, "The engine did not name the fields of \(group.form).",
                                    hint: "The engine may be older than the tool. Run `tecopa doctor`.")
            }
            let open = known.filter { !reserved.contains($0) }
            for name in group.names where !open.contains(name) {
                throw TecopaFailure(
                    .usage,
                    "Unknown field for \(group.form): \(name). The engine's fields are: "
                        + open.joined(separator: ", ") + ".")
            }
        }
    }

    // MARK: Arguments

    /// The strings of a list argument. An argument that was not given is no strings.
    static func strings(_ value: JSONValue?) -> [String] {
        (value?.arrayValue ?? []).compactMap(\.stringValue)
    }

    /// True for the form of an engine id, `uuid4().hex`. `isHexDigit` alone is also
    /// true for the fullwidth forms, which are not ASCII.
    static func isHexID(_ id: String) -> Bool {
        !id.isEmpty && id.allSatisfy { $0.isASCII && $0.isHexDigit }
    }

    /// An id goes into a URL path, so a caller's id is checked before any request.
    static func checkID(_ id: String, _ what: String) throws {
        guard isHexID(id) else {
            throw TecopaFailure(.usage, "\(what) is hexadecimal: \(id)")
        }
    }

    /// A path argument is absolute. Under `tecopa mcp` the working directory is the
    /// MCP client's, so a relative path would name a file that the caller does not
    /// mean. The command line makes each path absolute before it calls an entry.
    static func checkAbsolute(_ path: String, _ name: String) throws {
        guard path.hasPrefix("/") else {
            throw TecopaFailure(.usage, "\(name) must be an absolute path: \(path)")
        }
    }

    /// The four texts of a `crop` argument. The tool checks the form only, four
    /// finite numbers, and sends each text as the caller wrote it.
    static func cropArgument(_ text: String) throws -> [String] {
        let digits = Set("0123456789+-.eE")
        let parts = text.split(separator: ",", omittingEmptySubsequences: false).map(String.init)
        guard parts.count == 4,
              parts.allSatisfy({ $0.allSatisfy(digits.contains) && Double($0)?.isFinite == true }) else {
            throw TecopaFailure(
                .usage, "crop is four numbers, x0,y0,x1,y1, with no spaces: \(text.debugDescription)")
        }
        return parts
    }

    /// The four texts of a crop that the engine gave as JSON numbers.
    static func cropTexts(_ value: JSONValue?) -> [String]? {
        guard let numbers = value?.arrayValue, numbers.count == 4 else { return nil }
        let texts: [String] = numbers.compactMap {
            switch $0 {
            case .int, .double: return formText($0)
            default: return nil
            }
        }
        return texts.count == 4 ? texts : nil
    }

    /// A path the tool can write: nothing is at it, and its folder exists. The
    /// check is before the first request, so a render of minutes is not lost to a
    /// path that `writeNew` refuses. `writeNew` still refuses at the end, because
    /// another program can make the file in between.
    static func freePath(_ out: String?, _ runtime: Runtime) throws -> String {
        guard let out, !out.isEmpty else {
            throw TecopaFailure(.usage, "out is required: the path of the file to write.")
        }
        try checkAbsolute(out, "out")
        guard runtime.pathKind(out) == nil else { throw fileAlreadyThere(out) }
        let folder = (out as NSString).deletingLastPathComponent
        switch runtime.pathKind(folder) {
        case .folder: return out
        case .file: throw TecopaFailure(.usage, "\(folder) is not a folder.")
        case nil: throw TecopaFailure(.usage, "The folder \(folder) does not exist.")
        }
    }

    /// `freePath`, or nil with `no_wait`: that call writes no file, so it takes no
    /// path. A path it did not use would look like a file that was written.
    static func outPath(_ arguments: [String: JSONValue], _ runtime: Runtime) throws -> String? {
        guard arguments["no_wait"]?.boolValue == true else {
            return try freePath(arguments["out"]?.stringValue, runtime)
        }
        guard arguments["out"] == nil else {
            throw TecopaFailure(.usage, "no_wait writes no file, so it takes no out.",
                                hint: "Run `tecopa render fetch` with the job id and out when the job is done.")
        }
        return nil
    }

    /// One file to send: its name without the folder, and its bytes.
    struct Upload: Equatable, Sendable {
        let filename: String
        let data: Data
    }

    /// Read each file before the first request, so a path that cannot be read
    /// starts no upload. `name` is the argument that holds the paths.
    static func uploads(_ paths: [String], _ runtime: Runtime, name: String = "tracks",
                        what: String = "track file") throws -> [Upload] {
        try paths.map { path in
            try checkAbsolute(path, name)
            guard let data = runtime.readData(path) else {
                throw TecopaFailure(.usage, "Cannot read the \(what): \(path)")
            }
            return Upload(filename: (path as NSString).lastPathComponent, data: data)
        }
    }

    /// The sheet size for the engine's starter crop. The route needs both, and the
    /// tool has no default for a field, so it cannot supply the one that is missing.
    static func printSize(_ fields: Fields) throws -> (width: String, height: String) {
        guard let width = fields.value("print_w"), let height = fields.value("print_h") else {
            throw TecopaFailure(
                .usage, "print_w and print_h go together: the tool has no default for the other one.",
                hint: "Name both, or give crop.")
        }
        return (width, height)
    }

    // MARK: Requests

    /// POST the tracks. The answer names the session, the region and the starter
    /// crop. It also holds the track geometry, which no result keeps. `session`
    /// adds the tracks to a session that exists.
    static func upload(_ runtime: Runtime, _ files: [Upload], region: String? = nil,
                       session: String? = nil) async throws -> JSONValue {
        var form = Multipart()
        for file in files { try form.file("files", filename: file.filename, file.data) }
        if let region { try form.field("region_id", region) }
        if let session { try form.field("session_id", session) }
        let path = "/api/upload"
        return try runtime.client.json(try await runtime.client.post(path, form), for: path)
    }

    /// The session id of an upload answer. It goes into a URL path, so an answer
    /// with another form is not used.
    static func sessionID(in answer: JSONValue) throws -> String {
        guard let id = answer["session"]?.stringValue, isHexID(id) else {
            throw TecopaFailure(.environment, "The engine's answer has no session id.")
        }
        return id
    }

    /// The crop that `app/geo.py` frames for a session's tracks on one sheet. The
    /// two sizes are the caller's text, so they are escaped for the query.
    static func starterCrop(_ runtime: Runtime, session: String, fields: Fields) async throws -> [String] {
        let size = try printSize(fields)
        let path = "/sessions/\(session)/starter_crop?print_w=\(queryText(size.width))"
            + "&print_h=\(queryText(size.height))"
        guard let crop = cropTexts(try await runtime.client.debug(path)["starter_crop"]) else {
            throw TecopaFailure(.environment, "The engine's answer has no starter crop.")
        }
        return crop
    }

    /// A value for a URL query. Only the unreserved characters go in as they are.
    private static func queryText(_ text: String) -> String {
        let plain = CharacterSet(charactersIn:
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._")
        return text.addingPercentEncoding(withAllowedCharacters: plain) ?? ""
    }

    /// A session's own proof fields and crop. Without them, one `set` would put
    /// every other field of the session back to the engine's default. A session
    /// with no proof is the engine's 409, and it passes through.
    static func proofForm(_ runtime: Runtime, session: String) async throws -> (fields: Fields, crop: [String]) {
        let answer = try await runtime.client.debug("/sessions/\(session)/proof_form")
        guard case .object(let form)? = answer["proof_form"], let crop = cropTexts(answer["crop"]) else {
            throw TecopaFailure(.environment, "The engine's answer has no proof_form and crop.")
        }
        return (try fields(ofProofForm: form), crop)
    }

    /// The engine's `proof_form` object as form fields, by name. The engine leaves
    /// out a key with no value, so a null is skipped.
    static func fields(ofProofForm form: [String: JSONValue]) throws -> Fields {
        var fields = Fields()
        for name in form.keys.sorted() where form[name] != .null {
            guard let text = form[name].flatMap(formText) else {
                throw TecopaFailure(.environment, "The engine's proof_form field \(name) is not one value.")
            }
            fields.set(name, text)
        }
        return fields
    }

    /// POST one proof and return the PNG. The engine stamps the spec of this proof
    /// on the session, and each output route renders that spec.
    static func proof(_ runtime: Runtime, session: String, crop: [String],
                      fields: Fields) async throws -> Data {
        var form = Multipart()
        try form.field("session_id", session)
        for (name, value) in zip(["x0", "y0", "x1", "y1"], crop) { try form.field(name, value) }
        for pair in fields.pairs { try form.field(pair.name, pair.value) }
        let path = "/api/proof"
        return try file(runtime, try await runtime.client.post(path, form), for: path)
    }

    /// The bytes of a reply that is a file. Any status but 2xx is `refused`, with
    /// the engine's own body. A 2xx reply that is JSON is not a file, and the tool
    /// does not write it as one.
    ///
    /// The status is read first, and the body of a file is never read as text: a
    /// final can be hundreds of megabytes.
    static func file(_ runtime: Runtime, _ reply: HTTPReply, for path: String) throws -> Data {
        guard (200..<300).contains(reply.status) else {
            throw runtime.client.refusedFailure(reply.status, path, EngineClient.value(of: reply.body))
        }
        guard reply.contentType?.lowercased().hasPrefix("application/json") != true else {
            throw TecopaFailure(.environment, "The engine answered \(path) with JSON, not with a file.",
                                body: EngineClient.value(of: reply.body))
        }
        return reply.body
    }

    /// POST one output route: the session, then the fields. The answer names the job.
    static func submit(_ runtime: Runtime, path: String, session: String,
                       fields: Fields) async throws -> JSONValue {
        var form = Multipart()
        try form.field("session_id", session)
        for pair in fields.pairs { try form.field(pair.name, pair.value) }
        return try runtime.client.json(try await runtime.client.post(path, form), for: path)
    }

    /// The job id of a submit answer. It goes into a URL path, so an answer with
    /// another form is not used.
    static func jobID(in answer: JSONValue) throws -> String {
        guard let id = answer["job"]?.stringValue, isHexID(id) else {
            throw TecopaFailure(.environment, "The engine's answer has no job id.")
        }
        return id
    }

    /// The seconds between two polls, and the longest time one call waits for a job.
    static let pollInterval: Double = 1
    static let pollLimit: Double = 900
    static let fetchHint = "Run `tecopa render fetch`."

    /// Poll a job until it is done. A job that ends in `error` is `refused` with
    /// the job's own text. The tool never asks the engine to try again.
    static func wait(_ runtime: Runtime, job: String) async throws {
        var waited: Double = 0
        while true {
            let status = try await runtime.client.get("/api/jobs/" + job)
            switch status["state"]?.stringValue {
            case "done":
                return
            case "error":
                let said = status["error"]?.stringValue ?? "The engine gave no text."
                throw TecopaFailure(.refused, "Job \(job) ended in an error: \(said)", body: status)
            default:
                break                                   // queued or running
            }
            guard waited < pollLimit else {
                throw TecopaFailure(
                    .environment, "The job did not finish within \(secondsText(pollLimit)) seconds.")
            }
            await runtime.sleep(pollInterval)
            waited += pollInterval
        }
    }

    /// GET the file of a job that is done and write it to `out`. A job that is not
    /// done is the engine's 409, and it passes through.
    static func fetch(_ runtime: Runtime, job: String, out: String) async throws -> [String: JSONValue] {
        let path = "/api/jobs/\(job)/result"
        let data = try file(runtime, try await runtime.client.download(path), for: path)
        return try save(runtime, data, to: out)
    }

    /// Wait for a job, then write its file. This is the end of each output route,
    /// and of a reprint that is a film.
    ///
    /// A failure that is not the engine's refusal names the job: the time limit, a
    /// poll with no answer, a write that failed. The job can still end well, or its
    /// file is still on the engine, and the caller has no other way to learn the id.
    static func waitAndFetch(_ runtime: Runtime, job: String, out: String) async throws -> [String: JSONValue] {
        do {
            try await wait(runtime, job: job)
            return try await fetch(runtime, job: job, out: out)
        } catch let failure as TecopaFailure where failure.kind != .refused {
            throw TecopaFailure(failure.kind, failure.message + " The job is \(job).",
                                hint: fetchHint, status: failure.status, body: failure.body)
        }
    }

    /// POST one output route and follow its job. The result has `job`, and
    /// `skipped` or `frames` when the route gave one. `out` nil is `no_wait`: the
    /// call returns after the submit, with no poll and no file.
    static func submitAndFetch(_ runtime: Runtime, path: String, session: String, fields: Fields,
                               out: String?) async throws -> [String: JSONValue] {
        let answer = try await submit(runtime, path: path, session: session, fields: fields)
        let job = try jobID(in: answer)
        var result: [String: JSONValue] = ["job": .string(job)]
        for key in ["skipped", "frames"] {
            if let value = answer[key], value != .null { result[key] = value }
        }
        guard let out else { return result }
        result.merge(try await waitAndFetch(runtime, job: job, out: out)) { _, new in new }
        return result
    }

    // MARK: Results

    /// Write the bytes to a path that holds no file, and report them: `out`,
    /// `bytes` and `sha256`. A caller can compare two files by the last one.
    static func save(_ runtime: Runtime, _ data: Data, to out: String) throws -> [String: JSONValue] {
        try runtime.writeNew(out, data)
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        return ["out": .string(out), "bytes": .int(Int64(data.count)), "sha256": .string(digest)]
    }

    /// The running engine's version, which it stamps into each manifest. It needs
    /// the debug gate. With the gate off, or on any failure, there is no value, and
    /// a render never fails for it.
    static func engineVersion(_ runtime: Runtime) async -> String? {
        (try? await runtime.client.debug("/engine"))?["engine_version"]?.stringValue
    }

    static func withEngineVersion(_ result: [String: JSONValue],
                                  _ runtime: Runtime) async -> [String: JSONValue] {
        var result = result
        if let version = await engineVersion(runtime) { result["engine_version"] = .string(version) }
        return result
    }

    // MARK: The flow

    /// One output route: its path, and its key in /api/debug/forms.
    struct Output: Equatable, Sendable {
        let path: String
        let form: String
        /// True for the route that takes `presets`.
        var takesPresets = false

        static let final = Output(path: "/api/final/submit", form: "final_submit")
        static let wallpaper = Output(path: "/api/wallpapers/submit", form: "wallpapers_submit",
                                      takesPresets: true)
        static let film = Output(path: "/api/timelapse/submit", form: "timelapse_submit")
    }

    /// The flow of the four entries that make a picture. `output` nil is
    /// `render proof`: the proof itself is the file.
    static func render(_ runtime: Runtime, _ arguments: [String: JSONValue],
                       to output: Output?) async throws -> JSONValue {
        // 1. The arguments. Each check here is before the first request.
        let paths = strings(arguments["tracks"])
        let given = arguments["session"]?.stringValue.flatMap { $0.isEmpty ? nil : $0 }
        guard !paths.isEmpty || given != nil else {
            throw TecopaFailure(.usage, "Give tracks or a session.")
        }
        guard paths.isEmpty || given == nil else {
            throw TecopaFailure(.usage, "Give tracks or a session, not both.")
        }
        if let given { try checkID(given, "A session id") }
        let region = arguments["region"]?.stringValue
        if let region {
            guard given == nil else {
                throw TecopaFailure(.usage, "region goes with tracks. A session has its plate.")
            }
            guard ScriptRunner.isRegionID(region) else {
                throw TecopaFailure(.usage, "Not a region id: \(region)")
            }
        }
        let crop = try arguments["crop"]?.stringValue.map { try cropArgument($0) }
        // the picture: `spec`, then `set`
        var change = try arguments["spec"]?.stringValue.map { try specFields($0, runtime) } ?? Fields()
        change.merge(try pairs(strings(arguments["set"]), "set"))
        // the container: the fields of the output route
        var container = Fields()
        if let output, output.takesPresets {
            let presets = strings(arguments["presets"])
            guard !presets.isEmpty else {
                throw TecopaFailure(.usage, "presets is required: one wallpaper preset id or more.")
            }
            container.set("presets", presets.joined(separator: ","))
        }
        let options = try pairs(strings(arguments["opt"]), "opt")
        container.merge(options)
        // new tracks have no fields of their own, so the size must be whole here
        if given == nil, crop == nil, change.namesPrintSize { _ = try printSize(change) }
        let out = try outPath(arguments, runtime)
        let files = try uploads(paths, runtime)

        // 2. The names, against the engine's own lists.
        try await checkNames(runtime, [("proof", change.names), (output?.form ?? "", options.names)])

        // 3 to 6. The session, and the fields and the crop of the proof. A session
        // that is given and not changed has no proof: its stamped spec is used.
        var result: [String: JSONValue] = [:]
        let session: String
        var next: (crop: [String], fields: Fields)?
        if let given {
            session = given
            if output == nil || !change.isEmpty || crop != nil {
                let own = try await proofForm(runtime, session: session)
                var fields = own.fields
                fields.merge(change)
                let frame: [String]
                if let crop {
                    frame = crop
                } else if change.namesPrintSize {
                    frame = try await starterCrop(runtime, session: session, fields: fields)
                } else {
                    frame = own.crop
                }
                next = (frame, fields)
            }
        } else {
            let answer = try await upload(runtime, files, region: region)
            session = try sessionID(in: answer)
            if let plate = answer["region"]?.stringValue { result["region"] = .string(plate) }
            let frame: [String]
            if let crop {
                frame = crop
            } else if change.namesPrintSize {
                frame = try await starterCrop(runtime, session: session, fields: change)
            } else if let start = cropTexts(answer["starter_crop"]) {
                frame = start
            } else {
                throw TecopaFailure(.environment, "The engine's answer has no starter crop.")
            }
            next = (frame, change)
        }
        result["session"] = .string(session)

        // 7. The proof.
        var png: Data?
        if let next {
            png = try await proof(runtime, session: session, crop: next.crop, fields: next.fields)
        }

        // 8 to 10. The file: the proof itself, or the file of the output route's job.
        if let output {
            let made = try await submitAndFetch(runtime, path: output.path, session: session,
                                                fields: container, out: out)
            result.merge(made) { _, new in new }
        } else if let png, let out {
            result.merge(try save(runtime, png, to: out)) { _, new in new }
        }
        return .object(await withEngineVersion(result, runtime))
    }
}
