import PRLoopKit
import Testing

@MainActor @Suite struct HistoryStoreTests {
    private let gitops = "iprally/gitops"

    private func entries(_ repos: String...) throws -> Result<[HistoryEntry], any Error> {
        .success(try repos.map { try Snapshots.historyEntry(["repo": .string($0)]) })
    }

    @Test("show fetches the list with the limit and the repo")
    func fetches() async throws {
        let daemon = ScriptedDaemon(history: [try entries("iprally/iprally")])
        let store = HistoryStore(daemon: daemon, limit: 5)
        await store.show(repo: nil, rev: "a")
        #expect(store.entries.count == 1)
        #expect(await daemon.calls == [.history(repo: nil, limit: 5)])
    }

    @Test("the same repo and rev does not refetch")
    func cached() async throws {
        let daemon = ScriptedDaemon(history: [try entries("iprally/iprally"), try entries("iprally/iprally")])
        let store = HistoryStore(daemon: daemon)
        await store.show(repo: nil, rev: "a")
        await store.show(repo: nil, rev: "a")
        #expect(await daemon.calls.count == 1)
    }

    @Test("a new rev refetches")
    func revMoves() async throws {
        let daemon = ScriptedDaemon(history: [try entries("iprally/iprally"), try entries("iprally/iprally", gitops)])
        let store = HistoryStore(daemon: daemon)
        await store.show(repo: nil, rev: "a")
        await store.show(repo: nil, rev: "b")
        #expect(store.entries.count == 2)
        #expect(await daemon.calls.count == 2)
    }

    @Test("a new repo refetches with that repo")
    func repoMoves() async throws {
        let daemon = ScriptedDaemon(history: [try entries("iprally/iprally", gitops), try entries(gitops)])
        let store = HistoryStore(daemon: daemon)
        await store.show(repo: nil, rev: "a")
        await store.show(repo: gitops, rev: "a")
        #expect(await daemon.calls == [.history(repo: nil, limit: 20), .history(repo: gitops, limit: 20)])
        #expect(store.entries.count == 1)
    }

    @Test("entries(in:) hides other repos while a refetch runs")
    func filtered() async throws {
        let store = HistoryStore(daemon: ScriptedDaemon(history: [try entries("iprally/iprally", gitops)]))
        await store.show(repo: nil, rev: "a")
        #expect(store.entries(in: nil).count == 2)
        #expect(store.entries(in: gitops).map(\.repo) == [gitops])
    }

    @Test("a failed refetch for the same repo keeps the list and retries on the next rev")
    func failureKeepsList() async throws {
        let daemon = ScriptedDaemon(history: [
            try entries("iprally/iprally"), .failure(APIError.timeout), try entries(gitops),
        ])
        let store = HistoryStore(daemon: daemon)
        await store.show(repo: nil, rev: "a")
        await store.show(repo: nil, rev: "b")
        #expect(store.entries.map(\.repo) == ["iprally/iprally"])
        await store.show(repo: nil, rev: "b")
        #expect(store.entries.map(\.repo) == [gitops])
        #expect(await daemon.calls.count == 3)
    }

    @Test("a failed fetch for another repo clears the list")
    func failureClears() async throws {
        let daemon = ScriptedDaemon(history: [try entries("iprally/iprally"), .failure(APIError.down)])
        let store = HistoryStore(daemon: daemon)
        await store.show(repo: nil, rev: "a")
        await store.show(repo: gitops, rev: "a")
        #expect(store.entries.isEmpty)
        await store.show(repo: nil, rev: "a")
        #expect(await daemon.calls.count == 3)
    }
}
