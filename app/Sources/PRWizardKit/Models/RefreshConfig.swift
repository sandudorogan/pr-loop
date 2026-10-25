public struct RefreshConfig: Codable, Hashable, Sendable {
    public var interval: Int
    public var idle: Int

    enum CodingKeys: String, CodingKey {
        case interval = "interval_s"
        case idle = "idle_s"
    }
}
