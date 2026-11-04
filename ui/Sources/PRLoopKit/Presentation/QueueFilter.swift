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

    /// To Approve, My PRs and Done in the layout's order. The first two split into stages, also in the layout's
    /// order; rows keep the daemon's order inside a stage. Empty sections and stages hide.
    public func sections(_ items: [QueueItem], done: [HistoryEntry] = [], layout: QueueLayout = QueueLayout())
        -> [QueueSection]
    {
        let open = self.items(items).filter { !$0.isDone }
        let finished = done.filter { $0.isDone && matches($0.repo, $0.key, $0.title) }.map(TodoRow.done)
        return layout.sectionOrder.compactMap { kind in
            let mine = open.filter { $0.isMine == (kind == .mine) }
            let stages: [QueueStage] =
                kind == .done
                ? []
                : layout.stageOrder(of: kind).compactMap { stage in
                    let rows = mine.filter { QueueStage.Kind($0.group) == stage }.map(TodoRow.open)
                    return rows.isEmpty ? nil : QueueStage(section: kind, kind: stage, rows: rows)
                }
            let rows = kind == .done ? finished : stages.flatMap(\.rows)
            return rows.isEmpty ? nil : QueueSection(kind: kind, stages: stages, rows: rows)
        }
    }

    private func matches(_ repo: String, _ key: String, _ title: String) -> Bool {
        (self.repo == nil || self.repo == repo) && (query.isEmpty || "\(key) \(title)".localizedStandardContains(query))
    }
}
