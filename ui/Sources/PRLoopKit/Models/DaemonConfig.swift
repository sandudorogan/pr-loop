public struct DaemonConfig: Codable, Hashable, Sendable {
    public var version: Int
    public var detect: DetectConfig
    public var lanes: LanesConfig
    public var projects: [String: ProjectOverride]
    public var review: ReviewConfig
    public var fix: FixConfig
    public var refresh: RefreshConfig
}
