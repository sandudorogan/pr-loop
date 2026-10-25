import PRWizardKit
import SwiftUI

struct ProjectSidebar: View {
    @Binding var selection: SidebarSelection
    @Environment(QueueStore.self) private var store

    var body: some View {
        List(
            selection: Binding {
                selection
            } set: {
                selection = $0 ?? .all
            }
        ) {
            Label("All repos", systemImage: "square.stack")
                .badge(store.snapshot?.counts.ready ?? 0)
                .tag(SidebarSelection.all)
            Section("Repos") {
                ForEach(store.projects) { ProjectRow(summary: $0).tag(SidebarSelection.repo($0.id)) }
            }
        }
        .listStyle(.sidebar)
        .navigationSplitViewColumnWidth(min: 180, ideal: 220)
    }
}
