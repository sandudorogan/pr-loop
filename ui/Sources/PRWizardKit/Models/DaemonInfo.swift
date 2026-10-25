import Foundation

public struct DaemonInfo: Codable, Hashable, Sendable {
    public let name: String
    public let version: String
    public let commit: String?
    public let api: Int
    public let pid: Int
    public let startedAt: Date
    public let uptime: Int
    public let label: String
    public let isPaused: Bool
    public let projects: [Project]
    public let lanes: Lanes
    public let refresh: RefreshStatus
    public let config: ConfigStatus
    public let paths: DaemonPaths

    enum CodingKeys: String, CodingKey {
        case name, version, commit, api, pid, label, projects, lanes, refresh, config, paths
        case startedAt = "started_at"
        case uptime = "uptime_s"
        case isPaused = "paused"
    }
}
