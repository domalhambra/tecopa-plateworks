// build.sh writes Baked.generated.swift (gitignored) and builds with -DTECOPA_BAKED.
// That file then supplies these two names. A plain `swift build` or `swift test`
// compiles the defaults below, so a test never depends on where this checkout is.
#if !TECOPA_BAKED
public let bakedRepoPath: String? = nil
public let bakedVersion: String = "dev"
#endif
