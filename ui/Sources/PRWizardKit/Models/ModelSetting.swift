public struct ModelSetting: Codable, Hashable, Sendable {
    public var model: String?
    public var effort: String?
    public var unknown: JSONObject

    static let empty = ModelSetting(model: nil, effort: nil, unknown: [:])

    enum CodingKeys: String, CodingKey, CaseIterable {
        case model, effort
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(model, forKey: .model)
        try container.encode(effort, forKey: .effort)
        try encoder.encode(unknownKeys: unknown)
    }
}

extension ModelSetting {
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        model = try container.decodeIfPresent(String.self, forKey: .model)
        effort = try container.decodeIfPresent(String.self, forKey: .effort)
        unknown = try decoder.unknownKeys(besides: CodingKeys.self)
    }
}
