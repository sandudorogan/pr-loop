public struct PauseState: Codable, Hashable, Sendable {
    public let isPaused: Bool

    enum CodingKeys: String, CodingKey {
        case isPaused = "paused"
    }
}
