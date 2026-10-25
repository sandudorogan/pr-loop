public struct ConfigEnvelope: Codable, Hashable, Sendable {
    public let rev: String
    public let path: String
    public let realPath: String
    public let source: ConfigSource
    @Nullable public var error: String?
    public let config: DaemonConfig
    public let defaults: DaemonConfig
    public let effective: [String: EffectiveConfig]
    public let choices: Choices

    enum CodingKeys: String, CodingKey {
        case rev, path, source, error, config, defaults, effective, choices
        case realPath = "real_path"
    }
}
