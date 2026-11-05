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

    static let fontRoles: [(key: String, label: String)] = [
        ("TECOPA_FONT_TITLE", "Title (cartouche)"), ("TECOPA_FONT_POINT", "Points"),
        ("TECOPA_FONT_AREA", "Areas"), ("TECOPA_FONT_WATER", "Water"), ("TECOPA_FONT", "Body and fallback"),
    ]

    var body: some View {
        TabView {
            Form {
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
                    Button("Save and Restart Engine") { Task { await save() } }.disabled(!dirty)
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
        values = (try? EngineEnvironment.settings(
            from: FileManager.default.contents(atPath: model.settingsPath), path: model.settingsPath)) ?? [:]
        tokenSaved = Keychain.read(service: DeskClient.service, account: DeskClient.account) != nil
    }

    private func save() async {
        let clean = values.filter { EngineEnvironment.isSettingsKey($0.key) && !$0.value.isEmpty }
        do {
            try FileManager.default.createDirectory(atPath: model.dataRoot, withIntermediateDirectories: true)
            let data = try JSONSerialization.data(withJSONObject: clean, options: [.prettyPrinted, .sortedKeys])
            try data.write(to: URL(fileURLWithPath: model.settingsPath), options: .atomic)
            dirty = false
            note = "Saved. Restarting the engine…"
            await model.restartEngine()
            note = "Saved."
        } catch {
            note = "Could not save: \(error.localizedDescription)"
        }
    }

    private func installTool() {
        let helper = Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/tecopa").path
        let bin = model.runtime.home + "/.local/bin"
        let link = bin + "/tecopa"
        do {
            guard FileManager.default.isExecutableFile(atPath: helper) else {
                note = "This build has no tecopa command inside it."; return
            }
            try FileManager.default.createDirectory(atPath: bin, withIntermediateDirectories: true)
            if (try? FileManager.default.destinationOfSymbolicLink(atPath: link)) != nil
                || FileManager.default.fileExists(atPath: link) {
                let old = link + ".before-app"
                try? FileManager.default.removeItem(atPath: old)
                try FileManager.default.moveItem(atPath: link, toPath: old)
            }
            try FileManager.default.createSymbolicLink(atPath: link, withDestinationPath: helper)
            note = "~/.local/bin/tecopa now runs this app's copy. The old one is ~/.local/bin/tecopa.before-app."
        } catch {
            note = "Could not install: \(error.localizedDescription)"
        }
    }
}
