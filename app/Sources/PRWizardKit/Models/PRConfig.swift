import Foundation

public struct PRConfig: Codable, Hashable, Sendable {
    public struct Layers: Codable, Hashable, Sendable {
        public let project: [String]
        public let pr: [String]
    }

    public let key: String
    public let rev: String
    public let override: JSONValue?
    public let layers: Layers
    public let labels: [String]
    public let effective: EffectiveConfig
    public let createdAt: Date?
    public let updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case key, rev, override, layers, labels, effective
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}
