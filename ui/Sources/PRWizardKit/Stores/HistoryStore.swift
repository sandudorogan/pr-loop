import Observation

@MainActor @Observable public final class HistoryStore {
    public private(set) var entries: [HistoryEntry] = []

    private struct Request: Hashable {
        let repo: String?
        let rev: String?
    }

    private let daemon: any DaemonAPI
    private let limit: Int
    private var loaded: Request?

    public init(daemon: any DaemonAPI, limit: Int = 20) {
        self.daemon = daemon
        self.limit = limit
    }

    public func entries(in repo: String?) -> [HistoryEntry] {
        entries.filter { repo == nil || $0.repo == repo }
    }

    public func show(repo: String?, rev: String?) async {
        let request = Request(repo: repo, rev: rev)
        guard request != loaded else { return }
        do {
            let fetched = try await daemon.history(repo: repo, limit: limit)
            guard !Task.isCancelled else { return }
            entries = fetched
            loaded = request
        } catch {
            guard !Task.isCancelled, loaded?.repo != repo else { return }
            entries = []
            loaded = nil
        }
    }
}
