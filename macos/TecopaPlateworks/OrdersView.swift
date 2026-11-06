import AppKit
import SwiftUI
import TecopaKit

/// One row of GET /api/orders.
struct OrderRow: Identifiable, Hashable {
    var folder: String
    var name: String
    var number: String
    var title: String
    var prepared: Bool
    var approved: Bool
    var id: String { folder }

    init?(_ j: JSONValue) {
        guard let folder = j["folder"]?.stringValue, let name = j["name"]?.stringValue else { return nil }
        self.folder = folder
        self.name = name
        number = j["order_number"]?.stringValue ?? ""
        title = j["title"]?.stringValue ?? name
        prepared = j["prepared"]?.boolValue ?? false
        approved = j["approved"]?.boolValue ?? false
    }

    var stage: String { approved ? "Approved" : prepared ? "Prepared" : "New" }
}

/// The Orders pane: every order, and one button per step of docs/changing-things.md >
/// Run an order (phase 2 spec). Each step is a TecopaKit catalog entry; a refusal shows
/// the engine's words as they are.
struct OrdersView: View {
    @Environment(AppModel.self) private var model
    @State private var orders: [OrderRow] = []
    @State private var selection: OrderRow.ID?
    @State private var loadError: String?
    @State private var showingNew = false

    var body: some View {
        HSplitView {
            VStack(spacing: 0) {
                List(orders, selection: $selection) { o in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(o.title).font(.headline).lineLimit(1)
                        HStack {
                            Text(o.number.isEmpty ? o.name : o.number)
                            Spacer()
                            Text(o.stage).foregroundStyle(o.approved ? .green : o.prepared ? .blue : .secondary)
                        }
                        .font(.caption)
                    }
                    .padding(.vertical, 2)
                    .tag(o.id)
                }
                .overlay {
                    if orders.isEmpty && loadError == nil {
                        // A first launch: say why the list is empty and where it reads.
                        ContentUnavailableView("No orders yet", systemImage: "tray",
                                               description: Text("Orders are the folders in your orders folder (Settings > General). Make one from an intake number with New Order."))
                    }
                }
                if let loadError {
                    Text(loadError).font(.caption).foregroundStyle(.red).padding(6)
                }
            }
            .frame(minWidth: 240, idealWidth: 300, maxWidth: 380)

            Group {
                if let o = orders.first(where: { $0.id == selection }) {
                    OrderDetail(order: o, reload: { Task { await load() } })
                        .id(o.id)
                } else {
                    ContentUnavailableView("No order selected", systemImage: "shippingbox",
                                           description: Text("Choose an order, or make one from an intake number."))
                }
            }
            .frame(minWidth: 520, maxWidth: .infinity, maxHeight: .infinity)
        }
        .toolbar {
            ToolbarItemGroup {
                Button { showingNew = true } label: { Label("New Order", systemImage: "plus") }
                    .help("Make an order folder from an intake number, like TP-26-001")
                Button { Task { await load() } } label: { Label("Refresh", systemImage: "arrow.clockwise") }
                Button {
                    NSWorkspace.shared.open(URL(fileURLWithPath: ordersRoot))
                } label: { Label("Orders Folder", systemImage: "folder") }
            }
        }
        .sheet(isPresented: $showingNew) {
            NewOrderSheet { await load() }
        }
        .task { await load() }
    }

    private var ordersRoot: String {
        let settings = (try? EngineEnvironment.settings(
            from: FileManager.default.contents(atPath: model.settingsPath), path: model.settingsPath)) ?? [:]
        return settings["TECOPA_ORDERS_DIR"] ?? (model.runtime.home + "/Tecopa Orders")
    }

    private func load() async {
        do {
            let j = try await model.runtime.client.get("/api/orders")
            orders = (j.arrayValue ?? []).compactMap(OrderRow.init)
            loadError = nil
            if selection == nil { selection = orders.first?.id }
        } catch {
            loadError = "The orders could not be read: \(error)"
        }
    }
}

// MARK: - New order

