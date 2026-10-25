public struct ReviewOverride: Codable, Hashable, Sendable {
    public var isEnabled: Bool?
    public var workers: Int?
    public var rounds: Int?
    public var maxAdded: Int?
    public var trivial: [String]?
    public var timeout: Int?
    public var reviewers: [ReviewerConfig]?

    enum CodingKeys: String, CodingKey {
        case workers, rounds, trivial, reviewers
        case isEnabled = "enabled"
        case maxAdded = "max_added"
        case timeout = "timeout_s"
    }
}
