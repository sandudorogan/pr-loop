public struct QueueSection: Hashable, Identifiable, Sendable {
    public enum Kind: String, CaseIterable, Sendable {
        case inWork = "In Work"
        case upNext = "Up Next"
        case ready = "Ready"
        case waiting = "Waiting"
        case paused = "Paused"

        init(_ group: Group) {
            self =
                switch group {
                case .active: .inWork
                case .queued: .upNext
                case .ready: .ready
                case .idle, .unknown: .waiting
                case .paused: .paused
                }
        }
    }

    public let kind: Kind
    public let items: [QueueItem]

    public var id: Kind { kind }
    public var title: String { kind.rawValue }
}
