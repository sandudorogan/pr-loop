public struct CodexModel: Codable, Hashable, Identifiable, Sendable {
    public let model: String
    public let efforts: [String]
    @Nullable public var defaultEffort: String?

    public var id: String { model }

    enum CodingKeys: String, CodingKey {
        case model, efforts
        case defaultEffort = "default_effort"
    }
}
