import Foundation

public struct ReviewResult: Codable, Hashable, Sendable {
    public let sha: String
    public let isCurrent: Bool
    public let status: String
    public let verdict: Verdict?
    public let note: String
    public let rounds: Int
    public let isHeld: Bool
    public let at: Date

    enum CodingKeys: String, CodingKey {
        case sha, status, verdict, note, rounds, at
        case isCurrent = "current"
        case isHeld = "hold"
    }
}
