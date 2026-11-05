import SwiftUI
import TecopaKit

/// Tecopa Plateworks: one window with the studio, the orders, the plates and the
/// engine, and a Settings window (native Mac app phase 2 spec, decisions 1 and 2).
@main
struct TecopaPlateworksApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    var body: some Scene {
        Window("Tecopa Plateworks", id: "main") {
            MainView()
                .environment(delegate.model)
                .frame(minWidth: 1000, minHeight: 680)
        }
        .defaultSize(width: 1440, height: 900)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Open Tracks…") { delegate.model.studioOpen("fileInput") }
                    .keyboardShortcut("o", modifiers: .command)
                Button("Open Poster…") { delegate.model.studioOpen("posterInput") }
                    .keyboardShortcut("o", modifiers: [.command, .shift])
                Divider()
                Button("Reload Studio") { delegate.model.pane = .studio; delegate.model.studioReloads += 1 }
                    .keyboardShortcut("r", modifiers: .command)
            }
            CommandMenu("Go") {
                ForEach(Pane.allCases) { pane in
                    Button(pane.title) { delegate.model.pane = pane }
                        .keyboardShortcut(pane.shortcut, modifiers: .command)
                }
                Divider()
                Button("Open the Studio in the Browser") { delegate.model.openStudioInBrowser() }
            }
        }
        Settings {
            SettingsView()
                .environment(delegate.model)
        }
    }
}
