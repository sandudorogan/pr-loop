import PRWizardKit
import SwiftUI

struct RecentlyWorkedOn: View {
    let repo: String?
    @Binding var sidebar: SidebarSelection
    @Environment(QueueStore.self) private var store
    @Environment(HistoryStore.self) private var history

    private var title: String {
        repo.map { "Nothing in \(ProjectSummary.shortName(of: $0))" } ?? "Nothing in the queue"
    }

    var body: some View {
        let rows = history.entries(in: repo).map(HistoryRow.init)
        Group {
            if rows.isEmpty {
                plain
            } else {
                VStack(spacing: 16) {
                    header
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Recently worked on").font(.headline).padding(.horizontal)
                        HistoryTable(rows: rows, showsProject: repo == nil)
                    }
                }
                .padding(.top, 24)
            }
        }
        .task(id: Request(repo: repo, rev: store.snapshot?.rev)) {
            await history.show(repo: repo, rev: store.snapshot?.rev)
        }
    }

    @ViewBuilder private var plain: some View {
        if repo == nil {
            ContentUnavailableView(
                "Nothing in the queue", systemImage: "checkmark.seal",
                description: Text("Your open PRs and the ones that wait on your review show up here."))
        } else {
            ContentUnavailableView {
                Label(title, systemImage: "checkmark.seal")
            } actions: {
                Button("Show All Repos") { sidebar = .all }
            }
        }
    }

    private var header: some View {
        VStack(spacing: 4) {
            Label(title, systemImage: "checkmark.seal").font(.title2.weight(.semibold))
            if repo == nil {
                Text("Your open PRs and the ones that wait on your review show up here.").foregroundStyle(.secondary)
            } else {
                Button("Show All Repos") { sidebar = .all }
            }
        }
    }

    private struct Request: Hashable {
        let repo: String?
        let rev: String?
    }
}
