import PRLoopKit
import UserNotifications

nonisolated struct UserNotificationsNotifier: Notifier {
    private var center: UNUserNotificationCenter { .current() }

    func authorization() async -> NotificationAuthorization {
        let settings = await center.notificationSettings()
        return switch settings.authorizationStatus {
        case .notDetermined: .notDetermined
        case .denied: .denied
        default: settings.alertStyle == .alert ? .authorized : .temporary
        }
    }

    func requestAuthorization() async -> NotificationAuthorization {
        _ = try? await center.requestAuthorization(options: [.alert, .badge])
        return await authorization()
    }

    func post(_ notification: ReadyNotification) async throws {
        let content = UNMutableNotificationContent()
        content.title = notification.title
        content.subtitle = notification.subtitle
        content.body = notification.body
        content.threadIdentifier = notification.key
        content.userInfo = ["url": notification.url.absoluteString, "key": notification.key]
        try await center.add(UNNotificationRequest(identifier: notification.id, content: content, trigger: nil))
    }

    func removeDelivered(key: String) async {
        let delivered = await center.deliveredNotifications().map(\.request)
        center.removeDeliveredNotifications(
            withIdentifiers: delivered.filter { $0.content.userInfo["key"] as? String == key }.map(\.identifier))
    }
}
