public struct Choices: Codable, Hashable, Sendable {
    public let engines: [String]
    public let fixEngines: [String]
    public let gateKinds: [String]
    public let claudeEfforts: [String]
    public let codexEfforts: [String]
    public let claudeModels: [String]
    @Nullable public var codexDefault: CodexDefault?
    public let codexModels: [CodexModel]
    public let prompts: [String]

    enum CodingKeys: String, CodingKey {
        case engines, prompts
        case fixEngines = "fix_engines"
        case gateKinds = "gate_kinds"
        case claudeEfforts = "claude_efforts"
        case codexEfforts = "codex_efforts"
        case claudeModels = "claude_models"
        case codexDefault = "codex_default"
        case codexModels = "codex_models"
    }
}
