import SwiftUI
import TecopaKit

/// The Engine pane: doctor, the log, the caches and the runs (phase 2 spec, decision 13).
struct EngineView: View {
    @Environment(AppModel.self) private var model
    @State private var tab = 0

    var body: some View {
        VStack(spacing: 0) {
            Picker("", selection: $tab) {
                Text("Health").tag(0); Text("Log").tag(1); Text("Runs").tag(2); Text("Caches").tag(3)
            }
            .pickerStyle(.segmented).labelsHidden().padding(10).frame(maxWidth: 480)
            Divider()
            switch tab {
            case 0: HealthView()
            case 1: LogView()
            case 2: RunsView()
            default: JSONPane(entry: "caches")
            }
        }
        .toolbar {
            ToolbarItem {
                Button { Task { await model.restartEngine() } } label: { Label("Restart Engine", systemImage: "arrow.triangle.2.circlepath") }
                    .help("Stop the engine this app started and start it again")
            }
        }
    }
}

struct HealthView: View {
    @Environment(AppModel.self) private var model
    @State private var rows: [JSONValue] = []
    @State private var version = ""

    var body: some View {
        List {
            Section("This app") {
                LabeledContent("Engine version", value: model.bundleVersion)
                LabeledContent("Data", value: model.dataRoot)
                LabeledContent("Log", value: model.runtime.logPath)
            }
            Section("Doctor") {
                ForEach(Array(rows.enumerated()), id: \.offset) { _, r in
                    let status = r["status"]?.stringValue ?? ""
                    HStack(alignment: .firstTextBaseline) {
                        Image(systemName: status == "ok" ? "checkmark.circle.fill" : status == "warn" ? "exclamationmark.triangle.fill" : "xmark.octagon.fill")
                            .foregroundStyle(status == "ok" ? .green : status == "warn" ? .orange : .red)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(r["name"]?.stringValue ?? "").font(.headline)
                            Text(r["detail"]?.stringValue ?? "").textSelection(.enabled)
                            if let h = r["hint"]?.stringValue { Text(h).font(.caption).foregroundStyle(.secondary) }
                        }
                    }
                }
            }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        if case .success(let d) = await model.call("doctor") { rows = d["checks"]?.arrayValue ?? [] }
    }
}

struct LogView: View {
    @Environment(AppModel.self) private var model
    @State private var lines: [String] = []
    @State private var filter = ""
    @State private var follow = true

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                TextField("Filter", text: $filter).textFieldStyle(.roundedBorder).frame(maxWidth: 260)
                    .onSubmit { Task { await load() } }
                Toggle("Follow", isOn: $follow).toggleStyle(.checkbox)
                Spacer()
                Button("Open in Console") { NSWorkspace.shared.open(URL(fileURLWithPath: model.runtime.logPath)) }
            }
            .padding(8)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(lines.enumerated()), id: \.offset) { _, l in
                        Text(l).font(.caption.monospaced())
                            .foregroundStyle(l.contains("ERROR") || l.contains("Traceback") ? .red : .primary)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(8)
            }
            .defaultScrollAnchor(.bottom)
        }
        .task {
            while !Task.isCancelled {
                await load()
                if !follow { break }
                try? await Task.sleep(for: .seconds(2))
            }
        }
    }

    private func load() async {
        var args: [String: JSONValue] = ["lines": .int(500)]
        if !filter.isEmpty { args["grep"] = .string(filter) }
        if case .success(let d) = await model.call("logs", args) {
            lines = (d["lines"]?.arrayValue ?? []).compactMap { $0.stringValue }
        }
    }
}

struct RunsView: View {
    @Environment(AppModel.self) private var model
    @State private var runs: [JSONValue] = []

    var body: some View {
        List {
            ForEach(Array(runs.enumerated()), id: \.offset) { _, r in
                HStack {
                    VStack(alignment: .leading) {
                        Text(r["command"]?.stringValue ?? r["file"]?.stringValue ?? "?").font(.headline)
                        Text([r["id"]?.stringValue, r["started"]?.stringValue].compactMap { $0 }.joined(separator: "  "))
                            .font(.caption.monospaced()).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Text(r["state"]?.stringValue ?? "")
                    if r["state"]?.stringValue == "running", let id = r["id"]?.stringValue {
                        Button("Cancel") { Task { _ = await model.call("runs_cancel", ["run": .string(id)]); await load() } }
                    }
                }
            }
        }
        .task { await load() }
        .refreshable { await load() }
    }

    private func load() async {
        if case .success(let d) = await model.call("runs") { runs = d["runs"]?.arrayValue ?? [] }
    }
}

/// A read-only catalog entry, shown as its JSON.
struct JSONPane: View {
    @Environment(AppModel.self) private var model
    let entry: String
    @State private var text = ""

    var body: some View {
        ScrollView {
            Text(text).font(.callout.monospaced()).textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading).padding(12)
        }
        .task {
            switch await model.call(entry) {
            case .success(let d): text = d.text(pretty: true)
            case .failure(let f): text = f.message
            }
        }
    }
}