struct NewOrderSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let done: () async -> Void
    @State private var number = "TP-\(String(Calendar.current.component(.year, from: Date())).suffix(2))-"
    @State private var busy = false
    @State private var output = ""
    @State private var failed = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("New order from the intake").font(.headline)
            Text("Copies the client's files from the job folder in Dropbox into a new order folder. It never writes to Dropbox, and a second run adds only new files.")
                .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            TextField("Order number", text: $number).textFieldStyle(.roundedBorder).font(.body.monospaced())
                .onSubmit { Task { await run() } }
            if !output.isEmpty {
                ScrollView { Text(output).font(.callout.monospaced()).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading) }
                    .frame(minHeight: 120, maxHeight: 260)
                    .foregroundStyle(failed ? .red : .primary)
            }
            HStack {
                Spacer()
                Button("Close") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Make Order") { Task { await run() } }
                    .keyboardShortcut(.defaultAction).disabled(busy || number.count < 9)
            }
        }
        .padding(20)
        .frame(width: 520)
    }

    private func run() async {
        guard !busy else { return }
        busy = true; defer { busy = false }
        switch await model.call("order_new", ["number": .string(number.trimmingCharacters(in: .whitespaces))]) {
        case .success(let d):
            failed = false
            output = d["output"]?.stringValue ?? "Done."
            await done()
        case .failure(let f):
            failed = true
            output = [f.message, f.hint].compactMap { $0 }.joined(separator: "\n")
        }
    }
}

// MARK: - One order

struct OrderDetail: View {
    @Environment(AppModel.self) private var model
    let order: OrderRow
    let reload: () -> Void

    @State private var note: (text: String, error: Bool)?
    @State private var previewSizes: [PreviewSize] = []
    @State private var desk: DeskOrder?
    @State private var deskNote = ""
    @State private var prepareReport = ""
    @State private var printNote = ""

