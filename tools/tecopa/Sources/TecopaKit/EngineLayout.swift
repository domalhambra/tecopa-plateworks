import Foundation

/// Where the engine's code, its two interpreters, its plates and its data live.
/// `.bundle` is the Mac app (spec 4.1 and 4.2); `.repo` is a checkout with its two
/// venvs. The two interpreters are never one file (invariant 13).
public enum EngineLayout: Equatable, Sendable {
    case bundle(URL)
    case repo(String)

    private var resources: String? {
        guard case .bundle(let url) = self else { return nil }
        return url.standardizedFileURL.path + "/Contents/Resources"
    }

    /// The folder `--app-dir` names: it holds `app/`, `scripts/` and `config/`.
    public var codeRoot: String {
        switch self {
        case .bundle: return resources! + "/engine"
        case .repo(let repo): return repo
        }
    }

    /// The interpreter that runs uvicorn and the engine.
    public var enginePython: String {
        switch self {
        case .bundle: return resources! + "/python-engine/bin/python3.14"
        case .repo(let repo): return repo + "/" + ScriptRunner.Venv.app.rawValue + "/bin/python"
        }
    }

    /// The interpreter that runs `region_prep.py` and the other prep scripts.
    public var prepPython: String {
        switch self {
        case .bundle: return resources! + "/python-prep/bin/python3.14"
        case .repo(let repo): return repo + "/" + ScriptRunner.Venv.prep.rawValue + "/bin/python"
        }
    }

    /// The git-tracked plate files. In the bundle they are seeded into the data root.
    public var platesRoot: String {
        switch self {
        case .bundle: return resources! + "/plates"
        case .repo(let repo): return repo + "/regions"
        }
    }

    /// The engine's working directory. A repo engine runs in the checkout.
    public func dataRoot(home: String) -> String {
        switch self {
        case .bundle: return home + "/Library/Application Support/Tecopa Plateworks"
        case .repo(let repo): return repo
        }
    }

    /// One value of the bundle's Info.plist, or nil: a repo layout, a missing or
    /// unreadable plist, or a key that is absent or not a string. Read through
    /// `runtime.readData`, never PlistBuddy, so a test serves the bytes.
    public func infoValue(_ key: String, _ runtime: Runtime) -> String? {
        guard case .bundle(let url) = self,
              let data = runtime.readData(url.standardizedFileURL.path + "/Contents/Info.plist"),
              let plist = try? PropertyListSerialization.propertyList(from: data, format: nil),
              let dict = plist as? [String: Any] else { return nil }
        return dict[key] as? String
    }
}
