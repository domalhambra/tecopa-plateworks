import SwiftUI
import WebKit
import UniformTypeIdentifiers

/// The web studio inside the window (phase 2 spec, decision 2): uploads through the
/// open panel, downloads saved to Downloads, links outside the engine to the browser.
struct StudioView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        StudioWebView(url: model.studioURL, reloads: model.studioReloads, command: model.studioCommand)
            .toolbar {
                ToolbarItemGroup {
                    Button { model.studioReloads += 1 } label: { Label("Reload", systemImage: "arrow.clockwise") }
                        .help("Reload the studio")
                    Button { model.openStudioInBrowser() } label: { Label("Open in Browser", systemImage: "safari") }
                        .help("Open the studio in the default browser")
                }
            }
    }
}

struct StudioWebView: NSViewRepresentable {
    let url: URL
    let reloads: Int
    let command: (id: Int, script: String)?

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.preferences.isElementFullscreenEnabled = true
        let web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = context.coordinator
        web.uiDelegate = context.coordinator
        web.allowsMagnification = true
        web.isInspectable = true
        web.setValue(false, forKey: "drawsBackground")
        context.coordinator.loaded = (url, reloads)
        if let command { context.coordinator.lastCommand = command.id; context.coordinator.pending = command.script }
        web.load(URLRequest(url: url))
        return web
    }

    func updateNSView(_ web: WKWebView, context: Context) {
        if let command, command.id != context.coordinator.lastCommand {
            context.coordinator.lastCommand = command.id
            if web.isLoading { context.coordinator.pending = command.script }
            else { web.evaluateJavaScript(command.script) }
        }
        guard context.coordinator.loaded.url != url || context.coordinator.loaded.reloads != reloads else { return }
        context.coordinator.loaded = (url, reloads)
        web.load(URLRequest(url: url))
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
        var loaded: (url: URL, reloads: Int) = (URL(string: "about:blank")!, -1)
        var lastCommand = 0
        /// A command that arrived while the page loaded; it runs when the load finishes.
        var pending: String?

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            if let p = pending { pending = nil; webView.evaluateJavaScript(p) }
        }

        // Links that leave the engine open in the browser.
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     preferences: WKWebpagePreferences) async -> (WKNavigationActionPolicy, WKWebpagePreferences) {
            if let u = action.request.url, u.host != "127.0.0.1", u.scheme == "http" || u.scheme == "https" {
                NSWorkspace.shared.open(u)
                return (.cancel, preferences)
            }
            return (action.shouldPerformDownload ? .download : .allow, preferences)
        }

        func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse) async -> WKNavigationResponsePolicy {
            if let http = response.response as? HTTPURLResponse,
               let disposition = http.value(forHTTPHeaderField: "Content-Disposition"),
               disposition.lowercased().contains("attachment") {
                return .download
            }
            return response.canShowMIMEType ? .allow : .download
        }

        func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
            download.delegate = self
        }

        func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
            download.delegate = self
        }

        // A file the studio offers lands in Downloads under its own name, never over a file.
        func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                      suggestedFilename: String) async -> URL? {
            let dir = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
            var dest = dir.appendingPathComponent(suggestedFilename)
            let stem = dest.deletingPathExtension().lastPathComponent, ext = dest.pathExtension
            var n = 2
            while FileManager.default.fileExists(atPath: dest.path) {
                dest = dir.appendingPathComponent("\(stem) \(n)").appendingPathExtension(ext)
                n += 1
            }
            return dest
        }

        func downloadDidFinish(_ download: WKDownload) {
            if let url = download.progress.fileURL { NSWorkspace.shared.activateFileViewerSelecting([url]) }
        }

        // <input type=file>: the studio's track, poster and photo pickers.
        func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                     initiatedByFrame frame: WKFrameInfo) async -> [URL]? {
            let panel = NSOpenPanel()
            panel.allowsMultipleSelection = parameters.allowsMultipleSelection
            panel.canChooseDirectories = parameters.allowsDirectories
            panel.canChooseFiles = true
            return panel.runModal() == .OK ? panel.urls : nil
        }

        func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo) async {
            let a = NSAlert(); a.messageText = message; a.runModal()
        }

        func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo) async -> Bool {
            let a = NSAlert(); a.messageText = message
            a.addButton(withTitle: "OK"); a.addButton(withTitle: "Cancel")
            return a.runModal() == .alertFirstButtonReturn
        }

        // A window the studio opens (a preview of an export) opens in the browser.
        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let u = action.request.url { NSWorkspace.shared.open(u) }
            return nil
        }
    }
}
