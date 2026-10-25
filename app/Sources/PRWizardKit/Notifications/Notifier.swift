public protocol Notifier: Sendable {
    func authorization() async -> NotificationAuthorization
    func requestAuthorization() async -> NotificationAuthorization
    func post(_ notification: ReadyNotification) async throws
    func removeDelivered(key: String) async
}
