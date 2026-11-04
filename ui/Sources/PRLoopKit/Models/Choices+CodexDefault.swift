extension Choices {
    public var codexModelLabel: String {
        codexDefault.map { "Codex default (\($0.model))" } ?? "Codex default"
    }
}
