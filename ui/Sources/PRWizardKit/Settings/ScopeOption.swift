/// One row of the Settings scope dropdown: "All repos", then each detected project.
public struct ScopeOption: Hashable, Identifiable, Sendable {
    public let scope: SettingsScope
    public let title: String
    public let detail: String
    public let isEnabled: Bool
    public let help: String?
    public let problem: String?

    public var id: String { scope.rawValue }

    public static let allRepos = ScopeOption(
        scope: .allRepos, title: "All repos", detail: "defaults", isEnabled: true, help: nil, problem: nil)

    public init(_ summary: ProjectSummary, overrides: Int, roots: [String]) {
        let project = summary.project
        let isMissing = project.status == .noCheckout && !project.isAvailable
        let count = overrides == 0 ? "no overrides" : overrides == 1 ? "1 override" : "\(overrides) overrides"
        self.init(
            scope: .project(project.repo), title: project.repo,
            detail: isMissing ? "unavailable: no local checkout" : "\(summary.laneLine) · \(count)",
            isEnabled: !isMissing, help: isMissing ? "Clone it into one of: \(roots.joined(separator: ", "))" : nil,
            problem: project.status == .error ? project.error : nil)
    }

    private init(
        scope: SettingsScope, title: String, detail: String, isEnabled: Bool, help: String?, problem: String?
    ) {
        self.scope = scope
        self.title = title
        self.detail = detail
        self.isEnabled = isEnabled
        self.help = help
        self.problem = problem
    }
}
