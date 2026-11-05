import SwiftUI
import WebKit

/// The web studio inside the window (phase 2 spec decision 2; phase 3a): one web view
/// for the window's life, so switching panes never reloads the studio. Uploads go
/// through the open panel, a download lands in Downloads, and a link outside the engine
/// opens in the browser.
struct StudioView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        StudioHost(controller: model.studio)
            .toolbar {
                if model.pane == .studio { ToolbarItemGroup {
                    Button { model.reloadStudio() } label: { Label("Reload", systemImage: "arrow.clockwise") }
                        .help("Reload the studio")
                    Button { model.openStudioInBrowser() } label: { Label("Open in Browser", systemImage: "safari") }
                        .help("Open the studio in the default browser")
                } }
            }
    }
}

/// Hosts the controller's one web view: building this again re-hosts the same view.
struct StudioHost: NSViewRepresentable {
    let controller: StudioController
    func makeNSView(context: Context) -> WKWebView { controller.showing() }
    func updateNSView(_ web: WKWebView, context: Context) {}
}

@MainActor
final class StudioController: NSObject, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    static let home = URL(string: "http://127.0.0.1:8848/")!
    let web: WKWebView
    private var loadedOnce = false
    /// Scripts that wait for the page to finish loading; each runs once.
    private var pending: [String] = []

    override init() {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.preferences.isElementFullscreenEnabled = true
        web = WKWebView(frame: .zero, configuration: config)
        super.init()
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsMagnification = true
        web.isInspectable = true
        web.setValue(false, forKey: "drawsBackground")
    }

    /// The web view, loaded the first time it is shown.
    func showing() -> WKWebView {
        if !loadedOnce { loadedOnce = true; web.load(URLRequest(url: Self.home)) }
        return web
    }

    /// Reload the page as it is now: its own address, without a one-shot `?order=`.
    func reload() {
        guard loadedOnce else { return }
        if web.url == nil { web.load(URLRequest(url: Self.home)) } else { web.reload() }
    }

    /// Load `?order=<folder>` once; the studio opens the order and drops the link.
    func open(order folder: String) {
        var c = URLComponents(url: Self.home, resolvingAgainstBaseURL: false)!
        c.queryItems = [URLQueryItem(name: "order", value: folder)]
        loadedOnce = true
        web.load(URLRequest(url: c.url!))
    }

    /// Run a script once the page is ready (now, if it is).
    func run(_ script: String) {
        if !loadedOnce { _ = showing() }
        if web.isLoading { pending.append(script) } else { web.evaluateJavaScript(script) }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        let scripts = pending
        pending = []
        for s in scripts { webView.evaluateJavaScript(s) }
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
            let name = ext.isEmpty ? "\(stem) \(n)" : "\(stem) \(n).\(ext)"
            dest = dir.appendingPathComponent(name)
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
