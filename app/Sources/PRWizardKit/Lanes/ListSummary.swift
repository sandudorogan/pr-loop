public enum ListSummary {
    /// The first few entries joined by spaces, then an ellipsis when more follow.
    public static func line(_ entries: [String], limit: Int = 4) -> String {
        (entries.prefix(limit) + (entries.count > limit ? ["…"] : [])).joined(separator: "  ")
    }
}
