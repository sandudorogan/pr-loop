import AppKit
import PRWizardKit
import SwiftUI

struct HistoryTable: View {
    let rows: [HistoryRow]
    let showsProject: Bool
    @State private var selection = Set<HistoryRow.ID>()
    @Environment(PeekModel.self) private var peek

    var body: some View {
        Table(of: HistoryRow.self, selection: $selection) {
            TableColumn("State") { Text($0.stateLabel) }.width(min: 56, ideal: 64)
            TableColumn("Outcome") { row in
                StatusBadge(status: row.entry.outcome).hoverPeek(row.id, popover(row), isAnchor: true, peek: peek)
            }
            .width(min: 90, ideal: 120)
            TableColumn("PR") { Text(verbatim: "#\($0.entry.number)").monospacedDigit() }.width(min: 56, ideal: 72)
            if showsProject {
                TableColumn("Project") { Text(ProjectSummary.shortName(of: $0.entry.repo)).lineLimit(1) }
                    .width(min: 60, ideal: 80)
            }
            TableColumn("Title") { row in
                Text(row.entry.title).lineLimit(1).hoverPeek(row.id, popover(row), peek: peek)
            }
            .width(min: 160)
            TableColumn("Rounds") { Text(verbatim: "\($0.entry.rounds)").monospacedDigit() }.width(56)
            TableColumn("Fixes pushed") { Text(verbatim: "\($0.entry.fixesPushed)").monospacedDigit() }.width(90)
            TableColumn("When") {
                Text($0.entry.at, format: .relative(presentation: .named)).foregroundStyle(.secondary)
            }
            .width(min: 80, ideal: 100)
        } rows: {
            ForEach(rows) { TableRow($0) }
        }
        .contextMenu(forSelectionType: HistoryRow.ID.self) { keys in
            let urls = urls(keys)
            Button("Open on GitHub") { open(urls) }.disabled(urls.isEmpty)
            Button("Copy Link") { copy(urls) }.disabled(urls.isEmpty)
            Divider()
            let focus = peekFocus(keys)
            Button("Show Findings", action: focus.toggle).keyboardShortcut("y").disabled(focus.id == nil)
        } primaryAction: { keys in
            open(urls(keys))
        }
        .onExitCommand { peek.dismiss() }
        .onKeyPress(.space) { peekFocus(selection).pressSpace() }
        .focusedSceneValue(\.peekFocus, peekFocus(selection))
    }

    private func popover(_ row: HistoryRow) -> FindingsPopover? {
        row.entry.findings.map { FindingsPopover(findings: $0, url: row.entry.url) }
    }

    private func peekFocus(_ keys: Set<HistoryRow.ID>) -> PeekFocus {
        let row = keys.count == 1 ? rows.first { keys.contains($0.id) } : nil
        return PeekFocus(model: peek, id: row?.entry.findings == nil ? nil : row?.id)
    }

    private func urls(_ keys: Set<HistoryRow.ID>) -> [URL] {
        rows.filter { keys.contains($0.id) }.map(\.entry.url)
    }

    private func open(_ urls: [URL]) {
        for url in urls { NSWorkspace.shared.open(url) }
    }

    private func copy(_ urls: [URL]) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(urls.map(\.absoluteString).joined(separator: "\n"), forType: .string)
    }
}
