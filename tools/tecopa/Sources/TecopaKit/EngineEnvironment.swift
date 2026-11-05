import Foundation

/// The engine's one environment builder (spec 5.3). Every path is absolute, so
/// nothing relies on a relative default or on the working directory.
public enum EngineEnvironment {
    /// Never passed to the engine. `PYTHONSTARTUP` and `__PYVENV_LAUNCHER__` go too,
    /// as `ScriptRunner.droppedVariables` drops them.
    public static let removedNames = [
        "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "__PYVENV_LAUNCHER__", "PROJ_LIB",
        "PROJ_DATA", "GDAL_DATA", "TECOPA_RELIEF_WORKERS",
    ]
    /// Every inherited `TECOPA_*` goes, so a settings key that `settings.json` does
    /// not hold is unset, whatever the shell said.
    public static let removedPrefixes = ["GDAL_", "DYLD_", "TECOPA_"]

    /// The keys `settings.json` may set. Any other key there is ignored.
    public static func isSettingsKey(_ key: String) -> Bool {
        key == "TECOPA_ORDERS_DIR" || key == "TECOPA_INTAKE_DIR" || key.hasPrefix("TECOPA_FONT")
    }

    /// `settings.json` is a flat JSON object keyed by environment name. No file is
    /// no settings. A file that is not a JSON object throws, and the app does not
    /// spawn. A value that is not a string is skipped.
    public static func settings(from data: Data?, path: String) throws -> [String: String] {
        guard let data else { return [:] }
        guard let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            throw TecopaFailure(.environment, "settings.json is not valid JSON: " + path)
        }
        return object.compactMapValues { $0 as? String }
    }

    public static func build(layout: EngineLayout, home: String, base: [String: String],
                             settings: [String: String], engineVersion: String) -> [String: String] {
        var env = base.filter { key, _ in
            !removedNames.contains(key) && !removedPrefixes.contains(where: { key.hasPrefix($0) })
        }
        for (key, value) in settings where isSettingsKey(key) { env[key] = value }
        let data = layout.dataRoot(home: home)
        env["TECOPA_REGIONS"] = data + "/regions"
        env["TECOPA_BLOBS"] = data + "/blobs"
        env["TECOPA_UPLOADS"] = data + "/uploads"
        env["TECOPA_PREP_PYTHON"] = layout.prepPython
        env["TECOPA_PREP_SCRIPT"] = layout.codeRoot + "/region_prep.py"
        env["TECOPA_LABELS_SCRIPT"] = layout.codeRoot + "/scripts/build_labels.py"
        // Always set: without it app/provenance.py shells out to git on import.
        env["TECOPA_ENGINE_VERSION"] = engineVersion
        env["TECOPA_DEBUG"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONNOUSERSITE"] = "1"
        return env
    }

    /// The engine command, exactly. `-P` and an explicit `--app-dir` keep the
    /// working directory off `sys.path` (spec 5.2).
    public static func command(layout: EngineLayout, port: Int) -> (executable: String, arguments: [String]) {
        (layout.enginePython,
         ["-P", "-m", "uvicorn", "app.main:app", "--app-dir", layout.codeRoot,
          "--host", "127.0.0.1", "--port", String(port)])
    }
}
