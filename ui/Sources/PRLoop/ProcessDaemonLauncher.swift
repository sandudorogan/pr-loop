import Foundation
import PRLoopKit

nonisolated struct ProcessDaemonLauncher: DaemonLauncher {
    struct Failure: LocalizedError {
        let status: Int32

        var errorDescription: String? { "launchctl kickstart exited with status \(status)" }
    }

    @concurrent func run(_ executable: String, _ arguments: [String]) async throws {
        let process = Process()
        process.executableURL = URL(filePath: executable)
        process.arguments = arguments
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { throw Failure(status: process.terminationStatus) }
    }
}
