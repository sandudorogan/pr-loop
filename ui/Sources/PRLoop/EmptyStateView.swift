import PRLoopKit
import SwiftUI

struct EmptyStateView: View {
    let filter: QueueFilter
    let socket: String
    @Binding var sidebar: SidebarSelection
    @Environment(QueueStore.self) private var store

    var body: some View {
        switch store.phase {
        case .idle, .connecting:
            ProgressView("Connecting to PR Loop…")
        case .down(let error, _):
            ContentUnavailableView {
                Label("PR Loop is not running", systemImage: "bolt.horizontal.circle")
            } description: {
                Text(verbatim: (error as? APIError) == .down ? "Nothing answers on \(socket)." : "\(socket): \(error)")
            } actions: {
                Button("Start Daemon") { Task { await store.startDaemon(with: ProcessDaemonLauncher()) } }
                    .disabled(store.pendingActions.contains(.startDaemon))
                Button("Retry") { store.retry() }
            }
        case .incompatible(let api):
            ContentUnavailableView(
                "Update PR Loop.app", systemImage: "arrow.triangle.2.circlepath",
                description: Text("The daemon speaks API v\(api). This app speaks v1."))
        case .live, .stale:
            if !filter.query.isEmpty {
                ContentUnavailableView.search(text: filter.query)
            } else {
                RecentlyWorkedOn(repo: filter.repo, sidebar: $sidebar)
            }
        }
    }
}
