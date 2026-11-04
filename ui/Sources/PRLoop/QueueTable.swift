import AppKit
import PRLoopKit
import SwiftUI

struct QueueTable: View {
    /// The narrowest detail column that shows every column at its minimum without a horizontal scroller.
    static let minWidth: CGFloat = 566

    let sections: [QueueSection]
    @Binding var layout: QueueLayout
    let showsProject: Bool
    @Binding var selection: Set<TodoRow.ID>
    @Binding var columns: TableColumnCustomization<TodoRow>
    let showSettings: (TodoRow.ID) -> Void
    @Environment(QueueStore.self) private var store
    @Environment(PeekModel.self) private var peek
    @SceneStorage("folded") private var folded = QueueSection.Kind.done.rawValue

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
            TableColumn("Author") { Text($0.author).lineLimit(1).help("@\($0.login)") }
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
                Section {
                    if isOpen(section.id) && section.stages.isEmpty {
                        ForEach(section.rows) { TableRow($0) }
                    }
                } header: {
                    header(
                        section.dragID, section.title, section.rows.count, folding: section.id,
                        among: sections.map(\.dragID))
                }
                if isOpen(section.id) {
                    ForEach(section.stages) { stage in
                        Section {
                            if isOpen(stage.id) {
                                ForEach(stage.rows) { TableRow($0) }
                            }
                        } header: {
                            header(
                                stage.dragID, stage.style.label, stage.rows.count, folding: stage.id,
                                among: section.stages.map(\.dragID), style: stage.style)
                        }
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

    private var foldedIDs: Set<String> { Set(folded.split(separator: ",").map(String.init)) }

    private func isOpen(_ id: String) -> Bool { !foldedIDs.contains(id) }

    /// A section or stage header. Moving one swaps it with its visible neighbour, so Move Up never lands on a
    /// hidden (empty) stage.
    private func header(
        _ dragID: String, _ title: String, _ count: Int, folding id: String, among siblings: [String],
        style: StatusStyle? = nil
    ) -> some View {
        let neighbour = { (offset: Int) in
            siblings.firstIndex(of: dragID).map { $0 + offset }.flatMap {
                siblings.indices.contains($0) ? siblings[$0] : nil
            }
        }
        return QueueHeader(
            title: title, count: count, style: style,
            isOpen: Binding {
                isOpen(id)
            } set: { open in
                folded = (open ? foldedIDs.subtracting([id]) : foldedIDs.union([id])).sorted().joined(separator: ",")
            },
            dragID: dragID, drop: { layout.drop($0, on: dragID) },
            up: neighbour(-1).map { above in { layout.drop(dragID, on: above) } },
            down: neighbour(1).map { below in { layout.drop(dragID, on: below) } })
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

/// A collapsible header that drags onto another header of its level, or moves from its menu.
private struct QueueHeader: View {
    let title: String
    let count: Int
    let style: StatusStyle?
    @Binding var isOpen: Bool
    let dragID: String
    let drop: (String) -> Bool
    let up: (() -> Void)?
    let down: (() -> Void)?

    var body: some View {
        HStack(spacing: 6) {
            Button {
                isOpen.toggle()
            } label: {
                Image(systemName: "chevron.right").rotationEffect(.degrees(isOpen ? 90 : 0)).frame(width: 12)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
            .accessibilityLabel(isOpen ? "Collapse \(title)" : "Expand \(title)")
            if let style { Image(systemName: style.symbol).foregroundStyle(style.tone.color) }
            Text(title).font(style == nil ? .headline : .subheadline.weight(.semibold))
            Text(verbatim: "\(count)").monospacedDigit().foregroundStyle(.secondary)
            Spacer()
        }
        .padding(.leading, style == nil ? 0 : 18)
        .contentShape(Rectangle())
        .draggable(dragID)
        .dropDestination(for: String.self) { ids, _ in ids.first.map(drop) ?? false }
        .contextMenu {
            Button("Move Up") { up?() }.disabled(up == nil)
            Button("Move Down") { down?() }.disabled(down == nil)
        }
    }
}
