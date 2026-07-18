import AppKit
import Foundation

// ---- Constants ----
let kPort = 8848
let kBaseURL = "http://127.0.0.1:8848/"
let kReadyURL = "http://127.0.0.1:8848/readyz"
let kLogPath = NSHomeDirectory() + "/Library/Logs/TrailPrint.log"

// One append-mode log fd, opened once and shared by the launcher AND the child engine.
// O_APPEND makes every write land atomically at EOF, so the launcher's own log lines and
// uvicorn's stdout/stderr can never overwrite each other — they write through one open
// file description (Foundation dups this fd into the child). Without O_APPEND the two
// would have independent offsets and clobber each other's tail bytes.
let kLogFD: Int32 = {
    let dir = NSHomeDirectory() + "/Library/Logs"
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    return open(kLogPath, O_WRONLY | O_APPEND | O_CREAT, 0o644)
}()
let logHandle = FileHandle(
    fileDescriptor: kLogFD >= 0 ? kLogFD : FileHandle.standardError.fileDescriptor,
    closeOnDealloc: false)

// ---- Small helpers ----

func onMain(_ block: @escaping () -> Void) { DispatchQueue.main.async(execute: block) }

func logLine(_ msg: String) {
    guard kLogFD >= 0 else { return }
    logHandle.write("[\(Date())] \(msg)\n".data(using: .utf8)!)
}

func openBrowser() { NSWorkspace.shared.open(URL(string: kBaseURL)!) }

func showAlert(_ title: String, _ text: String) {
    let a = NSAlert()
    a.messageText = title
    a.informativeText = text
    a.alertStyle = .critical
    a.addButton(withTitle: "OK")
    NSApp.activate(ignoringOtherApps: true)
    a.runModal()
}

/// Synchronous HTTP GET. Returns (data, hadResponse). `hadResponse` is true for ANY
/// HTTP reply (200 or 503); false only when the connection is refused/timed out.
/// MUST be called off the main thread.
func httpGet(_ urlString: String, timeout: TimeInterval) -> (Data?, Bool) {
    var data: Data?
    var hadResponse = false
    let sem = DispatchSemaphore(value: 0)
    let cfg = URLSessionConfiguration.ephemeral
    cfg.timeoutIntervalForRequest = timeout
    cfg.timeoutIntervalForResource = timeout
    let session = URLSession(configuration: cfg)
    let task = session.dataTask(with: URL(string: urlString)!) { d, r, _ in
        if r != nil { hadResponse = true; data = d }
        sem.signal()
    }
    task.resume()
    _ = sem.wait(timeout: .now() + timeout + 1)
    session.finishTasksAndInvalidate()
    return (data, hadResponse)
}

enum ServingState { case trailprint, foreign, none }

/// Is something already serving on the port, and is it TrailPrint?
func probeExisting(timeout: TimeInterval) -> ServingState {
    let (data, hadResponse) = httpGet(kReadyURL, timeout: timeout)
    if !hadResponse { return .none }
    if let d = data,
       let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
       obj["ready"] != nil, obj["regions"] != nil {
        return .trailprint
    }
    return .foreign
}

// ---- App delegate ----

final class AppDelegate: NSObject, NSApplicationDelegate {
    var engine: Process?
    var ownsEngine = false
    var isQuitting = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in self?.boot() }
    }

    func die(_ title: String, _ text: String) {
        onMain { showAlert(title, text); NSApp.terminate(nil) }
    }

    func boot() {
        // 1. Repo path baked at build time
        guard let repo = Bundle.main.object(forInfoDictionaryKey: "TrailPrintRepoPath") as? String,
              !repo.isEmpty else {
            die("TrailPrint can’t find its files",
                "No repository path is baked into this app. Rebuild it with:\n\nscripts/macos/build_app.sh --install")
            return
        }
        let py = repo + "/.venv/bin/python"
        let fm = FileManager.default

        // 2. Preflight
        if !fm.fileExists(atPath: repo) {
            die("TrailPrint can’t find its files",
                "The project folder isn’t where it was when this app was built:\n\n\(repo)\n\nRebuild with scripts/macos/build_app.sh --install after moving it back or rebuilding in place.")
            return
        }
        if !fm.fileExists(atPath: py) {
            die("TrailPrint isn’t set up yet",
                "No Python environment was found at:\n\n\(py)\n\nCreate it first:\n  python3 -m venv .venv && source .venv/bin/activate\n  pip install -r requirements-lock.txt")
            return
        }

        // 3. Already serving?
        switch probeExisting(timeout: 0.7) {
        case .trailprint:
            logLine("adopting engine already serving on \(kPort)")
            onMain { openBrowser() }
            return
        case .foreign:
            die("Port \(kPort) is in use",
                "Another program is already using port \(kPort). Quit it, then relaunch TrailPrint.")
            return
        case .none:
            break
        }

        // 4. Spawn the engine
        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "\(kPort)"]
        p.currentDirectoryURL = URL(fileURLWithPath: repo)
        if kLogFD >= 0 {
            p.standardOutput = logHandle
            p.standardError = logHandle
        }
        p.terminationHandler = { [weak self] proc in
            guard let self = self, !self.isQuitting else { return }
            self.die("TrailPrint’s engine stopped",
                     "The rendering engine exited unexpectedly (status \(proc.terminationStatus)).\n\nSee the log:\n\(kLogPath)")
        }
        logLine("starting engine: \(py) -m uvicorn app.main:app --port \(kPort) (cwd=\(repo))")
        do {
            try p.run()
        } catch {
            die("TrailPrint couldn’t start its engine",
                "\(error.localizedDescription)\n\nSee the log:\n\(kLogPath)")
            return
        }
        engine = p
        ownsEngine = true

        // 5. Poll readiness up to 60s (any HTTP response counts as up)
        let deadline = Date().addingTimeInterval(60)
        while Date() < deadline {
            if isQuitting { return }
            if !p.isRunning { return } // terminationHandler shows the alert
            let (_, hadResponse) = httpGet(kReadyURL, timeout: 1.0)
            if hadResponse {
                logLine("engine ready")
                onMain { openBrowser() }
                return
            }
            Thread.sleep(forTimeInterval: 0.5)
        }
        die("TrailPrint took too long to start",
            "The engine didn’t become ready within 60 seconds.\n\nSee the log:\n\(kLogPath)")
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openBrowser()
        return true
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        isQuitting = true
        if ownsEngine, let p = engine, p.isRunning {
            logLine("quitting: SIGTERM to engine")
            p.terminate() // SIGTERM
            let deadline = Date().addingTimeInterval(5)
            while p.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.1) }
            if p.isRunning {
                logLine("engine still alive after 5s; SIGKILL")
                kill(p.processIdentifier, SIGKILL)
            }
        }
        return .terminateNow
    }
}

// ---- Bootstrap ----

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)

// Minimal main menu so Cmd-Q and About work.
let mainMenu = NSMenu()
let appItem = NSMenuItem()
mainMenu.addItem(appItem)
let appMenu = NSMenu()
appItem.submenu = appMenu
appMenu.addItem(withTitle: "About TrailPrint",
                action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
appMenu.addItem(NSMenuItem.separator())
appMenu.addItem(withTitle: "Quit TrailPrint",
                action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
app.mainMenu = mainMenu

app.activate(ignoringOtherApps: true)
app.run()
