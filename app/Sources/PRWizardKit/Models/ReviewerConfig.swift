public struct ReviewerConfig: Codable, Hashable, Identifiable, Sendable {
    public var id: String
    public var isEnabled: Bool
    public var label: String
    public var prompt: String
    public var engine: Engine
    public var hasFallback: Bool
    public var needsConventions: Bool
    public var isAdvisory: Bool
    public var claude: ClaudeSettings
    public var codex: ModelSetting
    public var unknown: [String: JSONValue]

    enum CodingKeys: String, CodingKey, CaseIterable {
        case id, label, prompt, engine, claude, codex
        case isEnabled = "enabled"
        case hasFallback = "fallback"
        case needsConventions = "needs_conventions"
        case isAdvisory = "advisory"
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(isEnabled, forKey: .isEnabled)
        try container.encode(label, forKey: .label)
        try container.encode(prompt, forKey: .prompt)
        try container.encode(engine, forKey: .engine)
        try container.encode(hasFallback, forKey: .hasFallback)
        try container.encode(needsConventions, forKey: .needsConventions)
        try container.encode(isAdvisory, forKey: .isAdvisory)
        try container.encode(claude, forKey: .claude)
        try container.encode(codex, forKey: .codex)
        try encoder.encode(unknownKeys: unknown)
    }
}

extension ReviewerConfig {
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        isEnabled = try container.decodeIfPresent(Bool.self, forKey: .isEnabled) ?? true
        label = try container.decode(String.self, forKey: .label)
        prompt = try container.decode(String.self, forKey: .prompt)
        engine = try container.decode(Engine.self, forKey: .engine)
        hasFallback = try container.decodeIfPresent(Bool.self, forKey: .hasFallback) ?? true
        needsConventions = try container.decodeIfPresent(Bool.self, forKey: .needsConventions) ?? false
        isAdvisory = try container.decodeIfPresent(Bool.self, forKey: .isAdvisory) ?? false
        claude = try container.decodeIfPresent(ClaudeSettings.self, forKey: .claude) ?? .empty
        codex = try container.decodeIfPresent(ModelSetting.self, forKey: .codex) ?? .empty
        unknown = try decoder.unknownKeys(besides: CodingKeys.self)
    }
}
