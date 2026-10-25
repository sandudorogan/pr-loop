import Foundation

public protocol DaemonLauncher: Sendable {
    func run(_ executable: String, _ arguments: [String]) async throws
    func start() async throws
}

extension DaemonLauncher {
    public func start() async throws {
        try await start(labelFile: DaemonLocation.labelFile, uid: getuid())
    }

    public func start(labelFile: URL, uid: uid_t) async throws {
        let label = (try? String(contentsOf: labelFile, encoding: .utf8))?.trimmingCharacters(
            in: .whitespacesAndNewlines)
        try await run("/bin/launchctl", ["kickstart", "gui/\(uid)/\(label ?? DaemonLocation.label)"])
    }
}
