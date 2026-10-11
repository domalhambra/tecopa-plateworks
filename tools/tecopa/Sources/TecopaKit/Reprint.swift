import Foundation

/// The three entries that read a poster file: what it holds, the same picture
/// again, and its next edition.
///
/// The file is the archive: its manifest holds the spec, so no session is needed.
/// The tool sends the file's bytes unchanged and reads nothing from them. Each
/// request and each step of the render is a function of `Render`.
enum Reprint {
    static let entries: [CatalogEntry] = [inspectEntry, reprintEntry, continueEntry]

    // MARK: Entries

    private enum Parameter {
        static let file = EntryParameter(
            "file", .string, "The absolute path of a Tecopa Plateworks poster file. Required.")
        static let tracks = EntryParameter(
            "tracks", .stringArray, "Absolute GPX, KML or KMZ paths: the new tracks of this edition.")
        static let set = EntryParameter(
            "set", .stringArray,
            "key=value, one proof form field for each. Each one replaces a field of the file. "
                + "An unknown name is refused with the engine's list.")
        static let crop = EntryParameter(
            "crop", .string, "x0,y0,x1,y1 in overview pixels. Without it, the crop is the file's own.")
        static let reprintOpt = EntryParameter(
            "opt", .stringArray,
            "key=value, one field of the reprint route for each: format, embed_spec. "
                + "An unknown name is refused with the engine's list.")
        static let reprintOut = EntryParameter(
            "out", .string,
            "The absolute path of the file to write. It must hold no file. Required, with no_wait too.")
        static let reprintNoWait = EntryParameter(
            "no_wait", .boolean,
            "For a film: return the job id at once and write no file. Then run render_fetch. "
                + "A still is in the reply itself, and it is always written to out.")
        static let allowPlateMismatch = EntryParameter(
            "allow_plate_mismatch", .boolean,
            "Render on this engine's plate when it is not the plate of the file. Sent only when true.")
    }

    static let inspectEntry = CatalogEntry(
        name: "reprint_inspect",
        summary: "Read a poster file's manifest: the plate and its verdict, the sources, the edition. "
            + "Renders nothing.",
        readOnly: true,
        parameters: [Parameter.file]
    ) { runtime, arguments in
        let file = try poster(arguments, runtime)
        let path = "/api/reprint/inspect"
        return try runtime.client.json(
            try await runtime.client.post(path, try form(file, arguments)), for: path)
    }

    static let reprintEntry = CatalogEntry(
        name: "reprint",
        summary: "Render a poster file again from its own manifest, and write it to out. "
            + "A film is rendered as a job. One panel of a set gives the whole set, as a zip.",
        readOnly: false,
        parameters: [Parameter.file, Parameter.reprintOut, Parameter.reprintOpt,
                     Parameter.allowPlateMismatch, Parameter.reprintNoWait],
        text: Render.text
    ) { runtime, arguments in
        try await reprint(runtime, arguments)
    }

    static let continueEntry = CatalogEntry(
        name: "continue",
        summary: "Open a poster file for its next edition: add tracks, proof it, render the final, "
            + "and write it to out.",
        readOnly: false,
        parameters: [Parameter.file, Parameter.tracks, Parameter.set, Render.Parameter.opt,
                     Parameter.crop, Render.Parameter.out, Parameter.allowPlateMismatch,
                     Render.Parameter.noWait],
        text: Render.text
    ) { runtime, arguments in
        try await nextEdition(runtime, arguments)
    }

    // MARK: The file

    /// The poster file of a call: its name and its bytes, read before the first
    /// request. The engine has the size limit, 96 MB. The tool has none.
    static func poster(_ arguments: [String: JSONValue], _ runtime: Runtime) throws -> Render.Upload {
        guard let path = arguments["file"]?.stringValue, !path.isEmpty else {
            throw TecopaFailure(.usage, "file is required: the path of a poster file.")
        }
        return try Render.uploads([path], runtime, name: "file", what: "poster file")[0]
    }

    /// The form of a route that reads a poster file: the file, then the fields.
    ///
    /// This is the one place that writes `allow_plate_mismatch`, and it writes it
    /// only when the caller gave true. A refusal for another plate is the engine's
    /// 422, and the caller decides.
    static func form(_ file: Render.Upload, _ arguments: [String: JSONValue],
                     fields: Render.Fields = Render.Fields()) throws -> Multipart {
        var form = Multipart()
        try form.file("file", filename: file.filename, file.data)
        for pair in fields.pairs { try form.field(pair.name, pair.value) }
        if arguments["allow_plate_mismatch"]?.boolValue == true {
            try form.field("allow_plate_mismatch", "true")
        }
        return form
    }

    /// The bytes of a reply that is a still. `Render.file` refuses each status but
    /// 2xx, and a JSON reply. This refuses what is left that cannot be a poster: a
    /// reply with no content type, a text, or no bytes. Another program on the
    /// port can answer 200 with a page, and the tool does not write that page to
    /// `out` as the poster.
    static func still(_ runtime: Runtime, _ reply: HTTPReply, for path: String) throws -> Data {
        let data = try Render.file(runtime, reply, for: path)
        let kind = reply.contentType?.lowercased()
        guard let kind, !kind.hasPrefix("text/"), !data.isEmpty else {
            throw TecopaFailure(
                .environment, runtime.client.notTecopaMessage,
                hint: "The answer for \(path) is not a poster. " + EngineClient.notTecopaHint)
        }
        return data
    }

