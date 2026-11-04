/// How many review and fix passes the machine runs at once, from the draft: engine usage caps and Karma load are machine-wide.
public struct WorkerTotals: Hashable, Sendable {
    public static let limit = 8

    public let reviews: Int
    public let fixes: Int

    public var isOverLimit: Bool { max(reviews, fixes) > Self.limit }

    public var summary: String {
        let line =
            "Machine total: \(reviews) \(reviews == 1 ? "review" : "reviews"), "
            + "\(fixes) fix \(fixes == 1 ? "pass" : "passes") at once"
        return isOverLimit ? "\(line) (above \(Self.limit))." : "\(line)."
    }

    /// Shared pools: one of each. Separate pools: one per project with a checkout and that lane on.
    public init(draft: OverrideResolver, projects: [Project]) {
        func workers(_ lane: String, _ scope: SettingsScope) -> Int {
            draft.resolve("\(lane).workers", in: scope).value.int ?? 0
        }
        guard draft.resolve("lanes.separate", in: .allRepos).value == .bool(true) else {
            reviews = workers("review", .allRepos)
            fixes = workers("fix", .allRepos)
            return
        }
        func total(_ lane: String) -> Int {
            projects.filter { $0.isAvailable }.reduce(0) { sum, project in
                let scope = SettingsScope.project(project.repo)
                return draft.resolve("\(lane).enabled", in: scope).value == .bool(true)
                    ? sum + workers(lane, scope) : sum
            }
        }
        reviews = total("review")
        fixes = total("fix")
    }
}
