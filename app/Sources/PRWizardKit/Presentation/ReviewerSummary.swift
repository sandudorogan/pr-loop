/// The reviewer list subtitle: `engine · model · effort`, then its traits.
public struct ReviewerSummary: Hashable, Sendable {
    public let engine: String
    public let traits: String?
    public let isSkipped: Bool

    /// - Parameter project: the scope's project; a project with no conventions skips a `needs_conventions` reviewer.
    public init(_ reviewer: ReviewerConfig, project: Project? = nil) {
        let model = reviewer.engine == .codex ? reviewer.codex : ModelSetting(reviewer.claude)
        engine = [reviewer.engine.rawValue, model.model ?? "default", model.effort].compactMap { $0 }
            .joined(separator: " · ")
        let traits = [
            reviewer.isAdvisory ? "advisory" : nil, reviewer.needsConventions ? "conventions" : nil,
            reviewer.isEnabled ? nil : "off",
        ]
        .compactMap { $0 }
        self.traits = traits.isEmpty ? nil : traits.joined(separator: " · ")
        isSkipped =
            reviewer.isEnabled && reviewer.needsConventions
            && project?.conventions.map { $0.files.isEmpty && $0.skills.isEmpty } == true
    }
}
