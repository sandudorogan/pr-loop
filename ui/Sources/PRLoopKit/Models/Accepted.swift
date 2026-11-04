public struct Accepted: Codable, Hashable, Sendable {
    public let key: String?
    public let isAccepted: Bool

    enum CodingKeys: String, CodingKey {
        case key
        case isAccepted = "accepted"
    }
}