    // MARK: The flows

    /// `reprint`. The route answers a still with the poster itself, and a film
    /// with JSON that names a job.
    static func reprint(_ runtime: Runtime, _ arguments: [String: JSONValue]) async throws -> JSONValue {
        // 1. The arguments. Each check here is before the first request.
        let file = try poster(arguments, runtime)
        let options = try Render.pairs(Render.strings(arguments["opt"]), "opt")
        // The tool cannot know before the reply if the file is a still. A still is
        // the reply itself, with no job to fetch later, so there is always a path
        // for it: with `no_wait` too.
        guard let given = arguments["out"]?.stringValue, !given.isEmpty else {
            throw TecopaFailure(
                .usage, "out is required: a still is in the reply itself, so it needs the path of its file.",
                hint: "With no_wait, a film returns its job id and writes nothing.")
        }
        let out = try Render.freePath(given, runtime)

        // 2. The names, against the engine's own list.
        try await Render.checkNames(runtime, [("reprint", options.names)])

        // 3. The reply. The content type is read first: the bytes of a poster are
        // never read as JSON.
        let path = "/api/reprint"
        let reply = try await runtime.client.post(path, try form(file, arguments, fields: options))
        var result: [String: JSONValue]
        if (200..<300).contains(reply.status), Render.isJSON(reply),
           let answer = try? JSONValue.parse(reply.body), answer["job"] != nil {
            let wait = arguments["no_wait"]?.boolValue != true
            result = try await Render.follow(runtime, answer: answer, out: wait ? out : nil)
        } else {
            // `still` refuses each status but 2xx with the engine's own body, a
            // JSON reply that names no job, and a reply that is not a poster.
            result = try Render.save(runtime, try still(runtime, reply, for: path), to: out)
        }
        return .object(await Render.withEngineVersion(result, runtime))
    }

    /// `continue`: the session of the next edition, the new tracks, one proof,
    /// then the final as `render final` makes it.
    static func nextEdition(_ runtime: Runtime, _ arguments: [String: JSONValue]) async throws -> JSONValue {
        // 1. The arguments. Each check here is before the first request.
        let file = try poster(arguments, runtime)
        let files = try Render.uploads(Render.strings(arguments["tracks"]), runtime)
        let crop = try arguments["crop"]?.stringValue.map { try Render.cropArgument($0) }
        let change = try Render.pairs(Render.strings(arguments["set"]), "set")
        let options = try Render.pairs(Render.strings(arguments["opt"]), "opt")
        let out = try Render.outPath(arguments, runtime)

        // 2. The names, against the engine's own lists.
        let output = Render.Output.final
        try await Render.checkNames(runtime, [("proof", change.names), (output.form, options.names)])

        // 3. The session of the next edition. The answer has the /api/upload shape,
        // with the track geometry and the studio's prefill, which no result keeps.
        let path = "/api/continue"
        let answer = try runtime.client.json(
            try await runtime.client.post(path, try form(file, arguments)), for: path)
        let session = try Render.sessionID(in: answer)
        guard case .object(let proofForm)? = answer["proof_form"],
              let frame = Render.cropTexts(answer["starter_crop"]) else {
            throw TecopaFailure(.environment, "The engine's answer has no proof_form and starter crop.",
                                hint: "The engine may be older than the tool. Run `tecopa doctor`.")
        }
        let own = (fields: try Render.fields(ofProofForm: proofForm), crop: frame)

        // 4. The new tracks go into that session. The engine makes a new session
        // for an id it does not have, and that one is not the continued poster.
        var result: [String: JSONValue] = ["session": .string(session)]
        if !files.isEmpty {
            let upload = try await Render.upload(runtime, files, session: session)
            let added = try Render.sessionID(in: upload)
            guard added == session else {
                throw TecopaFailure(
                    .environment,
                    "The engine put the new tracks in session \(added), not in the continued session \(session).")
            }
            if let warnings = Render.warnings(ofUpload: upload) { result["upload"] = warnings }
        }

        // 5. The proof: the file's own fields, then `set`. It stamps the new edition.
        let next = try await Render.changedProof(runtime, session: session, own: own,
                                                 change: change, crop: crop)
        _ = try await Render.proof(runtime, session: session, crop: next.crop, fields: next.fields)

        // 6. The final.
        if let plate = answer["region"]?.stringValue { result["region"] = .string(plate) }
        if let edition = answer["edition"]?.intValue { result["edition"] = .int(Int64(edition)) }
        if let span = answer["year_span"]?.stringValue, !span.isEmpty { result["year_span"] = .string(span) }
        let made = try await Render.submitAndFetch(runtime, path: output.path, session: session,
                                                   fields: options, out: out)
        result.merge(made) { _, new in new }
        return .object(await Render.withEngineVersion(result, runtime))
    }
}
