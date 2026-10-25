import AppKit
import PRWizardKit
import SwiftUI

struct QueueTable: View {
    let sections: [QueueSection]
    let showsProject: Bool
    @Binding var selection: Set<QueueItem.ID>
    @Binding var columns: TableColumnCustomization<QueueItem>
    let showSettings: (QueueItem.ID) -> Void
    @Environment(QueueStore.self) private var store
    @Environment(PeekModel.self) private var peek

    var body: some View {
        Table(of: QueueItem.self, selection: $selection, columnCustomization: $columns) {
            TableColumn("") { MarkCell(item: $0) }.width(24).customizationID("mark")
            TableColumn("PR") { Text(verbatim: "#\($0.number)").monospacedDigit() }.width(min: 56, ideal: 72)
                .customizationID(
                    "pr")
            if showsProject {
                TableColumn("Project") { Text(ProjectSummary.shortName(of: $0.repo)).lineLimit(1) }
                    .width(min: 60, ideal: 80).customizationID("project")
            }
            TableColumn("Title") { item in
                HStack(spacing: 4) {
                    if item.isDraft { Text("[Draft]").foregroundStyle(.secondary) }
                    Text(item.title).lineLimit(1)
                }
                .hoverPeek(item.id, FindingsPopover(item: item), peek: peek)
            }
            .width(min: 160).customizationID("title")
            TableColumn("Author") { Text($0.isMine ? "you" : $0.author).lineLimit(1) }
                .width(min: 60, ideal: 100).customizationID("author")
            TableColumn("Status") { item in
                HStack(spacing: 4) {
                    StatusBadge(status: item.status)
                    if let help = item.overrideHelp {
                        Image(systemName: "slider.horizontal.3").foregroundStyle(.secondary).help(help)
                            .accessibilityLabel(help)
                    }
                }
                .hoverPeek(item.id, FindingsPopover(item: item), isAnchor: true, peek: peek)
            }
            .width(min: 90, ideal: 150).customizationID("status")
            TableColumn("Detail") { item in
                Group {
                    if let active = item.active {
                        Text(active.since, style: .timer).monospacedDigit()
                    } else {
                        Text(item.detail).lineLimit(1)
                    }
                }
                .foregroundStyle(.secondary)
            }
            .width(min: 80, ideal: 180).customizationID("detail")
        } rows: {
            ForEach(sections) { section in
                Section(section.title) { ForEach(section.items) { TableRow($0) } }
            }
        }
        .contextMenu(forSelectionType: QueueItem.ID.self) { keys in
            PullRequestMenu(
                items: items(keys), store: store, peek: peekFocus(keys),
                showSettings: keys.first.map { key in { showSettings(key) } })
        } primaryAction: { keys in
            for item in items(keys) { NSWorkspace.shared.open(item.url) }
        }
        .onExitCommand { peek.dismiss() }
        .onKeyPress(.space) { peekFocus(selection).pressSpace() }
        .focusedSceneValue(\.peekFocus, peekFocus(selection))
    }

    private func peekFocus(_ keys: Set<QueueItem.ID>) -> PeekFocus {
        PeekFocus(model: peek, id: keys.count == 1 ? keys.first : nil)
    }

    private func items(_ keys: Set<QueueItem.ID>) -> [QueueItem] {
        sections.flatMap(\.items).filter { keys.contains($0.id) }
    }
}

private struct MarkCell: View {
    let item: QueueItem

    var body: some View {
        if item.active != nil {
            Image(systemName: "play.fill").foregroundStyle(Tone.working.color).accessibilityLabel("In work")
        } else if let rank = item.rank {
            Text("\(rank)").monospacedDigit().foregroundStyle(.secondary)
        } else if item.group == .ready {
            Image(systemName: "checkmark").foregroundStyle(Tone.good.color).accessibilityLabel("Ready")
        }
    }
}
