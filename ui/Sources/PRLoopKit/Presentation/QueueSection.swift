public struct QueueSection: Hashable, Identifiable, Sendable {
    public enum Kind: String, CaseIterable, Codable, Sendable {
        case toApprove, mine, done

        public var title: String {
            switch self {
            case .toApprove: "To Approve"
            case .mine: "My PRs"
            case .done: "Done"
            }
        }
    }

    public let kind: Kind
    /// To Approve and My PRs split into stages. Done has none: its rows sit right under its header.
    public let stages: [QueueStage]
    public let rows: [TodoRow]

    public var id: String { kind.rawValue }
    public var title: String { kind.title }
    public var dragID: String { "section:\(kind.rawValue)" }
}

/// One stage of a section, like "Ready for review" in My PRs.
public struct QueueStage: Hashable, Identifiable, Sendable {
    public enum Kind: String, CaseIterable, Codable, Sendable {
        case ready, active, queued, waiting, paused

        init(_ group: Group) {
            self =
                switch group {
                case .ready: .ready
                case .active: .active
                case .queued: .queued
                case .idle, .unknown: .waiting
                case .paused: .paused
                }
        }
    }

    public let section: QueueSection.Kind
    public let kind: Kind
    public let rows: [TodoRow]

    public var id: String { "\(section.rawValue).\(kind.rawValue)" }
    public var dragID: String { "stage:\(id)" }

    /// A ready stage says who acts next, like its rows do.
    public var style: StatusStyle {
        switch (kind, section) {
        case (.ready, .mine): StatusStyle(symbol: "checkmark.seal.fill", tone: .mine, label: "Ready for review")
        case (.ready, _): StatusStyle(symbol: "checkmark.seal.fill", tone: .good, label: "Ready to approve")
        case (.active, _): StatusStyle(symbol: "play.fill", tone: .working, label: "In work")
        case (.queued, _): StatusStyle(symbol: "clock", tone: .neutral, label: "Up next")
        case (.waiting, _): StatusStyle(symbol: "hourglass", tone: .neutral, label: "Waiting")
        case (.paused, _): StatusStyle(symbol: "pause.fill", tone: .neutral, label: "Paused")
        }
    }
}
