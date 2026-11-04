public struct DoneState: Codable, Hashable, Sendable {
    public let isDone: Bool

    enum CodingKeys: String, CodingKey {
        case isDone = "done"
    }
}
