public struct ProjectOverride: Codable, Hashable, Sendable {
    public var root: String?
    public var review: ReviewOverride?
    public var fix: FixOverride?
}
