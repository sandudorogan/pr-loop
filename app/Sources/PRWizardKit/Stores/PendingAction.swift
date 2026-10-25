public enum PendingAction: Hashable, Sendable {
    case refresh
    case startDaemon
    case setPaused(Bool)
    case moveToFront(PRRef)
    case review(PRRef)
    case fix(PRRef)
    case pause(PRRef)
}
