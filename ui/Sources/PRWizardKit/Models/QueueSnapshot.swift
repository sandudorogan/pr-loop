import Foundation

public struct QueueSnapshot: Codable, Hashable, Sendable {
    public let rev: String
    public let generatedAt: Date
    public let fetchedAt: Date?
    public let isPaused: Bool
    public let lanes: Lanes
    public let projects: [Project]
    public let refresh: RefreshStatus
    public let counts: QueueCounts
    public let items: [QueueItem]

    enum CodingKeys: String, CodingKey {
        case rev, lanes, projects, refresh, counts, items
        case generatedAt = "generated_at"
        case fetchedAt = "fetched_at"
        case isPaused = "paused"
    }
}
