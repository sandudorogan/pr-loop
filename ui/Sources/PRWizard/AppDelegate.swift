import AppKit
import PRWizardKit
import UserNotifications

final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let socket =
        UserDefaults.standard.string(forKey: AppStorageKey.socket) ?? DaemonLocation.socket.path(percentEncoded: false)
    let store: QueueStore
    let history: HistoryStore
    let settings: SettingsStore
    let prSettings: PRSettingsStore
    let notifications: ReadyNotifications

    override init() {
        let daemon = DaemonClient(transport: UnixSocketTransport(path: socket))
        store = QueueStore(daemon: daemon)
        history = HistoryStore(daemon: daemon, limit: 200)
        settings = SettingsStore(daemon: daemon)
        prSettings = PRSettingsStore(daemon: daemon)
        notifications = ReadyNotifications(
            daemon: daemon, notifier: UserNotificationsNotifier(), cursor: DefaultsEventCursor(),
            isEnabled: { UserDefaults.standard.bool(forKey: AppStorageKey.notifiesReady) })
        super.init()
    }

    func applicationWillFinishLaunching(_ notification: Notification) {
        UserDefaults.standard.register(defaults: [
            AppStorageKey.showsMenuBarExtra: true, AppStorageKey.notifiesReady: true,
        ])
        UNUserNotificationCenter.current().delegate = self
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        store.start()
        notifications.start()
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        Task { await notifications.authorize() }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        !UserDefaults.standard.bool(forKey: AppStorageKey.showsMenuBarExtra)
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .list]
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse
    ) async {
        guard let url = (response.notification.request.content.userInfo["url"] as? String).flatMap(URL.init) else {
            return
        }
        NSWorkspace.shared.open(url)
    }
}
