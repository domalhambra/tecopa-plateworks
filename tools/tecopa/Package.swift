// swift-tools-version: 6.0
import PackageDescription

// The `tecopa` tool: one binary that is a command line and an MCP server for the
// Tecopa Plateworks engine. Design: docs/superpowers/specs/2026-10-09-tecopa-cli-and-mcp-design.md
let package = Package(
    name: "tecopa",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(url: "https://github.com/apple/swift-argument-parser.git", from: "1.8.2"),
        .package(url: "https://github.com/modelcontextprotocol/swift-sdk.git", from: "0.12.1"),
    ],
    targets: [
        // Foundation only. Every operation lives here, so the CLI and the MCP server
        // cannot differ.
        .target(name: "TecopaKit"),
        .executableTarget(
            name: "tecopa",
            dependencies: [
                "TecopaKit",
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
                .product(name: "MCP", package: "swift-sdk"),
            ]),
        .testTarget(name: "TecopaKitTests", dependencies: ["TecopaKit", "tecopa"]),
    ],
    swiftLanguageModes: [.v5]
)
