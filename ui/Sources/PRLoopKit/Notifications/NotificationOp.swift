public enum NotificationOp: Hashable, Sendable {
    case post(ReadyNotification)
    case remove(key: String)
}
