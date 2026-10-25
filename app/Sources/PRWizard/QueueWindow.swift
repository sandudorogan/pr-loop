import PRWizardKit
import SwiftUI

struct QueueWindow: View {
    let socket: String
    @Environment(QueueStore.self) private var store
    @SceneStorage("sidebar") private var sidebar = SidebarSelection.all
    @SceneStorage("columns") private var columns = TableColumnCustomization<QueueItem>()
    @SceneStorage("inspector") private var showsInspector = false
    @State private var selection = Set<QueueItem.ID>()
    @State private var search = ""

    private var filter: QueueFilter { QueueFilter(repo: sidebar.repo, text: search) }
    private var sections: [QueueSection] { filter.sections(store.snapshot?.items ?? []) }

    var body: some View {
        NavigationSplitView {
            ProjectSidebar(selection: $sidebar)
        } detail: {
            detail
                .inspector(isPresented: $showsInspector) {
                    PRInspector(items: selected)
                        .inspectorColumnWidth(min: 260, ideal: 320)
                }
                .safeAreaInset(edge: .bottom) { banner }
        }
        .navigationTitle("PR Wizard")
        .navigationSubtitle(subtitle)
        .searchable(text: $search, placement: .toolbar, prompt: "Filter")
        .toolbar { QueueToolbar(store: store, repo: sidebar.repo, showsInspector: $showsInspector) }
        .focusedSceneValue(
            \.queueFocus, QueueFocus(items: selected, sidebar: $sidebar, showsInspector: $showsInspector)
        )
        .frame(minWidth: 820, minHeight: 400)
    }

    @ViewBuilder private var detail: some View {
        if sections.isEmpty {
            EmptyStateView(filter: filter, socket: socket, sidebar: $sidebar)
        } else {
            QueueTable(sections: sections, showsProject: sidebar == .all, selection: $selection, columns: $columns)
                .opacity(store.phase.isDisconnected ? 0.5 : 1)
        }
    }

    @ViewBuilder private var banner: some View {
        if let failure = store.lastActionError {
            Label(failure.message, systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(Tone.attention.color)
                .padding(8)
                .frame(maxWidth: .infinity)
                .background(.bar)
        }
    }

    private var selected: [QueueItem] {
        sections.flatMap(\.items).filter { selection.contains($0.id) }
    }

    private var subtitle: String {
        let scope =
            sidebar.repo.map { repo in store.projects.first { $0.id == repo }.map { "\(repo) · \($0.laneLine)" } ?? repo
            }
            ?? "All repos"
        guard let fetched = store.snapshot?.fetchedAt else { return scope }
        return "\(scope) · fetched \(fetched.formatted(date: .omitted, time: .shortened))"
    }
}
