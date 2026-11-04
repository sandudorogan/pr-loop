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
        items.filter { matches($0.repo, $0.key, $0.title) }
    }

    /// To Approve, then My PRs, each with what needs me on top, then Done. Empty sections hide.
    public func sections(_ items: [QueueItem], done: [HistoryEntry] = []) -> [QueueSection] {
        let open = self.items(items).filter { !$0.isDone }.sorted { $0.group.attention < $1.group.attention }
        let rows: [QueueSection.Kind: [TodoRow]] = [
            .toApprove: open.filter { !$0.isMine }.map(TodoRow.open),
            .mine: open.filter(\.isMine).map(TodoRow.open),
            .done: done.filter { $0.isDone && matches($0.repo, $0.key, $0.title) }.map(TodoRow.done),
        ]
        return QueueSection.Kind.allCases.compactMap { kind in
            rows[kind].flatMap { $0.isEmpty ? nil : QueueSection(kind: kind, rows: $0) }
        }
    }

    private func matches(_ repo: String, _ key: String, _ title: String) -> Bool {
        (self.repo == nil || self.repo == repo) && (query.isEmpty || "\(key) \(title)".localizedStandardContains(query))
    }
}
