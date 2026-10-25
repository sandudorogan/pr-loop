public struct EventPage: Codable, Hashable, Sendable {
    public let cursor: String
    public let isReset: Bool
    public let events: [DaemonEvent]

    enum CodingKeys: String, CodingKey {
        case cursor, events
        case isReset = "reset"
    }
}
