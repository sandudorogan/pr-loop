import Foundation
import PRWizardKit
import Testing

@MainActor @Suite struct LanesSettingsTests {
    private func loaded() async throws -> SettingsStore {
        let store = SettingsStore(daemon: ScriptedDaemon(config: [.success(try Settings.envelope())]))
        await store.load()
        return store
    }

    @Test("the layout follows the draft at once, and a project reads its own lanes")
    func layoutFollowsDraft() async throws {
        let store = try await loaded()
        let projects = try Snapshots.queue().projects
        #expect(store.lanesLayout(in: Settings.gitops, projects: projects).review == .laneOff)
        #expect(store.lanesLayout(in: Settings.gitops, projects: projects).fix == .sharedPool)
        store.set("lanes.separate", to: true, in: .allRepos)
        #expect(store.lanesLayout(in: Settings.gitops, projects: projects).fix == .stepper)
        #expect(store.lanesLayout(in: .allRepos, projects: projects).showsTotals)
        store.set("review.enabled", to: true, in: Settings.gitops)
        #expect(store.lanesLayout(in: Settings.gitops, projects: projects).review == .stepper)
    }

    @Test("a number shows in its unit and writes back in seconds")
    func units() async throws {
        let store = try await loaded()
        #expect(store.int("review.timeout_s", in: .allRepos, per: 60) == 45)
        store.setInt("review.timeout_s", to: 30, in: .allRepos, per: 60)
        #expect(store.resolve("review.timeout_s", in: .allRepos).value == 1800)
        #expect(store.patch == ["review": ["timeout_s": 1800]])
    }

    @Test("a project list overrides whole and comes back with Use Default")
    func lists() async throws {
        let store = try await loaded()
        let defaults = store.strings("review.trivial", in: .allRepos)
        #expect(!defaults.isEmpty)
        store.setUsesDefault(false, for: "review.trivial", in: Settings.gitops)
        #expect(store.strings("review.trivial", in: Settings.gitops) == defaults)
        store.setStrings("review.trivial", to: defaults + ["*.snap"], in: Settings.gitops)
        #expect(store.draft.isOverridden("review.trivial", in: Settings.gitops))
        store.setUsesDefault(true, for: "review.trivial", in: Settings.gitops)
        #expect(store.strings("review.trivial", in: Settings.gitops) == defaults)
    }

    @Test("a list's summary shows the first entries and an ellipsis")
    func summary() {
        #expect(ListSummary.line(["*.lock", "*.md"]) == "*.lock  *.md")
        #expect(ListSummary.line(["a", "b", "c", "d", "e"]) == "a  b  c  d  …")
        #expect(ListSummary.line([]) == "")
    }

    @Test("an error on a list element belongs to the list's row")
    func elementErrors() throws {
        let json = """
            [{"path": "review.trivial[2]", "message": "must be a glob"},
             {"path": "review.trivial", "message": "at most 50"},
             {"path": "review.trivialize", "message": "unrelated"}]
            """
        let errors = FieldErrors(try JSONDecoder().decode([APIErrorBody.Problem].self, from: Data(json.utf8)))
        #expect(errors.messages(within: "review.trivial", in: .allRepos) == ["must be a glob", "at most 50"])
    }
}
