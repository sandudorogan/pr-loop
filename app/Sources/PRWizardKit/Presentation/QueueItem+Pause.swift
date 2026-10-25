extension [QueueItem] {
    /// Pause and Resume act on the whole selection: it resumes only when every selected PR is paused.
    public var resumes: Bool { !isEmpty && allSatisfy(\.isPaused) }
}
