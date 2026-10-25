public struct ClaudeSettings: Codable, Hashable, Sendable {
    public var model: String?
    public var effort: String?
    public var incremental: ModelSetting?
    public var unknown: [String: JSONValue]

    static let empty = ClaudeSettings(model: nil, effort: nil, incremental: nil, unknown: [:])

    enum CodingKeys: String, CodingKey, CaseIterable {
        case model, effort, incremental
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(model, forKey: .model)
        try container.encode(effort, forKey: .effort)
        try container.encode(incremental, forKey: .incremental)
        try encoder.encode(unknownKeys: unknown)
    }
}

extension ClaudeSettings {
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        model = try container.decodeIfPresent(String.self, forKey: .model)
        effort = try container.decodeIfPresent(String.self, forKey: .effort)
        incremental = try container.decodeIfPresent(ModelSetting.self, forKey: .incremental)
        unknown = try decoder.unknownKeys(besides: CodingKeys.self)
    }
}
