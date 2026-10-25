import PRWizardKit
import Testing

@MainActor @Suite struct WorkerTotalsTests {
    private let gitops = Settings.gitops

    private func totals(_ edit: (SettingsStore) -> Void = { _ in }, projects: [Project]? = nil) async throws
        -> WorkerTotals
    {
        let store = SettingsStore(daemon: ScriptedDaemon(config: [.success(try Settings.envelope())]))
        await store.load()
        edit(store)
        return store.workerTotals(projects: try projects ?? Snapshots.queue().projects)
    }

    @Test("shared pools are one of each, whatever the projects hold")
    func shared() async throws {
        let totals = try await totals { $0.set("fix.workers", to: 1, in: .project("iprally/iprally")) }
        #expect((totals.reviews, totals.fixes) == (3, 3))
        #expect(!totals.isOverLimit)
    }

    @Test("separate pools sum every project with a checkout and that lane on")
    func separate() async throws {
        let totals = try await totals { $0.set("lanes.separate", to: true, in: .allRepos) }
        #expect((totals.reviews, totals.fixes) == (6, 9))
        #expect(totals.isOverLimit)
        #expect(totals.summary == "Machine total: 6 reviews, 9 fix passes at once (above 8).")
    }

    @Test("a project override moves the total, and the warning goes away at 8")
    func override() async throws {
        let totals = try await totals {
            $0.set("lanes.separate", to: true, in: .allRepos)
            $0.set("fix.workers", to: 2, in: Settings.gitops)
        }
        #expect((totals.reviews, totals.fixes) == (6, 8))
        #expect(totals.summary == "Machine total: 6 reviews, 8 fix passes at once.")
    }

    @Test("a project with a checkout error runs no pool")
    func errorProject() async throws {
        let projects = try [Snapshots.project(0), Snapshots.project(2, ["status": "error", "available": false])]
        let totals = try await totals({ $0.set("lanes.separate", to: true, in: .allRepos) }, projects: projects)
        #expect((totals.reviews, totals.fixes) == (3, 3))
    }

    @Test("one pass reads in the singular")
    func singular() async throws {
        let totals = try await totals {
            $0.set("review.workers", to: 1, in: .allRepos)
            $0.set("fix.workers", to: 1, in: .allRepos)
        }
        #expect(totals.summary == "Machine total: 1 review, 1 fix pass at once.")
    }
}
