import AppKit
import PRLoopKit
import SwiftUI

struct MenuBarContent: View {
    @Environment(QueueStore.self) private var store
    @Environment(\.openSettings) private var openSettings
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        switch MenuItems.top(5, in: store.phase) {
        case .connecting:
            Button("Connecting to PR Loop…") {}.disabled(true)
        case .down:
            Button("PR Loop daemon is not running") {}.disabled(true)
            Button("Start Daemon") { Task { await store.startDaemon(with: ProcessDaemonLauncher()) } }
                .disabled(store.pendingActions.contains(.startDaemon))
        case .incompatible(let api):
            Button("The daemon speaks API v\(api). Update PR Loop.app.") {}.disabled(true)
        case .empty:
            Button("Nothing in the queue") {}.disabled(true)
        case .top(let rows):
            ForEach(rows) { row in
                Button {
                    NSWorkspace.shared.open(row.url)
                } label: {
                    Label {
                        Text(verbatim: row.text)
                    } icon: {
                        Image(systemName: row.symbol)
                    }
                }
            }
        }
        Divider()
        Button("Open PR Loop") {
            NSApp.activate()
            openWindow(id: "queue")
        }
        .keyboardShortcut("o")
        Button("Settings…") {
            NSApp.activate()
            openSettings()
        }
        .keyboardShortcut(",")
        Divider()
        Button("Quit PR Loop") { NSApp.terminate(nil) }
            .keyboardShortcut("q")
    }
}
