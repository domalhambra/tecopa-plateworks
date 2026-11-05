import AppKit
import SwiftUI
import TecopaKit

struct PlateRow: Identifiable {
    var id: String
    var name: String
    var ready: Bool
    var demPresent: Bool
    var problem: String?
}

/// The Plates pane: each plate's readiness and its cached DEM, the Dropbox restore and
/// Free Space (phase 1 spec 6, phase 2 spec decision 12), verify, and a new plate.
struct PlatesView: View {
    @Environment(AppModel.self) private var model
    @State private var plates: [PlateRow] = []
    @State private var selection: PlateRow.ID?
    @State private var output = ""
    @State private var failed = false
    @State private var busy = false
    @State private var build: (title: String, state: String, progress: String)?
    @State private var showingNew = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Table(plates, selection: $selection) {
                TableColumn("Plate") { p in
                    VStack(alignment: .leading) {
                        Text(p.name)
                        Text(p.id).font(.caption.monospaced()).foregroundStyle(.secondary)
                    }
                }
                TableColumn("Terrain") { p in
                    if p.demPresent {
                        Label(p.ready ? "Ready" : "Not ready", systemImage: p.ready ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                            .foregroundStyle(p.ready ? .green : .orange)
                    } else {
                        Label("Not cached", systemImage: "icloud.and.arrow.down").foregroundStyle(.secondary)
                    }
                }
                .width(min: 110, ideal: 130)
                TableColumn("Note") { p in Text(p.problem ?? "").font(.caption).foregroundStyle(.secondary).lineLimit(2) }
            }
            .frame(minHeight: 260)
            Divider()
            VStack(alignment: .leading, spacing: 8) {
                if let build {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            if build.state == "running" || build.state == "queued" { ProgressView().controlSize(.small) }
                            Text("\(build.title): \(build.state)").font(.headline)
                                .foregroundStyle(build.state == "error" ? .red : build.state == "done" ? .green : .primary)
                        }
                        Text(build.progress).font(.caption.monospaced()).textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .padding(10).background(RoundedRectangle(cornerRadius: 8).fill(.quaternary))
                }
                if !output.isEmpty {
                    ScrollView {
                        Text(output).font(.callout.monospaced()).textSelection(.enabled)
                            .foregroundStyle(failed ? .red : .primary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 220)
                }
            }
            .padding(12)
        }
        .toolbar {
            ToolbarItemGroup {
                Button { Task { await act("plate_restore") } } label: { Label("Restore from Dropbox", systemImage: "icloud.and.arrow.down") }
                    .disabled(selection == nil || busy)
                    .help("Copy this plate's DEM back from the Dropbox archive, checked by its sha256")
                Button { Task { await act("plate_evict") } } label: { Label("Free Space", systemImage: "externaldrive.badge.minus") }
                    .disabled(selection == nil || busy)
                    .help("Delete this plate's cached DEM. It refuses while an order run is going.")
                Button { Task { await verify() } } label: { Label("Verify", systemImage: "checkmark.shield") }
                    .disabled(busy)
                Button { showingNew = true } label: { Label("New Plate", systemImage: "plus") }
                Button { Task { await load() } } label: { Label("Refresh", systemImage: "arrow.clockwise") }
            }
        }
        .sheet(isPresented: $showingNew) {
            NewPlateSheet { jid, title in await follow(jid, title) }
        }
        .task { await load() }
    }

    private func load() async {
        switch await model.call("regions") {
        case .success(let d):
            let names = Dictionary(uniqueKeysWithValues: (d["regions"]?.arrayValue ?? []).compactMap { r -> (String, String)? in
                guard let id = r["id"]?.stringValue else { return nil }
                return (id, r["name"]?.stringValue ?? id)
            })
            plates = (d["readiness"]?.arrayValue ?? []).compactMap { r in
                guard let id = r["id"]?.stringValue else { return nil }
                var problem: String? = r["error"]?.stringValue
                if problem == nil, r["crs_match"]?.boolValue == false { problem = "The DEM's projection is not the plate's." }
                if problem == nil, let drift = r["bounds_drift_m"], r["bounds_match"]?.boolValue == false {
                    problem = "The DEM's bounds drift \(drift.text(pretty: false)) m from the plate."
                }
                return PlateRow(id: id, name: names[id] ?? id, ready: r["ready"]?.boolValue ?? false,
                                demPresent: r["dem_present"]?.boolValue ?? false, problem: problem)
            }.sorted { $0.name < $1.name }
        case .failure(let f):
            failed = true; output = f.message
        }
    }

    /// Follow the engine's build job (GET /api/regions/build/<job>) until it ends.
    private func follow(_ jid: String, _ title: String) async {
        build = (title, "queued", "")
        while true {
            if let j = try? await model.runtime.client.get("/api/regions/build/\(jid)") {
                let state = j["state"]?.stringValue ?? "?"
                let progress = j["error"]?.stringValue ?? j["progress"]?.stringValue ?? ""
                build = (title, state, progress)
                if state == "done" || state == "error" { await load(); return }
            }
            try? await Task.sleep(for: .seconds(2))
        }
    }

    private func verify() async {
        busy = true; defer { busy = false }
        var args: [String: JSONValue] = [:]
        if let selection { args["regions"] = .array([.string(selection)]) }
        show(await model.call("regions_verify", args))
    }

    private func act(_ entry: String) async {
        guard let selection else { return }
        busy = true; defer { busy = false }
        show(await model.call(entry, ["id": .string(selection)]))
        await load()
    }

    private func show(_ r: Result<JSONValue, TecopaFailure>) {
        switch r {
        case .success(let d):
            failed = false
            output = d["output"]?.stringValue ?? d.text(pretty: true)
        case .failure(let f):
            failed = true
            output = [f.message, f.hint].compactMap { $0 }.joined(separator: "\n")
        }
    }
}

