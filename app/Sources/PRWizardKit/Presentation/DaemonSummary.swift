import Foundation

public struct DaemonSummary: Hashable, Sendable {
    public let line: String

    public init(_ info: DaemonInfo, _ snapshot: QueueSnapshot, now: Date = .now) {
        let version = info.commit.map { "\(info.version) (\($0))" } ?? info.version
        let active = snapshot.projects.count { $0.status == .active }
        line =
            "\(version) · up \(Self.uptime(now.timeIntervalSince(info.startedAt))) · "
            + "\(active) active repos of \(snapshot.projects.count)"
    }

    static func uptime(_ seconds: TimeInterval) -> String {
        switch Int(seconds) {
        case ..<3600: "\(Int(seconds) / 60) min"
        case ..<86400: "\(Int(seconds) / 3600) h"
        default: "\(Int(seconds) / 86400) d"
        }
    }
}
