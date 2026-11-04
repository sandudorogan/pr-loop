import AppKit
import PRLoopKit
import SwiftUI

struct QueueCommands: Commands {
    let store: QueueStore
    @FocusedValue(\.queueFocus) private var focus
    @FocusedValue(\.peekFocus) private var peek

    var body: some Commands {
        SidebarCommands()
        CommandGroup(replacing: .textEditing) {
            Button("Filter") { focus?.focusFilter() }
                .keyboardShortcut("f")
                .disabled(focus == nil)
        }
        CommandGroup(after: .sidebar) {
            Button(focus?.showsInspector.wrappedValue == true ? "Hide Inspector" : "Show Inspector") {
                focus?.showsInspector.wrappedValue.toggle()
            }
            .keyboardShortcut("i", modifiers: [.command, .option])
            .disabled(focus == nil)
            Divider()
            Button("Refresh") { Task { await store.refresh() } }
                .keyboardShortcut("r")
                .disabled(store.snapshot == nil || store.isRefreshing)
            Divider()
            Button("All Repos") { focus?.sidebar.wrappedValue = .all }
                .keyboardShortcut("0")
                .disabled(focus == nil)
            ForEach(Array(store.projects.prefix(9).enumerated()), id: \.element.id) { index, project in
                Button(project.project.repo) { focus?.sidebar.wrappedValue = .repo(project.id) }
                    .keyboardShortcut(KeyEquivalent(Character("\(index + 1)")))
                    .disabled(focus == nil)
            }
        }
        CommandMenu("Pull Request") {
            PullRequestMenu(items: focus?.items ?? [], store: store, peek: peek, showSettings: focus?.showSettings)
        }
        CommandMenu("Daemon") {
            let isPaused = store.snapshot?.isPaused == true
            Button(isPaused ? "Resume" : "Pause") { Task { await store.setPaused(!isPaused) } }
                .keyboardShortcut("p", modifiers: [.command, .option])
                .disabled(store.snapshot == nil)
            Button("Start Daemon") { Task { await store.startDaemon(with: ProcessDaemonLauncher()) } }
                .disabled(!store.phase.isDisconnected || store.pendingActions.contains(.startDaemon))
            Button("Open Log") { openLog() }
                .disabled(store.info == nil)
        }
    }

    private func openLog() {
        guard let log = store.info?.paths.log else { return }
        NSWorkspace.shared.open(URL(filePath: log))
    }
}
