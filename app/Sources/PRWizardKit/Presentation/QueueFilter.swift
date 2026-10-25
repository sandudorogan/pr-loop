import Foundation

public struct QueueFilter: Hashable, Sendable {
    public var repo: String?
    public var text: String

    public init(repo: String? = nil, text: String = "") {
        self.repo = repo
        self.text = text
    }

    public func items(_ items: [QueueItem]) -> [QueueItem] {
        let text = text.trimmingCharacters(in: .whitespaces)
        return items.filter { item in
            (repo == nil || item.repo == repo)
                && (text.isEmpty || "\(item.key) \(item.title)".localizedStandardContains(text))
        }
    }

    public func sections(_ items: [QueueItem]) -> [QueueSection] {
        let groups = Dictionary(grouping: self.items(items)) { QueueSection.Kind($0.group) }
        return QueueSection.Kind.allCases.compactMap { kind in
            groups[kind].map { QueueSection(kind: kind, items: $0) }
        }
    }
}
