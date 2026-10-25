public struct FixOverride: Codable, Hashable, Sendable {
    public var isEnabled: Bool?
    public var workers: Int?
    public var engine: Engine?
    public var model: String?
    public var effort: String?
    public var prompt: String?
    public var mergePrompt: String?
    public var turnTimeout: Int?
    public var passTimeout: Int?
    public var maxErrors: Int?
    public var testRetries: Int?
    public var ciTries: Int?
    public var ciApps: [String]?
    public var gates: [GateConfig]?

    enum CodingKeys: String, CodingKey {
        case workers, engine, model, effort, prompt, gates
        case isEnabled = "enabled"
        case mergePrompt = "merge_prompt"
        case turnTimeout = "turn_timeout_s"
        case passTimeout = "pass_timeout_s"
        case maxErrors = "max_errors"
        case testRetries = "test_retries"
        case ciTries = "ci_tries"
        case ciApps = "ci_apps"
    }
}
