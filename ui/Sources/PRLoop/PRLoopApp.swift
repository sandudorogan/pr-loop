import SwiftUI

@main
struct PRLoopApp: App {
    @NSApplicationDelegateAdaptor private var delegate: AppDelegate
    @AppStorage(AppStorageKey.showsMenuBarExtra) private var showsMenuBarExtra = true

    var body: some Scene {
        Window("PR Loop", id: "queue") {
            QueueWindow(socket: delegate.socket)
                .environment(delegate.store)
                .environment(delegate.history)
                .environment(delegate.settings)
                .environment(delegate.prSettings)
        }
        .defaultSize(width: 1180, height: 640)
        .commands { QueueCommands(store: delegate.store) }
        Settings {
            SettingsView()
                .environment(delegate.store)
                .environment(delegate.settings)
                .environment(delegate.notifications)
        }
        MenuBarExtra("PR Loop", systemImage: "arrow.triangle.2.circlepath", isInserted: $showsMenuBarExtra) {
            MenuBarContent().environment(delegate.store)
        }
        .menuBarExtraStyle(.menu)
    }
}
