import AppKit
import PRWizardKit
import SwiftUI

struct HistoryTable: View {
    let rows: [HistoryRow]
    let showsProject: Bool
    @State private var selection = Set<HistoryRow.ID>()

    var body: some View {
        Table(of: HistoryRow.self, selection: $selection) {
            TableColumn("State") { Text($0.stateLabel) }.width(min: 56, ideal: 64)
            TableColumn("Outcome") { StatusBadge(status: $0.entry.outcome) }.width(min: 90, ideal: 120)
            TableColumn("PR") { Text(verbatim: "#\($0.entry.number)").monospacedDigit() }.width(min: 56, ideal: 72)
            if showsProject {
                TableColumn("Project") { Text(ProjectSummary.shortName(of: $0.entry.repo)).lineLimit(1) }
                    .width(min: 60, ideal: 80)
            }
            TableColumn("Title") { Text($0.entry.title).lineLimit(1).truncationMode(.middle) }.width(min: 160)
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
        } primaryAction: { keys in
            open(urls(keys))
        }
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
