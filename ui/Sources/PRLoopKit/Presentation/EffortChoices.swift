public struct EffortChoices: Hashable, Sendable {
    public let efforts: [String]
    public let defaultLabel: String

    public init(_ choices: Choices, model: String?, effort: String?) {
        let listed = choices.codexModels.first { $0.model == model ?? choices.codexDefault?.model }
        let narrowed = listed?.efforts ?? choices.codexEfforts
        efforts = narrowed + [effort].compactMap { $0 }.filter { !narrowed.contains($0) }
        defaultLabel = choices.codexDefault?.effort.map { "Codex default (\($0))" } ?? "Codex default"
    }
}
