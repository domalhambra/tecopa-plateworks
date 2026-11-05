import AppKit
import Observation
import SwiftUI
import TecopaKit

enum Pane: String, CaseIterable, Identifiable {
    case studio, orders, plates, engine
    var id: String { rawValue }
    var title: String {
        switch self {
        case .studio: return "Studio"
        case .orders: return "Orders"
        case .plates: return "Plates"
        case .engine: return "Engine"
        }
    }
    var symbol: String {
        switch self {
        case .studio: return "map"
        case .orders: return "shippingbox"
        case .plates: return "mountain.2"
        case .engine: return "gearshape.2"
        }
    }
    var shortcut: KeyEquivalent {
        switch self {
        case .studio: return "1"
        case .orders: return "2"
        case .plates: return "3"
        case .engine: return "4"
        }
    }
}

enum EngineState: Equatable {
    case starting(String)
    case ready(adopted: Bool)
    case failed(title: String, message: String)
}

/// What the window shows and the one owner of the engine (phase 1 spec 5.5, 5.6;
/// phase 2 spec). Every tool action goes through TecopaKit's catalog (phase 2,
/// decision 3); this holds no order, plate or render rule.
@MainActor
@Observable
final class AppModel {
    let layout = EngineLayout.bundle(Bundle.main.bundleURL)
    /// Every catalog entry runs with this bundle's interpreters and data, never a repo.
    let runtime = Runtime(layout: .bundle(Bundle.main.bundleURL))
    @ObservationIgnored private let spawner = ProcessEngineSpawner()
    @ObservationIgnored private var quitGate = QuitGate()
    @ObservationIgnored private var quitting = false

    var engine: EngineState = .starting("Starting the engine…")
    var pane: Pane = .studio
    /// The studio's address; Orders sets `?order=` to land on an order (decision 10).
    var studioURL = URL(string: "http://127.0.0.1:8848/")!
    var studioReloads = 0
    /// A command for the studio page, run once by StudioWebView (phase 3: the native
    /// File menu drives the studio's own file inputs, so the engine sees the same upload).
    var studioCommand: (id: Int, script: String)?
    private(set) var ownedPid: Int32?

    var dataRoot: String { layout.dataRoot(home: runtime.home) }
    var settingsPath: String { dataRoot + "/settings.json" }
    var bundleVersion: String { layout.infoValue("TecopaEngineVersion", runtime) ?? "unknown" }

    // MARK: launch

    func launch() async {
        engine = .starting("Reading the settings…")
        let settings: [String: String]
        do {
            settings = try EngineEnvironment.settings(
                from: FileManager.default.contents(atPath: settingsPath), path: settingsPath)
        } catch {
            engine = .failed(title: "Tecopa Plateworks couldn’t read its settings",
                             message: AlertText.badSettings(path: settingsPath))
            return
        }
        engine = .starting("Seeding the plates…")
        do {
            let report = try EngineHost.prepareData(layout: layout, home: runtime.home,
                                                    bundleVersion: bundleVersion)
            for id in report.regionChangedUnderDEM {
                log("event=seed.region_changed id=\(id): the plate's region.json changed under its cached DEM; it may ORPHAN until the DEM is refilled")
            }
            for (id, files) in report.leftBehind.sorted(by: { $0.key < $1.key }) {
                log("event=seed.left_behind id=\(id) files=\(files.joined(separator: ","))")
            }
        } catch {
            engine = .failed(title: "Tecopa Plateworks couldn’t seed its plates",
                             message: AlertText.couldNotStart("\(error)", log: runtime.logPath))
            return
        }

        engine = .starting("Looking for an engine on port 8848…")
        switch startAction(await EngineHost.classify(runtime)) {
        case .adopt:
            let found = await adoptedVersion()
            if let note = adoptNote(bundleVersion: bundleVersion, engineVersion: found) { log(note) }
            log("event=engine.adopted version=\(found ?? "unknown")")
            engine = .ready(adopted: true)
        case .refuseForeign:
            engine = .failed(title: "Port 8848 is in use", message: AlertText.portInUse)
        case .refuseNotAnswering:
            engine = .failed(title: "Port 8848 is in use", message: AlertText.notAnswering)
        case .spawn:
            await spawn(settings: settings)
        }
    }

    private func spawn(settings: [String: String]) async {
        engine = .starting("Starting the engine…")
        let env = EngineEnvironment.build(layout: layout, home: runtime.home,
                                          base: ProcessInfo.processInfo.environment,
                                          settings: settings, engineVersion: bundleVersion)
        log("event=engine.start python=\(layout.enginePython) cwd=\(dataRoot) version=\(bundleVersion)")
        do {
            _ = try await EngineHost.start(
                layout: layout, runtime: runtime, spawner: spawner, environment: env,
                onSpawn: { pid in Task { @MainActor in self.ownedPid = pid } },
                onExit: { status in Task { @MainActor in self.engineExited(status) } })
            engine = .ready(adopted: false)
        } catch let f as TecopaFailure {
            engine = .failed(title: "Tecopa Plateworks couldn’t start its engine",
                             message: AlertText.couldNotStart(f.message, log: runtime.logPath))
        } catch {
            engine = .failed(title: "Tecopa Plateworks couldn’t start its engine",
                             message: AlertText.couldNotStart("\(error)", log: runtime.logPath))
        }
    }

