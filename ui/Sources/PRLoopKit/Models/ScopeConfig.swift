public struct ScopeConfig: Codable, Hashable, Sendable {
    public var isEnabled: Bool
    public var workers: Int
    @Nullable public var model: String?
    @Nullable public var effort: String?
    public var timeout: Int

    enum CodingKeys: String, CodingKey {
        case workers, model, effort
        case isEnabled = "enabled"
        case timeout = "timeout_s"
    }
}
