import Foundation

public struct DaemonEvent: Codable, Hashable, Identifiable, Sendable {
    public let id: String
    public let seq: Int
    public let type: EventType
    public let key: String
    public let repo: String
    public let number: Int
    public let title: String
    public let url: URL
    public let author: String
    public let head: String
    public let verdict: Verdict?
    public let at: Date

    public var ref: PRRef { PRRef(repo: repo, number: number) }
}
