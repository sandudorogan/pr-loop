public struct NextResult: Codable, Hashable, Sendable {
    public struct Outcome: Codable, Hashable, Sendable {
        public let key: String
        public let isBumped: Bool
        public let reason: String?

        enum CodingKeys: String, CodingKey {
            case key, reason
            case isBumped = "bumped"
        }
    }

    public let next: [String]
    public let results: [Outcome]
}
