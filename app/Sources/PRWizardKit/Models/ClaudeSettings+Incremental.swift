extension ClaudeSettings {
    /// A lighter run on incremental diffs. Turning it on starts from the full run's model and effort.
    public var hasIncremental: Bool {
        get { incremental != nil }
        set { incremental = newValue ? incremental ?? ModelSetting(self) : nil }
    }
}
