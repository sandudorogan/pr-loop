public struct LanesConfig: Codable, Hashable, Sendable {
    public var isSeparate: Bool

    enum CodingKeys: String, CodingKey {
        case isSeparate = "separate"
    }
}
