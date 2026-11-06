import AppKit
import SwiftUI
import XCTest

/// Offscreen pictures of each pane at the window's minimum and default sizes. A look
/// at the layout, not a pixel test: it writes PNGs and asserts only that each one has
/// content. The sidebar draws on a material that cacheDisplay cannot capture, so it
/// shows blank here. Skipped unless TECOPA_SNAPSHOT_DIR is set.
@MainActor
final class PaneSnapshots: XCTestCase {
    private var folder: URL!

    override func setUp() async throws {
        guard let dir = ProcessInfo.processInfo.environment["TECOPA_SNAPSHOT_DIR"] else {
            throw XCTSkip("Set TECOPA_SNAPSHOT_DIR to write the pane pictures.")
        }
        folder = URL(fileURLWithPath: dir)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    }

    private func shoot<V: View>(_ view: V, _ name: String, _ size: CGSize, wait: TimeInterval = 3) throws {
        // cacheDisplay draws views, not the window's background, so the test paints it.
        let host = NSHostingView(rootView: view.frame(width: size.width, height: size.height)
            .background(Color(nsColor: .windowBackgroundColor)))
        let window = NSWindow(contentRect: NSRect(origin: CGPoint(x: -30000, y: -30000), size: size),
                              styleMask: [.titled, .fullSizeContentView], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentView = host
        window.layoutIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(wait))   // let .task loads land
        host.layoutSubtreeIfNeeded()
        guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return XCTFail(name) }
        host.cacheDisplay(in: host.bounds, to: rep)
        let png = try XCTUnwrap(rep.representation(using: .png, properties: [:]))
        try png.write(to: folder.appendingPathComponent(name + ".png"))
        XCTAssertGreaterThan(png.count, 5_000, name)
        window.close()
    }

    func testEveryPaneAtTheMinimumAndDefaultSizes() throws {
        for (label, size) in [("min", CGSize(width: 1000, height: 680)), ("default", CGSize(width: 1440, height: 900))] {
            for pane in [Pane.orders, .plates, .engine] {
                let model = AppModel()
                model.engine = .ready(adopted: true)
                model.pane = pane
                try shoot(MainView().environment(model), "\(pane.rawValue)-\(label)", size)
            }
        }
        let starting = AppModel()
        try shoot(MainView().environment(starting), "starting-min", CGSize(width: 1000, height: 680), wait: 0.5)
        let failed = AppModel()
        failed.engine = .failed(title: "Port 8848 is in use", message: AlertText.portInUse)
        failed.pane = .orders
        try shoot(MainView().environment(failed), "failed-min", CGSize(width: 1000, height: 680), wait: 2)
        try shoot(SettingsView().environment(AppModel()), "settings", CGSize(width: 620, height: 520), wait: 1)
    }
}
