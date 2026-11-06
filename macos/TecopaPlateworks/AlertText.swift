import Foundation

/// Every sentence the app shows in an alert. The spec fixes two of them
/// (phase 1 spec 5.5); the others keep the launcher's wording.
enum AlertText {
    static let portInUse = "Port 8848 is in use by another program."
    static let notAnswering = "An engine on port 8848 is not answering."

    static func quitConfirm(jobs: Int?) -> String {
        switch jobs {
        case .some(1): return "1 job is running. Quitting ends it."
        case .some(let n): return "\(n) jobs are running. Quitting ends them."
        case .none: return "The engine is busy and did not say what is running. Quitting may end a render."
        }
    }

    static func restartConfirm(jobs: Int?) -> String {
        switch jobs {
        case .some(1): return "1 job is running. Restarting the engine ends it."
        case .some(let n): return "\(n) jobs are running. Restarting the engine ends them."
        case .none: return "The engine is busy and did not say what is running. Restarting may end a render."
        }
    }

    static let restartNotOurs = "The engine on port 8848 was not started by this app, so the app did not restart it. Stop it (tecopa engine stop) and open the app again for this setting to take effect."

    static func engineStopped(status: Int32, log: String) -> String {
        "The rendering engine exited unexpectedly (status \(status)).\n\nSee the log:\n\(log)"
    }

    static func couldNotStart(_ reason: String, log: String) -> String {
        "\(reason)\n\nSee the log:\n\(log)"
    }

    static func badSettings(path: String) -> String {
        "Tecopa Plateworks could not read its settings: \(path) is not valid JSON."
    }
}
