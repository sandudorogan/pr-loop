public protocol DaemonAPI: Sendable {
    func info() async throws -> DaemonInfo
    func queue(since rev: String?, wait: Duration) async throws -> QueueSnapshot
    func events(since cursor: String?, wait: Duration) async throws -> EventPage
    func history(repo: String?, limit: Int) async throws -> [HistoryEntry]
    func refresh() async throws
    func moveToFront(_ prs: [PRRef]) async throws -> NextResult
    func review(_ pr: PRRef) async throws
    func fix(_ pr: PRRef) async throws
    func setPaused(_ paused: Bool) async throws -> Bool
}
