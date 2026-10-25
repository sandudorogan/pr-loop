extension QueueItem {
    public var overrideHelp: String? {
        override.isEmpty ? nil : "Overridden for this PR: \(override.joined(separator: ", "))"
    }
}
