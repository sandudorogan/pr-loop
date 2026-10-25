public struct QueueCounts: Codable, Hashable, Sendable {
    public let active: Int
    public let queued: Int
    public let ready: Int
    public let idle: Int
}
