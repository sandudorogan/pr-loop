import Foundation

public struct QueueFilter: Hashable, Sendable {
    public var repo: String?
    public var text: String

    public init(repo: String? = nil, text: String = "") {
        self.repo = repo
        self.text = text
    }

    public var query: String { text.trimmingCharacters(in: .whitespaces) }

    public func items(_ items: [QueueItem]) -> [QueueItem] {
        items.filter { item in
            (repo == nil || item.repo == repo)
                && (query.isEmpty || "\(item.key) \(item.title)".localizedStandardContains(query))
        }
    }

    public func sections(_ items: [QueueItem]) -> [QueueSection] {
        let groups = Dictionary(grouping: self.items(items)) { QueueSection.Kind($0.group) }
        return QueueSection.Kind.allCases.compactMap { kind in
            groups[kind].map { QueueSection(kind: kind, items: $0) }
        }
    }
}
