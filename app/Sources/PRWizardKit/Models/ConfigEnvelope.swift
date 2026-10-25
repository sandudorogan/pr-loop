public struct ConfigEnvelope: Codable, Hashable, Sendable {
    public let rev: String
    public let path: String
    public let realPath: String
    public let source: ConfigSource
    @Nullable public var error: String?
    public let config: DaemonConfig
    public let rawConfig: JSONValue
    public let defaults: DaemonConfig
    public let effective: [String: EffectiveConfig]
    public let choices: Choices

    enum CodingKeys: String, CodingKey {
        case rev, path, source, error, config, defaults, effective, choices
        case realPath = "real_path"
    }
}

extension ConfigEnvelope {
    public init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        rev = try container.decode(String.self, forKey: .rev)
        path = try container.decode(String.self, forKey: .path)
        realPath = try container.decode(String.self, forKey: .realPath)
        source = try container.decode(ConfigSource.self, forKey: .source)
        _error = try container.decode(Nullable<String>.self, forKey: .error)
        config = try container.decode(DaemonConfig.self, forKey: .config)
        rawConfig = try container.decode(JSONValue.self, forKey: .config)
        defaults = try container.decode(DaemonConfig.self, forKey: .defaults)
        effective = try container.decode([String: EffectiveConfig].self, forKey: .effective)
        choices = try container.decode(Choices.self, forKey: .choices)
    }
}
