import Foundation

/// One row of the to-do list: an open PR from the queue snapshot, or a done one from the history.
public enum TodoRow: Hashable, Identifiable, Sendable {
    case open(QueueItem)
    case done(HistoryEntry)

    public var item: QueueItem? {
        if case .open(let item) = self { item } else { nil }
    }

    public var entry: HistoryEntry? {
        if case .done(let entry) = self { entry } else { nil }
    }

    public var id: String {
        switch self {
        case .open(let item): item.key
        case .done(let entry): entry.key
        }
    }

    public var ref: PRRef {
        switch self {
        case .open(let item): item.ref
        case .done(let entry): entry.ref
        }
    }

    public var url: URL {
        switch self {
        case .open(let item): item.url
        case .done(let entry): entry.url
        }
    }

    public var repo: String { ref.repo }

    public var title: String {
        switch self {
        case .open(let item): item.title
        case .done(let entry): entry.title
        }
    }

    public var author: String {
        switch self {
        case .open(let item): item.authorLabel
        case .done(let entry): entry.authorLabel
        }
    }

    public var login: String {
        switch self {
        case .open(let item): item.author
        case .done(let entry): entry.author
        }
    }

    public var status: StatusStyle {
        switch self {
        case .open(let item): StatusStyle(item)
        case .done(let entry): StatusStyle(entry.outcome)
        }
    }

    /// A done PR moves back only while it is open on GitHub.
    public var canMoveBack: Bool { entry?.state == .settled }
}

extension [TodoRow] {
    /// Mark Done acts on the whole selection, like Pause: it moves back only when every selected row is done.
    public var movesBack: Bool { !isEmpty && allSatisfy { $0.entry != nil } }

    /// The PRs Mark Done (or Move to To-Do) sends: a closed or merged PR has no way back.
    public var doneRefs: [PRRef] { movesBack ? filter(\.canMoveBack).map(\.ref) : compactMap(\.item?.ref) }
}
