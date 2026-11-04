public struct QueueSection: Hashable, Identifiable, Sendable {
    public enum Kind: String, CaseIterable, Sendable {
        case toApprove = "To Approve"
        case mine = "My PRs"
        case done = "Done"
    }

    public let kind: Kind
    public let rows: [TodoRow]

    public var id: Kind { kind }
    public var title: String { kind.rawValue }
}

extension Group {
    /// What needs me first: a ready PR, then the bots' work in order, then what waits.
    var attention: Int {
        switch self {
        case .ready: 0
        case .active: 1
        case .queued: 2
        case .idle, .unknown: 3
        case .paused: 4
        }
    }
}
