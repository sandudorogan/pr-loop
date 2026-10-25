extension ModelSetting {
    init(_ claude: ClaudeSettings) {
        self.init(model: claude.model, effort: claude.effort, unknown: [:])
    }
}
