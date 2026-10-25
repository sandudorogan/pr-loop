import PRWizardKit
import Testing

@MainActor @Suite struct ScopeOptionTests {
    private func options(_ patch: [String: JSONValue] = [:], at index: Int = 0) async throws -> [ScopeOption] {
        let store = SettingsStore(daemon: ScriptedDaemon(config: [.success(try Settings.envelope())]))
        await store.load()
        let snapshot = try Snapshots.queue()
        let projects = try snapshot.projects.indices.map { try Snapshots.project($0, $0 == index ? patch : [:]) }
        return store.scopeOptions(for: projects.map { ProjectSummary($0, in: snapshot) })
    }

    @Test("All repos comes first, then each project in snapshot order")
    func order() async throws {
        #expect(try await options().map(\.title) == ["All repos"] + Snapshots.queue().projects.map(\.repo))
    }

    @Test("a project reads its lanes and override count")
    func detail() async throws {
        let details = try await options().map(\.detail)
        #expect(details[0] == "defaults")
        #expect(details[1] == "review · fix · 1 override")
        #expect(details[2] == "fix only · 1 override")
        #expect(details[3] == "review · fix · no overrides")
    }

    @Test("a project with no checkout is disabled and says where to clone it")
    func noCheckout() async throws {
        let option = try #require(try await options().last)
        #expect(!option.isEnabled)
        #expect(option.detail == "unavailable: no local checkout")
        #expect(option.help == "Clone it into one of: ~/workdir")
    }

    @Test("a project with a checkout error stays enabled and carries the error")
    func error() async throws {
        let option = try await options(["status": "error", "error": "not a checkout of iprally/iprally"])[1]
        #expect(option.isEnabled)
        #expect(option.detail == "checkout error · 1 override")
        #expect(option.problem == "not a checkout of iprally/iprally")
    }
}
