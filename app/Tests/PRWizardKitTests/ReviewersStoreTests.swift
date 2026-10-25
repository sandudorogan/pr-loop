import Foundation
import PRWizardKit
import Testing

@MainActor @Suite struct ReviewersStoreTests {
    private let iprally = SettingsScope.project("iprally/iprally")

    private func loaded() async throws -> SettingsStore {
        let store = SettingsStore(daemon: ScriptedDaemon(config: [.success(try Settings.envelope())]))
        await store.load()
        return store
    }

    private func ids(_ store: SettingsStore, _ scope: SettingsScope = .allRepos) -> [String] {
        store.reviewers(in: scope).map(\.id)
    }

    @Test("add appends a copy of the selected reviewer with the next free id")
    func add() async throws {
        let store = try await loaded()
        #expect(store.addReviewer(copying: 0, in: .allRepos) == 3)
        #expect(store.addReviewer(copying: 0, in: .allRepos) == 4)
        #expect(ids(store) == ["opus", "codex", "quality", "opus-2", "opus-3"])
        let copy = store.reviewers(in: .allRepos)[3]
        #expect(copy.label == "Claude Opus 5.5 copy")
        #expect(copy.claude == store.reviewers(in: .allRepos)[0].claude)
    }

    @Test("duplicate puts the copy right after its source")
    func duplicate() async throws {
        let store = try await loaded()
        #expect(store.duplicateReviewer(at: 1, in: .allRepos) == 2)
        store.duplicateReviewer(at: 2, in: .allRepos)
        #expect(ids(store) == ["opus", "codex", "codex-2", "codex-2-2", "quality"])
    }

    @Test("a copied id stays within the daemon's 32 characters")
    func longID() async throws {
        let store = try await loaded()
        let long = String(repeating: "a", count: 32)
        store.updateReviewer(at: 0, in: .allRepos) { $0.id = long }
        store.duplicateReviewer(at: 0, in: .allRepos)
        #expect(ids(store)[1] == String(repeating: "a", count: 30) + "-2")
    }

    @Test("the list holds eight reviewers at most")
    func maximum() async throws {
        let store = try await loaded()
        for _ in 0..<5 { store.addReviewer(copying: 0, in: .allRepos) }
        #expect(store.reviewers(in: .allRepos).count == 8)
        #expect(!store.canAddReviewer(in: .allRepos))
    }

    @Test("remove keeps the last enabled reviewer")
    func remove() async throws {
        let store = try await loaded()
        store.updateReviewer(at: 1, in: .allRepos) { $0.isEnabled = false }
        store.removeReviewer(at: 2, in: .allRepos)
        #expect(ids(store) == ["opus", "codex"])
        #expect(!store.canRemoveReviewer(at: 0, in: .allRepos))
        #expect(store.canRemoveReviewer(at: 1, in: .allRepos))
        store.removeReviewer(at: 1, in: .allRepos)
        #expect(!store.canRemoveReviewer(at: 0, in: .allRepos))
    }

    @Test(
        "move reorders and returns where the dragged reviewer landed",
        arguments: [
            (IndexSet([0]), 3, ["codex", "quality", "opus"], 2),
            (IndexSet([2]), 0, ["quality", "opus", "codex"], 0),
            (IndexSet([0]), 1, ["opus", "codex", "quality"], 0),
            (IndexSet([0, 1]), 3, ["quality", "opus", "codex"], 1),
        ])
    func move(offsets: IndexSet, destination: Int, order: [String], landing: Int) async throws {
        let store = try await loaded()
        #expect(store.moveReviewers(fromOffsets: offsets, toOffset: destination, in: .allRepos) == landing)
        #expect(ids(store) == order)
    }

    @Test("an edit in a project scope writes the whole list into that override only")
    func projectEdit() async throws {
        let store = try await loaded()
        store.setUsesDefault(false, for: "review.reviewers", in: iprally)
        store.updateReviewer(at: 2, in: iprally) { $0.needsConventions = false }
        #expect(store.reviewers(in: iprally)[2].needsConventions == false)
        #expect(store.reviewers(in: .allRepos)[2].needsConventions)
        let sent = try #require(store.patch?[["projects", "iprally/iprally", "review", "reviewers"]])
        #expect(try sent.decoded([ReviewerConfig].self) == store.reviewers(in: iprally))
        #expect(store.patch?[["review"]] == nil)
    }

    @Test("Use the default reviewers restores the defaults and drops the custom list")
    func restore() async throws {
        let store = try await loaded()
        store.setUsesDefault(false, for: "review.reviewers", in: iprally)
        store.removeReviewer(at: 1, in: iprally)
        #expect(ids(store, iprally) == ["opus", "quality"])
        store.setUsesDefault(true, for: "review.reviewers", in: iprally)
        #expect(ids(store, iprally) == ["opus", "codex", "quality"])
        #expect(!store.draft.isOverridden("review.reviewers", in: iprally))
        #expect(!store.isDirty)
    }

    @Test("a lighter run starts from the full run's model and effort, and off drops it")
    func incremental() async throws {
        let store = try await loaded()
        store.updateReviewer(at: 2, in: .allRepos) { $0.claude.hasIncremental = true }
        let quality = store.reviewers(in: .allRepos)[2].claude
        #expect(quality.incremental?.model == "haiku")
        #expect(quality.incremental?.effort == "xhigh")
        store.updateReviewer(at: 0, in: .allRepos) { $0.claude.hasIncremental = false }
        #expect(store.reviewers(in: .allRepos)[0].claude.incremental == nil)
    }
}
