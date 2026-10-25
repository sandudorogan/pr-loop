public struct ProjectSummary: Hashable, Identifiable, Sendable {
    public let project: Project
    public let pools: [Pool]
    public let readyCount: Int
    public let activeCount: Int

    public var id: String { project.repo }
    public var name: String { Self.shortName(of: project.repo) }

    public var needsAttention: Bool { [.error, .noCheckout].contains(project.status) }

    public var laneLine: String {
        switch (project.status, project.isReviewEnabled, project.isFixEnabled) {
        case (.error, _, _): "checkout error"
        case (.noCheckout, _, _): "no local checkout"
        case (_, true, true): "review · fix"
        case (_, false, true): "fix only"
        case (_, true, false): "review only"
        case (_, false, false): "lanes off"
        }
    }

    public init(_ project: Project, in snapshot: QueueSnapshot) {
        let items = snapshot.items.filter { $0.repo == project.repo }
        self.project = project
        pools = snapshot.lanes.isSeparate ? snapshot.lanes.pools.filter { $0.repo == project.repo } : []
        readyCount = items.count { $0.group == .ready }
        activeCount = items.count { $0.group == .active }
    }

    public static func shortName(of repo: String) -> String {
        repo.split(separator: "/").last.map(String.init) ?? repo
    }
}
