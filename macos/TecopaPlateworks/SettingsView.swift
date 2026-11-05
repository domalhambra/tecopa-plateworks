import AppKit
import SwiftUI
import TecopaKit

/// Settings (⌘,): settings.json, the desk token in the Keychain, the paper profiles,
/// and the tecopa command (phase 2 spec, decisions 6, 9 and 14).
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var values: [String: String] = [:]
    @State private var token = ""
    @State private var tokenSaved = false
    @State private var dirty = false
    @State private var note = ""
    @State private var toolNote = ""
    /// settings.json could not be read: shown, and kept aside before any save.
    @State private var loadError = ""

    static let fontRoles: [(key: String, label: String)] = [
        ("TECOPA_FONT_TITLE", "Title (cartouche)"), ("TECOPA_FONT_POINT", "Points"),
        ("TECOPA_FONT_AREA", "Areas"), ("TECOPA_FONT_WATER", "Water"), ("TECOPA_FONT", "Body and fallback"),
    ]

    var body: some View {
        TabView {
            Form {
                if !loadError.isEmpty {
                    Section { Label(loadError, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange) }
                }
                Section("Folders") {
                    folderRow("Orders folder", key: "TECOPA_ORDERS_DIR", fallback: model.runtime.home + "/Tecopa Orders")
                    folderRow("Dropbox intake", key: "TECOPA_INTAKE_DIR",
                              fallback: model.runtime.home + "/Dropbox/Apps/Plateworks Lab/Tecopa")
                }
                Section {
                    ForEach(Self.fontRoles, id: \.key) { role in fontRow(role.label, key: role.key) }
                    Toggle("Areas use mixed case (a small-caps face)", isOn: Binding(
                        get: { values["TECOPA_FONT_AREA_CASE"] == "mixed" },
                        set: { values["TECOPA_FONT_AREA_CASE"] = $0 ? "mixed" : nil; dirty = true }))
                } header: { Text("Type") } footer: {
                    Text("Licensed faces stay on this Mac. Nothing copies them into the app or the repo.")
                }
                HStack {
                    if !note.isEmpty { Text(note).font(.caption).foregroundStyle(.secondary) }
                    Spacer()
                    Button("Save and Restart Engine") { Task { await save() } }.disabled(!dirty || model.restarting)
                }
            }
            .formStyle(.grouped)
            .tabItem { Label("General", systemImage: "gearshape") }

            Form {
                Section {
                    SecureField("Desk API token", text: $token)
                    HStack {
                        Button(tokenSaved ? "Saved" : "Save to Keychain") {
                            tokenSaved = Keychain.write(token, service: DeskClient.service, account: DeskClient.account)
                        }
                        .disabled(token.isEmpty)
                        Button("Remove") {
                            Keychain.write("", service: DeskClient.service, account: DeskClient.account)
                            token = ""; tokenSaved = false
                        }
                    }
                } header: { Text("Order desk") } footer: {
                    Text("Read only: the Orders pane reads an order's paid size from lab.plateworks.org/desk/data. The token stays in your login Keychain (\(DeskClient.service)).")
                }
            }
            .formStyle(.grouped)
            .tabItem { Label("Order Desk", systemImage: "key") }

            Form {
                Section("Red River paper profiles") {
                    let profiles = iccProfiles
                    if profiles.isEmpty {
                        Label("No Red River profiles in /Library/ColorSync/Profiles. Soft proofs are skipped until they are installed.",
                              systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                    } else {
                        Label("\(profiles.count) Red River profiles installed", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                    }
                }
                Section {
                    Button("Install the tecopa Command") { installTool() }
                    Text("Links ~/.local/bin/tecopa to the copy inside this app, so Claude's tecopa tools use this app's engine.")
                        .font(.caption).foregroundStyle(.secondary)
                    if !toolNote.isEmpty { Text(toolNote).font(.callout).textSelection(.enabled) }
                } header: { Text("Command line") }
            }
            .formStyle(.grouped)
            .tabItem { Label("Tools", systemImage: "wrench.and.screwdriver") }
        }
        .frame(width: 620, height: 520)
        .task { load() }
    }

    private var iccProfiles: [String] {
        let dirs = ["/Library/ColorSync/Profiles", model.runtime.home + "/Library/ColorSync/Profiles"]
        return Set(dirs.flatMap { (try? FileManager.default.contentsOfDirectory(atPath: $0)) ?? [] })
            .filter { $0.hasPrefix("RR ") }.sorted()
    }

    private func folderRow(_ label: String, key: String, fallback: String) -> some View {
        LabeledContent(label) {
            HStack {
                Text(values[key] ?? fallback).lineLimit(1).truncationMode(.middle)
                    .foregroundStyle(values[key] == nil ? .secondary : .primary)
                Button("Choose…") {
                    let p = NSOpenPanel(); p.canChooseDirectories = true; p.canChooseFiles = false
                    if p.runModal() == .OK, let u = p.url { values[key] = u.path; dirty = true }
                }
                if values[key] != nil { Button("Default") { values[key] = nil; dirty = true } }
            }
        }
    }

    private func fontRow(_ label: String, key: String) -> some View {
        LabeledContent(label) {
            HStack {
                Text(values[key].map { URL(fileURLWithPath: $0).lastPathComponent } ?? "The default chain")
                    .lineLimit(1).foregroundStyle(values[key] == nil ? .secondary : .primary)
                Button("Choose…") {
                    let p = NSOpenPanel()
                    p.allowedContentTypes = [.font]
                    p.directoryURL = URL(fileURLWithPath: model.runtime.home + "/Library/Fonts")
                    if p.runModal() == .OK, let u = p.url { values[key] = u.path; dirty = true }
                }
                if values[key] != nil { Button("Clear") { values[key] = nil; dirty = true } }
            }
        }
    }

    private func load() {
        do {
            values = try EngineEnvironment.settings(
                from: FileManager.default.contents(atPath: model.settingsPath), path: model.settingsPath)
            loadError = ""
        } catch {
            values = [:]
            loadError = "\(model.settingsPath) is not valid JSON. Saving keeps a copy of it as settings.json.bad."
        }
        tokenSaved = Keychain.read(service: DeskClient.service, account: DeskClient.account) != nil
    }

    private func save() async {
        let clean = values.filter { EngineEnvironment.isSettingsKey($0.key) && !$0.value.isEmpty }
        do {
            try FileManager.default.createDirectory(atPath: model.dataRoot, withIntermediateDirectories: true)
            if !loadError.isEmpty {
                let bad = model.settingsPath + ".bad"
                try? FileManager.default.removeItem(atPath: bad)
                try FileManager.default.copyItem(atPath: model.settingsPath, toPath: bad)
                loadError = ""
            }
            let data = try JSONSerialization.data(withJSONObject: clean, options: [.prettyPrinted, .sortedKeys])
            try data.write(to: URL(fileURLWithPath: model.settingsPath), options: .atomic)
            dirty = false
            note = "Saved. Restarting the engine…"
            switch await model.restartEngine() {
            case .restarted: note = "Saved. The engine restarted with the new settings."
            case .cancelled: note = "Saved. The engine was not restarted; the settings take effect at its next start."
            case .notOurs: note = "Saved. " + AlertText.restartNotOurs
            case .busy: note = "Saved. A restart is already under way; the settings take effect at the engine's next start."
            }
        } catch {
            note = "Could not save: \(error.localizedDescription)"
        }
    }

    private func installTool() {
        let helper = Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/tecopa").path
        let bin = model.runtime.home + "/.local/bin"
        let link = bin + "/tecopa"
        let fm = FileManager.default
        guard fm.isExecutableFile(atPath: helper) else { toolNote = "This build has no tecopa command inside it."; return }
        if (try? fm.destinationOfSymbolicLink(atPath: link)) == helper {
            toolNote = "~/.local/bin/tecopa already runs this app's copy."; return
        }
        do {
            try fm.createDirectory(atPath: bin, withIntermediateDirectories: true)
            var kept = ""
            if (try? fm.destinationOfSymbolicLink(atPath: link)) != nil || fm.fileExists(atPath: link) {
                // Never remove an earlier backup: the first one is the original command.
                var old = link + ".before-app"
                var n = 2
                while fm.fileExists(atPath: old) || (try? fm.destinationOfSymbolicLink(atPath: old)) != nil {
                    old = link + ".before-app-\(n)"; n += 1
                }
                try fm.moveItem(atPath: link, toPath: old)
                kept = " The old one is \(old.replacingOccurrences(of: model.runtime.home, with: "~"))."
            }
            try fm.createSymbolicLink(atPath: link, withDestinationPath: helper)
            toolNote = "~/.local/bin/tecopa now runs this app's copy." + kept
        } catch {
            toolNote = "Could not install: \(error.localizedDescription)"
        }
    }
}
