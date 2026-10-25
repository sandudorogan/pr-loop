public struct EffectiveConfig: Codable, Hashable, Sendable {
    @Nullable public var root: String?
    public var review: ReviewConfig
    public var fix: FixConfig
}
