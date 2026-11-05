import AppKit
import TecopaKit

/// The app's lifecycle: start the engine at launch, stop it on quit. The work is in
/// AppModel; this answers AppKit (phase 1 spec 5.5).
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = AppModel()

    func applicationDidFinishLaunching(_ notification: Notification) {
        Task { await model.launch() }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        model.answerQuit(sender)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}
