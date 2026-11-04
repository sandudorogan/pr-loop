import AppKit
import PRLoopKit
import SwiftUI

struct QueueWindow: View {
    let socket: String
    @Environment(QueueStore.self) private var store
    @SceneStorage("sidebar") private var sidebar = SidebarSelection.all
    @SceneStorage("columns") private var columns = TableColumnCustomization<QueueItem>()
    @SceneStorage("inspector") private var showsInspector = false
    @SceneStorage("sidebarShown") private var showsSidebar = true
    @SceneStorage("inspectorTab") private var inspectorTab = PRInspector.Tab.status
    @SceneStorage("inspectorWidth") private var inspectorWidth = 320.0
    @State private var detailWidth: CGFloat = 0
    @State private var selection = Set<QueueItem.ID>()
    @State private var search = ""
    @State private var peek = PeekModel()

    private var filter: QueueFilter { QueueFilter(repo: sidebar.repo, text: search) }
    private var sections: [QueueSection] { filter.sections(store.snapshot?.items ?? []) }

    var body: some View {
        NavigationSplitView(columnVisibility: columnVisibility) {
            ProjectSidebar(selection: $sidebar)
                .toolbar(removing: .sidebarToggle)
                .toolbar { ToolbarItem { sidebarToggle } }
        } detail: {
            HStack(spacing: 0) {
                detail.frame(minWidth: 360, maxWidth: .infinity, maxHeight: .infinity)
                if showsInspector {
                    ResizeHandle(width: $inspectorWidth, range: inspectorRange)
                    PRInspector(items: selected, tab: $inspectorTab).frame(width: CGFloat(inspectorWidth))
                }
            }
            .onGeometryChange(for: CGFloat.self, of: \.size.width) { detailWidth = $0 }
            .safeAreaInset(edge: .bottom) { banner }
        }
        .navigationTitle("PR Loop")
        .navigationSubtitle(subtitle)
        .toolbar {
            QueueToolbar(
                store: store, repo: sidebar.repo, items: selected, showsInspector: $showsInspector, search: $search)
        }
        .focusedSceneValue(
            \.queueFocus,
            QueueFocus(
                items: selected, sidebar: $sidebar, showsInspector: $showsInspector,
                showSettings: { showSettings(selection) }, focusFilter: { NSApp.keyWindow?.focusToolbarField() })
        )
        .environment(peek)
        .frame(minWidth: minWidth, minHeight: 400)
        .onChange(of: selection) { _, keys in
            if !keys.isEmpty { showsInspector = true }
        }
    }

    private var sidebarToggle: some View {
        Button {
            showsSidebar.toggle()
        } label: {
            Label("Sidebar", systemImage: showsSidebar ? "rectangle.leadingthird.inset.filled" : "sidebar.leading")
        }
        .help(showsSidebar ? "Hide the sidebar" : "Show the sidebar")
    }

    /// The inspector and its 1 pt divider never squeeze the table below its minimum.
    private var inspectorRange: ClosedRange<Double> {
        280...max(280, Double(detailWidth - QueueTable.minWidth - 1))
    }

    /// SwiftUI drops a minimum on the detail column (it runs under the sidebar), so the window
    /// carries it: the sidebar (220 plus its 8 pt inset), the table and the docked inspector column (its width plus
    /// its 1 pt divider). Opening the inspector in a narrower window grows the window, and the table never scrolls sideways.
    private var minWidth: CGFloat {
        max(820, (showsSidebar ? 228 : 0) + QueueTable.minWidth + (showsInspector ? CGFloat(inspectorWidth) + 1 : 0))
    }

    private var columnVisibility: Binding<NavigationSplitViewVisibility> {
        Binding {
            showsSidebar ? .all : .detailOnly
        } set: {
            showsSidebar = $0 != .detailOnly
        }
    }

    @ViewBuilder private var detail: some View {
        if sections.isEmpty {
            EmptyStateView(filter: filter, socket: socket, sidebar: $sidebar)
        } else {
            QueueTable(
                sections: sections, showsProject: sidebar == .all, selection: $selection, columns: $columns,
                showSettings: { showSettings([$0]) }
            )
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

    private func showSettings(_ keys: Set<QueueItem.ID>) {
        selection = keys
        showsInspector = true
        inspectorTab = .settings
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
