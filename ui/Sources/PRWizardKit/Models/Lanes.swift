public struct Lanes: Codable, Hashable, Sendable {
    public let isSeparate: Bool
    public let pools: [Pool]

    enum CodingKeys: String, CodingKey {
        case isSeparate = "separate"
        case pools
    }
}
