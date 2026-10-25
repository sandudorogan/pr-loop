public struct Findings: Codable, Hashable, Sendable {
    public let head: String
    public let isCurrent: Bool
    public let round: Int
    public let atFloor: Int
    public let conventions: [String]
    public let reviewers: [ReviewerFindings]
    public let top: [TopFinding]

    enum CodingKeys: String, CodingKey {
        case head, round, conventions, reviewers, top
        case isCurrent = "current"
        case atFloor = "at_floor"
    }
}
