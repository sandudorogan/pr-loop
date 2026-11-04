import AppKit
import PRWizardKit
import SwiftUI

struct QueueTable: View {
    /// The narrowest detail column that shows every column at its minimum without a horizontal scroller.
    static let minWidth: CGFloat = 566

    let sections: [QueueSection]
    let showsProject: Bool
    @Binding var selection: Set<TodoRow.ID>
    @Binding var columns: TableColumnCustomization<TodoRow>
    let showSettings: (TodoRow.ID) -> Void
    @Environment(QueueStore.self) private var store
    @Environment(PeekModel.self) private var peek
    @SceneStorage("collapsed") private var collapsed = QueueSection.Kind.done.rawValue

    var body: some View {
        Table(of: TodoRow.self, selection: $selection, columnCustomization: $columns) {
            TableColumn("") { MarkCell(row: $0) }.width(24).customizationID("mark")
            TableColumn("PR") { Text(verbatim: "#\($0.ref.number)").monospacedDigit() }.width(min: 52, ideal: 72)
                .customizationID("pr")
            if showsProject {
                TableColumn("Project") { Text(ProjectSummary.shortName(of: $0.repo)).lineLimit(1) }
                    .width(min: 48, ideal: 80).customizationID("project")
            }
            TableColumn("Title") { row in
                HStack(spacing: 4) {
                    if row.item?.isDraft == true { Text("[Draft]").foregroundStyle(.secondary) }
                    Text(row.title).lineLimit(1)
                }
                .findingsPeek(row.id, popover(row), peek: peek)
            }
            .width(min: 120).customizationID("title")
            TableColumn("Author") { Text($0.author).lineLimit(1) }
                .width(min: 48, ideal: 100).customizationID("author")
            TableColumn("Status") { row in
                HStack(spacing: 4) {
                    StatusBadge(style: row.status)
                    if let help = row.item?.overrideHelp {
                        Image(systemName: "slider.horizontal.3").foregroundStyle(.secondary).help(help)
                            .accessibilityLabel(help)
                    }
                }
                .findingsPeek(row.id, popover(row), isAnchor: true, peek: peek)
            }
            .width(min: 80, ideal: 150).customizationID("status")
            TableColumn("Detail") { DetailCell(row: $0).foregroundStyle(.secondary) }
                .width(min: 60, ideal: 180).customizationID("detail")
        } rows: {
            ForEach(sections) { section in
                Section(isExpanded: expanded(section.kind)) {
                    ForEach(section.rows) { TableRow($0) }
                } header: {
                    HStack(spacing: 6) {
                        Text(section.title)
                        Text(verbatim: "\(section.rows.count)").monospacedDigit().foregroundStyle(.secondary)
                    }
                }
            }
        }
        .contextMenu(forSelectionType: TodoRow.ID.self) { keys in
            PullRequestMenu(
                rows: rows(keys), store: store, peek: peekFocus(keys),
                showSettings: keys.first.map { key in { showSettings(key) } })
        } primaryAction: { keys in
            for row in rows(keys) { NSWorkspace.shared.open(row.url) }
        }
        .onExitCommand { peek.dismiss() }
        .onKeyPress(.space) { peekFocus(selection).pressSpace() }
        .focusedSceneValue(\.peekFocus, peekFocus(selection))
    }

    private var folded: Set<String> { Set(collapsed.split(separator: ",").map(String.init)) }

    private func expanded(_ kind: QueueSection.Kind) -> Binding<Bool> {
        Binding {
            !folded.contains(kind.rawValue)
        } set: { open in
            let kinds = open ? folded.subtracting([kind.rawValue]) : folded.union([kind.rawValue])
            collapsed = kinds.sorted().joined(separator: ",")
        }
    }

    private func popover(_ row: TodoRow) -> FindingsPopover? {
        switch row {
        case .open(let item): FindingsPopover(item: item)
        case .done(let entry): entry.findings.map { FindingsPopover(findings: $0, url: entry.url) }
        }
    }

    private func peekFocus(_ keys: Set<TodoRow.ID>) -> PeekFocus {
        let peekable = keys.count == 1 ? rows(keys).filter { popover($0) != nil } : []
        return PeekFocus(model: peek, id: peekable.first?.id)
    }

    private func rows(_ keys: Set<TodoRow.ID>) -> [TodoRow] {
        sections.flatMap(\.rows).filter { keys.contains($0.id) }
    }
}

private struct MarkCell: View {
    let row: TodoRow

    var body: some View {
        switch row {
        case .done:
            Image(systemName: "checkmark.circle").foregroundStyle(.secondary).accessibilityLabel("Done")
        case .open(let item):
            if item.active != nil {
                Image(systemName: "play.fill").foregroundStyle(Tone.working.color).accessibilityLabel("In work")
            } else if let rank = item.rank {
                Text("\(rank)").monospacedDigit().foregroundStyle(.secondary)
            } else if item.group == .ready {
                Image(systemName: "checkmark").foregroundStyle(row.status.tone.color).accessibilityLabel("Ready")
            } else if item.isPaused {
                Image(systemName: "pause.fill").foregroundStyle(.secondary).accessibilityLabel("Paused")
            }
        }
    }
}

private struct DetailCell: View {
    let row: TodoRow

    var body: some View {
        switch row {
        case .open(let item):
            if let active = item.active {
                Text(active.since, style: .timer).monospacedDigit()
            } else {
                Text(item.detail).lineLimit(1)
            }
        case .done(let entry):
            let when = Text(entry.closedAt ?? entry.at, format: .relative(presentation: .named))
            Text("\(HistoryRow(entry).stateLabel) · \(when)").lineLimit(1)
        }
    }
}
