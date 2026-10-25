public protocol EventCursor: Sendable {
    func lastSeen() -> String?
    func save(_ cursor: String)
}
