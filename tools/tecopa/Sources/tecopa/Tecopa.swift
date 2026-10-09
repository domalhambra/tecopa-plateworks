import ArgumentParser
import TecopaKit

@main
struct Tecopa: AsyncParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "tecopa",
        abstract: "Control and diagnose the Tecopa Plateworks engine.",
        version: bakedVersion,
        subcommands: [
            DoctorCommand.self, EngineCommand.self, LogsCommand.self, RegionsCommand.self,
            JobsCommand.self, SessionsCommand.self, CachesCommand.self, MCPCommand.self,
        ])
}
