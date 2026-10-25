public enum PendingAction: Hashable, Sendable {
    case refresh
    case setPaused(Bool)
    case moveToFront(PRRef)
    case review(PRRef)
    case fix(PRRef)
}
