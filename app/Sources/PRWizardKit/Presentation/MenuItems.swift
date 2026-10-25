import Foundation

public enum MenuItems: Hashable, Sendable {
    case connecting
    case down
    case incompatible(api: Int)
    case empty
    case top([Row])

    public struct Row: Hashable, Identifiable, Sendable {
        public static let titleLimit = 44

        public let ref: PRRef
        public let url: URL
        public let symbol: String
        public let text: String

        public var id: String { ref.id }

        init(_ item: QueueItem) {
            let title =
                item.title.count > Self.titleLimit ? "\(item.title.prefix(Self.titleLimit - 1))…" : item.title
            ref = item.ref
            url = item.url
            symbol = StatusStyle(item.status).symbol
            text = "\(ProjectSummary.shortName(of: item.repo)) #\(item.number)  \(title)"
        }
    }

    public static func top(_ limit: Int, in phase: QueueStore.Phase) -> MenuItems {
        switch phase {
        case .idle, .connecting: .connecting
        case .down, .stale: .down
        case .incompatible(let api): .incompatible(api: api)
        case .live(let snapshot): snapshot.items.isEmpty ? .empty : .top(snapshot.items.prefix(limit).map(Row.init))
        }
    }
}
