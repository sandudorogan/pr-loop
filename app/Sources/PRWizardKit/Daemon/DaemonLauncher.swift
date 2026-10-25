import Foundation

public protocol DaemonLauncher: Sendable {
    func run(_ executable: String, _ arguments: [String]) async throws
}

extension DaemonLauncher {
    public func start(labelFile: URL = DaemonLocation.labelFile, uid: uid_t = getuid()) async throws {
        let label = (try? String(contentsOf: labelFile, encoding: .utf8))?.trimmingCharacters(
            in: .whitespacesAndNewlines)
        try await run("/bin/launchctl", ["kickstart", "gui/\(uid)/\(label ?? DaemonLocation.label)"])
    }
}
