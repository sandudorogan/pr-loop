import Foundation

public struct HistoryEntry: Codable, Hashable, Identifiable, Sendable {
    public let key: String
    public let repo: String
    public let number: Int
    public let title: String
    public let url: URL
    public let author: String
    public let authorName: String?
    public let isMine: Bool
    public let state: HistoryState
    public let outcome: String
    public let rounds: Int
    public let fixesPushed: Int
    public let head: String
    public let firstAt: Date
    public let at: Date
    public let closedAt: Date?
    public let findings: Findings?
    public let isDone: Bool

    public var id: String { key }
    public var ref: PRRef { PRRef(repo: repo, number: number) }

    enum CodingKeys: String, CodingKey {
        case key, repo, number, title, url, author, state, outcome, rounds, head, at, findings
        case isMine = "mine"
        case authorName = "author_name"
        case fixesPushed = "fixes_pushed"
        case firstAt = "first_at"
        case closedAt = "closed_at"
        case isDone = "done"
    }
}
