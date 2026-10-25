import SwiftUI

@main
struct PRWizardApp: App {
    @NSApplicationDelegateAdaptor private var delegate: AppDelegate
    @AppStorage(AppStorageKey.showsMenuBarExtra) private var showsMenuBarExtra = true

    var body: some Scene {
        Window("PR Wizard", id: "queue") {
            QueueWindow(socket: delegate.socket)
                .environment(delegate.store)
                .environment(delegate.history)
        }
        .defaultSize(width: 1180, height: 640)
        .commands { QueueCommands(store: delegate.store) }
        Settings {
            SettingsView().environment(delegate.store).environment(delegate.settings)
        }
        MenuBarExtra("PR Wizard", systemImage: "wand.and.stars", isInserted: $showsMenuBarExtra) {
            MenuBarContent().environment(delegate.store)
        }
        .menuBarExtraStyle(.menu)
    }
}
