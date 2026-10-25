import PRWizardKit
import SwiftUI

@main
struct PRWizardApp: App {
    private static let socket =
        UserDefaults.standard.string(forKey: "socket") ?? DaemonLocation.socket.path(percentEncoded: false)

    @State private var store: QueueStore
    @State private var history: HistoryStore

    init() {
        let daemon = DaemonClient(transport: UnixSocketTransport(path: Self.socket))
        _store = State(initialValue: QueueStore(daemon: daemon))
        _history = State(initialValue: HistoryStore(daemon: daemon))
    }

    var body: some Scene {
        Window("PR Wizard", id: "queue") {
            QueueWindow(socket: Self.socket)
                .environment(store)
                .environment(history)
                .task { store.start() }
        }
        .defaultSize(width: 1180, height: 640)
        .commands { QueueCommands(store: store) }
    }
}