/// Plan a plate from tracks, then build it (plate_plan, then plate_build).
struct NewPlateSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let started: (String, String) async -> Void
    @State private var tracks: [URL] = []
    @State private var plan: JSONValue?
    @State private var name = ""
    @State private var message = ""
    @State private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("New plate").font(.headline)
            HStack {
                Button("Choose Tracks…") { pick() }
                Text(tracks.isEmpty ? "No tracks" : tracks.map(\.lastPathComponent).joined(separator: ", "))
                    .lineLimit(2).foregroundStyle(.secondary)
            }
            if let plan {
                Grid(alignment: .leading) {
                    GridRow { Text("Id"); Text(plan["id"]?.stringValue ?? "").font(.body.monospaced()) }
                    GridRow { Text("EPSG"); Text(plan["epsg"]?.text(pretty: false) ?? "") }
                    GridRow { Text("Grid"); Text("\(plan["resolution_m"]?.text(pretty: false) ?? "?") m") }
                    GridRow { Text("DEM"); Text("about \(plan["est_dem_mb"]?.text(pretty: false) ?? "?") MB") }
                }
                TextField("Name", text: $name).textFieldStyle(.roundedBorder)
            }
            if !message.isEmpty { Text(message).foregroundStyle(.red).textSelection(.enabled) }
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Build") { Task { await build() } }
                    .keyboardShortcut(.defaultAction).disabled(plan == nil || name.isEmpty || busy || !message.isEmpty)
            }
        }
        .padding(20).frame(width: 520)
    }

    private func pick() {
        let p = NSOpenPanel()
        p.allowsMultipleSelection = true
        p.allowedContentTypes = []
        p.message = "Choose GPX, KML or KMZ tracks"
        guard p.runModal() == .OK else { return }
        tracks = p.urls
        Task { await planIt() }
    }

    private func planIt() async {
        busy = true; defer { busy = false }
        switch await model.call("plate_plan", ["tracks": .array(tracks.map { .string($0.path) })]) {
        case .success(let d):
            plan = d; message = ""
            name = d["name_prefill"]?.stringValue ?? ""
            // The engine's own refusals, before Build: the studio's create flow says the same.
            if d["us_covered"]?.boolValue == false { message = "USGS 3DEP terrain covers the US only: a plate cannot be built here." }
            else if d["over_budget"]?.boolValue == true { message = "This area is too large to build from the app (corridor-scale grid)." }
            else if d["prep_ready"]?.boolValue == false { message = "The region-prep interpreter is missing from this app." }
        case .failure(let f): message = f.message
        }
    }

    /// Build through the engine (POST /api/regions/build), so its checks, the labels
    /// and the plate list refresh all apply.
    private func build() async {
        guard let plan else { return }
        busy = true; defer { busy = false }
        let bbox = (plan["bbox"]?.arrayValue ?? []).compactMap { v -> Double? in
            if case .double(let d) = v { return d }; if case .int(let i) = v { return Double(i) }; return nil }
        let body: [String: Any] = ["id": plan["id"]?.stringValue ?? "", "name": name, "bbox": bbox,
                                   "epsg": plan["epsg"]?.intValue ?? 0]
        var req = URLRequest(url: URL(string: "http://127.0.0.1:8848/api/regions/build")!)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            let j = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            if (resp as? HTTPURLResponse)?.statusCode == 200, let jid = j?["job"] as? String {
                dismiss()
                await started(jid, "Build \(name)")
            } else {
                message = (j?["detail"] as? String) ?? "The engine refused the build."
            }
        } catch {
            message = "The engine could not be reached: \(error.localizedDescription)"
        }
    }

}
