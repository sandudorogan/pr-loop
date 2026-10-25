import PRWizardKit
import SwiftUI

@main
struct PRWizardApp: App {
    private static let socket =
        UserDefaults.standard.string(forKey: "socket") ?? DaemonLocation.socket.path(percentEncoded: false)

    @State private var store = QueueStore(daemon: DaemonClient(transport: UnixSocketTransport(path: socket)))

    var body: some Scene {
        Window("PR Wizard", id: "queue") {
            QueueWindow(socket: Self.socket)
                .environment(store)
                .task { store.start() }
        }
        .defaultSize(width: 1180, height: 640)
        .commands { QueueCommands(store: store) }
    }
}
