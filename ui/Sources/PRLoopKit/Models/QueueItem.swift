import Foundation

public struct QueueItem: Codable, Hashable, Identifiable, Sendable {
    public let key: String
    public let repo: String
    public let number: Int
    public let title: String
    public let url: URL
    public let author: String
    public let isMine: Bool
    public let isDraft: Bool
    public let labels: [String]
    public let head: String
    public let base: String
    public let additions: Int
    public let deletions: Int
    public let pushedAt: Date
    public let updatedAt: Date
    public let isRequested: Bool
    public let isBumped: Bool
    public let group: Group
    public let rank: Int?
    public let isPaused: Bool
    public let isDone: Bool
    public let status: String
    public let detail: String
    public let active: ActiveRun?
    public let review: ReviewResult?
    public let findings: Findings?
    public let fix: FixResult?
    public let isFixQueued: Bool
    public let override: [String]

    public var id: String { key }
    public var ref: PRRef { PRRef(repo: repo, number: number) }

    enum CodingKeys: String, CodingKey {
        case key, repo, number, title, url, author, labels, head, base, additions, deletions
        case group, rank, status, detail, active, review, findings, fix, override
        case isMine = "mine"
        case isDraft = "draft"
        case pushedAt = "pushed_at"
        case updatedAt = "updated_at"
        case isRequested = "requested"
        case isBumped = "bumped"
        case isFixQueued = "fix_queued"
        case isPaused = "paused"
        case isDone = "done"
    }
}
