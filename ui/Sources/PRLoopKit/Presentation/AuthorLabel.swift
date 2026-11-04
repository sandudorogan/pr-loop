extension QueueItem {
    /// "you" on my PR, else the author's name on GitHub, else the login.
    public var authorLabel: String { isMine ? "you" : authorName ?? author }
}

extension HistoryEntry {
    /// "you" on my PR, else the author's name on GitHub, else the login.
    public var authorLabel: String { isMine ? "you" : authorName ?? author }
}