    private var folderURL: URL { URL(fileURLWithPath: order.folder) }
    /// The order's run lives in the model, so it outlasts this view (one at a time).
    private var run: RunTracker? { model.orderRuns[order.folder] }
    /// A step runs, or one is being started: the run buttons wait for either.
    private var stepLocked: Bool { run?.isRunning == true || model.startingOrders.contains(order.folder) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                header
                if let run { RunPanel(run: run) { note = ($0, true) } }
                if let note {
                    Text(note.text).textSelection(.enabled)
                        .foregroundStyle(note.error ? .red : .primary)
                        .padding(10).frame(maxWidth: .infinity, alignment: .leading)
                        .background(RoundedRectangle(cornerRadius: 8).fill(.quaternary))
                }
                step("1. Preview", "Frames every size, builds a coarse plate, and writes the PDF and the email for the client.") {
                    previewStep
                }
                step("2. Prepare", "Builds the order's plate, frames the chosen size, and writes the client's proof.") {
                    prepareStep
                }
                step("3. Proof and approve", "Open the order in the studio. Render, Save to order, send the proof from HEY, and Approve when the client agrees.") {
                    HStack {
                        Button("Open in Studio") { model.openStudio(order: order.name) }
                            .disabled(!order.prepared)
                        if order.approved { Label("Approved", systemImage: "checkmark.seal.fill").foregroundStyle(.green) }
                    }
                }
                step("4. Finish", "Writes the print TIFFs at 300 ppi and PRINT.txt, for the approved proof.") {
                    finishStep
                }
            }
            .padding(20)
            .frame(maxWidth: 820, alignment: .leading)
        }
        .task {
            await refresh()
            await model.adoptOrderRun(folder: order.folder) { await refresh(); reload() }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(order.title).font(.title2.weight(.semibold))
            HStack(spacing: 12) {
                if !order.number.isEmpty { Text(order.number).font(.body.monospaced()) }
                Text(order.stage).foregroundStyle(.secondary)
                Spacer()
                Button("Show in Finder") { NSWorkspace.shared.activateFileViewerSelecting([folderURL]) }
                Button("Open order.toml") { NSWorkspace.shared.open(folderURL.appendingPathComponent("order.toml")) }
            }
        }
    }

    // MARK: Preview

    @ViewBuilder private var previewStep: some View {
        HStack {
            Button("Run Preview") { Task { await start("order_preview") } }.disabled(stepLocked)
            if let pdf = previewPDF {
                Button("Open PDF") { NSWorkspace.shared.open(pdf) }
                Button("Copy Email") { copyEmail() }.disabled(emailText == nil)
                    .help("Puts out/preview/email.txt on the clipboard, to paste into HEY. Nothing is sent.")
                Button("Reveal PDF") { NSWorkspace.shared.activateFileViewerSelecting([pdf]) }
            }
        }
        if !deskNote.isEmpty { Text(deskNote).font(.callout).foregroundStyle(.secondary) }
        if !previewSizes.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(previewSizes) { s in
                    HStack(alignment: .firstTextBaseline) {
                        Image(systemName: s.offered ? (isPaid(s) ? "checkmark.circle.fill" : "circle") : "xmark.circle")
                            .foregroundStyle(s.offered ? (isPaid(s) ? .green : .secondary) : .red)
                        VStack(alignment: .leading, spacing: 1) {
                            Text("\(s.label), \(s.orientation)").fontWeight(isPaid(s) ? .semibold : .regular)
                            if let why = s.why, !s.offered { Text("Not offered: \(why)").font(.caption).foregroundStyle(.secondary) }
                            if let w = s.warning { Text("Warning: \(w)").font(.caption).foregroundStyle(.orange) }
                        }
                        Spacer()
                        if s.offered {
                            Button(isPaid(s) ? "Choose (paid)" : "Choose") { Task { await choose(s) } }
                        }
                    }
                }
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 8).strokeBorder(.quaternary))
        }
    }

    private func isPaid(_ s: PreviewSize) -> Bool {
        guard let desk, desk.paid else { return false }
        return deskSizeMatches(desk.size, key: s.key)
    }

    /// The PDF the last preview wrote (preview.json's `pdf`); the newest one if older
    /// previews left others under another title.
    private var previewPDF: URL? {
        if let data = FileManager.default.contents(atPath: order.folder + "/work/preview/preview.json"),
           let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let pdf = root["pdf"] as? String {
            let url = pdf.hasPrefix("/") ? URL(fileURLWithPath: pdf) : folderURL.appendingPathComponent(pdf)
            if FileManager.default.fileExists(atPath: url.path) { return url }
        }
        let dir = folderURL.appendingPathComponent("out/preview")
        let pdfs = ((try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.contentModificationDateKey])) ?? [])
            .filter { $0.pathExtension == "pdf" }
        return pdfs.max { a, b in
            let da = (try? a.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let db = (try? b.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            return da < db
        }
    }

    private var emailText: String? {
        try? String(contentsOf: folderURL.appendingPathComponent("out/preview/email.txt"), encoding: .utf8)
    }

    private func copyEmail() {
        guard let t = emailText else { return }
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(t, forType: .string)
        note = ("The email is on the clipboard. Paste it into a new email in HEY, attach the PDF, read it, and send it.", false)
    }

    private func choose(_ s: PreviewSize) async {
        switch await model.call("order_choose", ["folder": .string(order.folder), "size": .string(s.key)]) {
        case .success(let d): note = (d["output"]?.stringValue ?? "Chose \(s.key).", false)
        case .failure(let f): note = (f.message, true)
        }
    }

    // MARK: Prepare

    @ViewBuilder private var prepareStep: some View {
        HStack {
            Button("Run Prepare") { Task { await start("order_prepare") } }.disabled(stepLocked)
            let soft = folderURL.appendingPathComponent("work/softproof.png")
            if FileManager.default.fileExists(atPath: soft.path) {
                Button("Open Soft Proof") { NSWorkspace.shared.open(soft) }
            }
            let proofDir = folderURL.appendingPathComponent("out/proof")
            if FileManager.default.fileExists(atPath: proofDir.path) {
                Button("Reveal Client Proof") { NSWorkspace.shared.activateFileViewerSelecting([proofDir]) }
            }
        }
        if !prepareReport.isEmpty { ReportText(text: prepareReport) }
    }

    // MARK: Finish

    @ViewBuilder private var finishStep: some View {
        HStack {
            Button("Run Finish") { Task { await start("order_finish") } }
                .disabled(stepLocked || !order.prepared)
            let printDir = folderURL.appendingPathComponent("out/print")
            ForEach(tiffs, id: \.self) { t in
                Button("Open \(t.lastPathComponent)") { NSWorkspace.shared.open(t) }
            }
            if FileManager.default.fileExists(atPath: printDir.path) {
                Button("Reveal Prints") { NSWorkspace.shared.activateFileViewerSelecting([printDir]) }
            }
        }
        if !printNote.isEmpty { ReportText(text: printNote) }
    }

    private var tiffs: [URL] {
        let dir = folderURL.appendingPathComponent("out/print")
        return ((try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? [])
            .filter { $0.pathExtension.lowercased() == "tif" }.sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    // MARK: Runs

    private func start(_ entry: String) async {
        note = nil
        if let refused = await model.startOrderRun(entry, folder: order.folder, then: { await refresh(); reload() }) {
            note = (refused, true)
        }
    }

    private func refresh() async {
        previewSizes = PreviewSize.load(folder: order.folder)
        prepareReport = (try? String(contentsOf: folderURL.appendingPathComponent("work/report.txt"), encoding: .utf8)) ?? ""
        printNote = (try? String(contentsOf: folderURL.appendingPathComponent("out/print/PRINT.txt"), encoding: .utf8)) ?? ""
        guard !order.number.isEmpty else { deskNote = ""; return }
        switch await DeskClient.order(order.number) {
        case .success(let d):
            desk = d
            deskNote = d.map { $0.paid ? "Paid on the order desk: \($0.size.isEmpty ? "size not recorded" : $0.size)" : "Not paid yet on the order desk." }
                ?? "The order desk has no row for \(order.number)."
        case .failure(let e):
            desk = nil
            deskNote = e.message
        }
    }

    // MARK: Layout

    private func step<Content: View>(_ title: String, _ detail: String,
                                     @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.headline)
            Text(detail).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// A report with its warnings first (changing-things, Run an order, step 7).
struct ReportText: View {
    let text: String
    var body: some View {
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        let warnings = lines.filter { $0.contains("Warning") || $0.contains("HOLES IN THE PRINT") || $0.contains("NOT RENDERED") }
        VStack(alignment: .leading, spacing: 6) {
            if !warnings.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(warnings.enumerated()), id: \.offset) { _, w in
                        Label(w.trimmingCharacters(in: .whitespaces), systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(w.contains("HOLES") ? .red : .orange)
                    }
                }
            }
            DisclosureGroup("Full report") {
                Text(text).font(.callout.monospaced()).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }
}

// MARK: - Runs

@MainActor
@Observable
final class RunTracker {
    let id: String
    let title: String
    var state = "running"
    var exitCode: Int?
    var lines: [String] = []
    var isRunning: Bool { state == "running" }

    init(id: String, title: String) { self.id = id; self.title = title }

    /// Poll the run record every 2 s until it ends (phase 2 spec, decision 15).
    func follow(_ model: AppModel, ended: @escaping () async -> Void) async {
        while true {
            if case .success(let d) = await model.call("runs_show", ["run": .string(id), "lines": .int(40)]) {
                state = d["state"]?.stringValue ?? state
                exitCode = d["exit_code"]?.intValue
                lines = (d["lines"]?.arrayValue ?? []).compactMap { $0.stringValue }
            }
            if !isRunning { await ended(); return }
            try? await Task.sleep(for: .seconds(2))
        }
    }

    /// Cancel the run; the engine's words when it refuses.
    func cancel(_ model: AppModel) async -> String? {
        if case .failure(let f) = await model.call("runs_cancel", ["run": .string(id)]) {
            return [f.message, f.hint].compactMap { $0 }.joined(separator: "\n")
        }
        return nil
    }
}

struct RunPanel: View {
    @Environment(AppModel.self) private var model
    let run: RunTracker
    var refused: (String) -> Void = { _ in }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                if run.isRunning { ProgressView().controlSize(.small) }
                Text("\(run.title): \(run.state)").font(.headline)
                    .foregroundStyle(run.state == "failed" ? .red : run.state == "done" ? .green : .primary)
                Spacer()
                if run.isRunning { Button("Cancel") { Task { if let r = await run.cancel(model) { refused(r) } } } }
            }
            ScrollView {
                Text(run.lines.joined(separator: "\n")).font(.caption.monospaced()).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(height: 140)
            .defaultScrollAnchor(.bottom)
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 8).fill(.quaternary))
    }
}
