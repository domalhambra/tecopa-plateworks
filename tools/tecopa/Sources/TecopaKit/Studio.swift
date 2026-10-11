import Foundation

/// The two entries that read what the studio reported: the small state of each
/// browser tab, and the errors of all tabs. A fault in the page is read here, with
/// no browser.
///
/// The engine holds the reports in memory and answers both lists at one debug
/// route, newest first. Each entry returns its list as the engine gave it. The
/// route has no filter, so `studio errors` filters in the tool. A report never
/// holds journey data: the engine keeps a few named keys of a state and no other.
enum Studio {
    static let entries: [CatalogEntry] = [stateEntry, errorsEntry]

    /// The kinds of error the engine keeps: an uncaught error, a rejected promise,
    /// and an error toast.
    static let kinds = ["error", "rejection", "toast"]

    // MARK: Entries

    static let stateEntry = CatalogEntry(
        name: "studio_state",
        summary: "List each studio tab that has reported, newest first: its session, target, view, "
            + "region and proof flags.",
        readOnly: true,
        text: stateText
    ) { runtime, _ in
        .object(["tabs": .array(try await list("tabs", runtime))])
    }

    static let errorsEntry = CatalogEntry(
        name: "studio_errors",
        summary: "List the errors the studio's tabs reported, newest first: uncaught errors, "
            + "rejected promises and error toasts.",
        readOnly: true,
        parameters: [
            EntryParameter("tab", .string, "A tab id from studio_state. Keeps only that tab's errors."),
            EntryParameter("kind", .string, "error, rejection or toast. Keeps only that kind."),
        ],
        text: errorsText
    ) { runtime, arguments in
        // Each check here is before the request.
        let tab = arguments["tab"]?.stringValue
        if let tab, !isTabID(tab) {
            throw TecopaFailure(
                .usage, "A tab id is 8 to 32 characters of a-z and 0-9: \(tab.debugDescription)",
                hint: "Run `tecopa studio state` for the ids.")
        }
        let kind = arguments["kind"]?.stringValue
        if let kind, !kinds.contains(kind) {
            throw TecopaFailure(
                .usage, "kind is one of \(kinds.joined(separator: ", ")): \(kind.debugDescription)")
        }
        let errors = try await list("errors", runtime).filter { error in
            (tab == nil || error["tab"]?.stringValue == tab)
                && (kind == nil || error["kind"]?.stringValue == kind)
        }
        return .object(["errors": .array(errors)])
    }

    /// True for the form of a tab id, which the studio makes and the engine checks:
    /// 8 to 32 characters of a-z and 0-9. The check reads bytes, so a fullwidth
    /// letter and a line end are not in it.
    static func isTabID(_ tab: String) -> Bool {
        let bytes = Array(tab.utf8)
        return (8...32).contains(bytes.count)
            && bytes.allSatisfy { (0x61...0x7A).contains($0) || (0x30...0x39).contains($0) }
    }

    /// One list of the engine's report. With no report yet the list is empty. An
    /// answer without the list is not an empty buffer, so it is a failure.
    static func list(_ key: String, _ runtime: Runtime) async throws -> [JSONValue] {
        guard let list = try await runtime.client.debug("/studio")[key]?.arrayValue else {
            throw TecopaFailure(.environment, "The engine's answer has no list of \(key).",
                                hint: "The engine may be older than the tool. Run `tecopa doctor`.")
        }
        return list
    }

    // MARK: Text

    /// The engine's `received`, seconds since 1970 on its own clock, as an ISO 8601
    /// time in UTC with whole seconds. The tool has no clock, so it prints no age.
    static func time(_ value: JSONValue?) -> String {
        let seconds: Double
        switch value {
        case .int(let number)?: seconds = Double(number)
        case .double(let number)?: seconds = number
        default: return "-"
        }
        // a number that is no time on a calendar is not printed as one
        guard seconds.isFinite, abs(seconds) < 1e11 else { return "-" }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.string(from: Date(timeIntervalSince1970: seconds.rounded(.down)))
    }

    /// One value of a state as text, or a dash when the state has none.
    private static func scalar(_ value: JSONValue?) -> String {
        value.flatMap(Render.formText) ?? "-"
    }

    /// One line for each tab: the tab, the time of its last report, then its state.
    static let stateText: @Sendable (JSONValue) -> String = { data in
        let tabs = data["tabs"]?.arrayValue ?? []
        guard !tabs.isEmpty else { return "No studio tab has reported." }
        return tabs.map { row in
            let head = "\(scalar(row["tab"]))  \(time(row["received"]))"
            // a tab that sent errors before its first state has none
            guard case .object(let state)? = row["state"] else { return head + "  no state" }
            let keys = ["target", "view", "session", "region", "has_spec", "proof_stale"]
            return ([head] + keys.map { "\($0)=\(scalar(state[$0]))" }).joined(separator: "  ")
        }.joined(separator: "\n")
    }

    /// For each error: a line with the time, the tab and the kind, then the
    /// message, then the source and its line, then the stack with an indent. The
    /// text is the engine's, which has removed the control characters. The tool
    /// removes nothing and adds nothing to it.
    static let errorsText: @Sendable (JSONValue) -> String = { data in
        let errors = data["errors"]?.arrayValue ?? []
        guard !errors.isEmpty else { return "No errors reported." }
        return errors.map { error in
            var lines = ["\(time(error["received"]))  \(scalar(error["tab"]))  \(scalar(error["kind"]))"]
            if let message = error["message"]?.stringValue, !message.isEmpty { lines.append(message) }
            if let source = error["source"]?.stringValue, !source.isEmpty {
                lines.append(error["line"]?.intValue.map { "\(source):\($0)" } ?? source)
            }
            if let stack = error["stack"]?.stringValue, !stack.isEmpty {
                lines += stack.components(separatedBy: "\n").map { "    " + $0 }
            }
            return lines.joined(separator: "\n")
        }.joined(separator: "\n\n")
    }
}
