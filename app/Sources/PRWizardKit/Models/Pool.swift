public struct Pool: Codable, Hashable, Identifiable, Sendable {
    public let id: String
    public let lane: Lane
    public let repo: String?
    public let workers: Int
    public let busy: Int
    public let pending: Int
}