    /// Stop the engine this app owns and start it again: a setting the engine reads at
    /// start changed (phase 2 spec, decision 14).
    func restartEngine() async {
        if let pid = ownedPid {
            quitting = true
            try? await EngineHost.stop(pid: pid, runtime: runtime, spawner: spawner)
            ownedPid = nil
            quitting = false
        }
        await launch()
        studioReloads += 1
    }

    private func adoptedVersion() async -> String? {
        guard case .reply(let r) = await runtime.client.probe("/api/debug/engine", timeout: 3) else { return nil }
        return r.json["engine_version"]?.stringValue
    }

    private func engineExited(_ status: Int32) {
        guard ownedPid != nil, !quitting else { return }
        ownedPid = nil
        log("event=engine.exited status=\(status)")
        engine = .failed(title: "Tecopa Plateworks’ engine stopped",
                         message: AlertText.engineStopped(status: status, log: runtime.logPath))
    }

    // MARK: the studio

    func openStudio(order folderName: String? = nil) {
        var c = URLComponents(string: "http://127.0.0.1:8848/")!
        if let folderName { c.queryItems = [URLQueryItem(name: "order", value: folderName)] }
        studioURL = c.url!
        studioReloads += 1
        pane = .studio
    }

    /// File > Open Tracks… and Open Poster…: the studio's own hidden inputs, so the
    /// upload is the web studio's, byte for byte.
    func studioOpen(_ input: String) {
        pane = .studio
        let n = (studioCommand?.id ?? 0) + 1
        studioCommand = (n, "document.getElementById('\(input)').click()")
    }

    func openStudioInBrowser() {
        NSWorkspace.shared.open(URL(string: "http://127.0.0.1:8848/")!)
    }

    // MARK: the catalog

    /// One TecopaKit catalog entry. The data on success, or the engine's own words.
    func call(_ name: String, _ arguments: [String: JSONValue] = [:]) async -> Result<JSONValue, TecopaFailure> {
        let (envelope, failure) = await Catalog.call(name, runtime, arguments)
        if let failure { return .failure(failure) }
        return .success(envelope["data"] ?? .null)
    }

    // MARK: quit

    func answerQuit(_ sender: NSApplication) -> NSApplication.TerminateReply {
        let marker = dataRoot + "/.quit-forced"
        let modified = (try? FileManager.default.attributesOfItem(atPath: marker))?[.modificationDate] as? Date
        let forced = quitMarkerIsFresh(modified: modified, now: Date())
        switch quitGate.answer(ownsEngine: ownedPid != nil, forced: forced) {
        case .now:
            return .terminateNow
        case .alreadyWaiting:
            return .terminateLater
        case .stopWithoutConfirm:
            try? FileManager.default.removeItem(atPath: marker)
            Task { await self.stopEngineAndReply(sender) }
            return .terminateLater
        case .readJobsFirst:
            Task {
                switch afterJobs(await EngineHost.activeJobs(self.runtime)) {
                case .stopEngine:
                    await self.stopEngineAndReply(sender)
                case .confirm(let jobs):
                    if self.confirmQuit(jobs: jobs) {
                        await self.stopEngineAndReply(sender)
                    } else {
                        self.quitGate.cancel()
                        sender.reply(toApplicationShouldTerminate: false)
                    }
                }
            }
            return .terminateLater
        }
    }

    private func stopEngineAndReply(_ sender: NSApplication) async {
        quitting = true
        if let pid = ownedPid {
            try? await EngineHost.stop(pid: pid, runtime: runtime, spawner: spawner)
            ownedPid = nil
        }
        log("event=engine.stopped")
        sender.reply(toApplicationShouldTerminate: true)
    }

    private func confirmQuit(jobs: Int?) -> Bool {
        let a = NSAlert()
        a.messageText = "Quit Tecopa Plateworks?"
        a.informativeText = AlertText.quitConfirm(jobs: jobs)
        a.addButton(withTitle: "Quit")
        a.addButton(withTitle: "Cancel")
        return a.runModal() == .alertFirstButtonReturn
    }

    // MARK: the log

    /// One line in the engine's log, the file `tecopa logs` and the Engine pane read.
    func log(_ line: String) {
        let stamp = ISO8601DateFormatter().string(from: Date())
        let data = Data("\(stamp) app \(line)\n".utf8)
        let path = runtime.logPath
        if !FileManager.default.fileExists(atPath: path) {
            FileManager.default.createFile(atPath: path, contents: nil)
        }
        if let h = FileHandle(forWritingAtPath: path) {
            h.seekToEndOfFile()
            h.write(data)
            try? h.close()
        }
    }
}
