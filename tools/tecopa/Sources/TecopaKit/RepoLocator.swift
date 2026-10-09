import Foundation

/// Where the repo is. The first source that names a path wins, and a wrong path is
/// an error: the tool never searches, and never falls through to another repo.
public enum RepoLocator {
    /// The file that proves a folder is the repo.
    static let marker = "app/main.py"

    public static func resolve(flag: String?, env: [String: String], baked: String?,
                               fileExists: (String) -> Bool) throws -> String {
        let candidates: [(source: String, path: String?)] = [
            ("--repo", flag),
            ("TECOPA_REPO", env["TECOPA_REPO"]),
            ("the path baked at build time", baked),
        ]
        guard let chosen = candidates.first(where: { !($0.path ?? "").isEmpty }),
              let path = chosen.path else {
            throw TecopaFailure(
                .environment, "No repository path is known.",
                hint: "Pass --repo, set TECOPA_REPO, or build with tools/tecopa/build.sh --install.")
        }
        let clean = path.hasSuffix("/") ? String(path.dropLast()) : path
        guard fileExists(clean + "/" + marker) else {
            throw TecopaFailure(
                .environment, "The repository is not at \(clean) (from \(chosen.source)).",
                hint: "Rebuild with tools/tecopa/build.sh --install, or pass --repo.")
        }
        return clean
    }
}
