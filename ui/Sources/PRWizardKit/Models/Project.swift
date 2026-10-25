public struct Project: Codable, Hashable, Identifiable, Sendable {
    public let repo: String
    public let status: ProjectStatus
    public let isAvailable: Bool
    public let isReviewEnabled: Bool
    public let isFixEnabled: Bool
    public let checkout: Checkout?
    public let prs: Int
    public let error: String?
    public let conventions: Conventions?
    public let gates: [ProjectGate]

    public var id: String { repo }

    enum CodingKeys: String, CodingKey {
        case repo, status, checkout, prs, error, conventions, gates
        case isAvailable = "available"
        case isReviewEnabled = "review"
        case isFixEnabled = "fix"
    }
}
