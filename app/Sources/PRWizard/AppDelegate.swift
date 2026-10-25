import AppKit
import PRWizardKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    let socket =
        UserDefaults.standard.string(forKey: AppStorageKey.socket) ?? DaemonLocation.socket.path(percentEncoded: false)
    let store: QueueStore
    let history: HistoryStore

    override init() {
        let daemon = DaemonClient(transport: UnixSocketTransport(path: socket))
        store = QueueStore(daemon: daemon)
        history = HistoryStore(daemon: daemon)
        super.init()
    }

    func applicationWillFinishLaunching(_ notification: Notification) {
        UserDefaults.standard.register(defaults: [AppStorageKey.showsMenuBarExtra: true])
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        store.start()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        !UserDefaults.standard.bool(forKey: AppStorageKey.showsMenuBarExtra)
    }
}
