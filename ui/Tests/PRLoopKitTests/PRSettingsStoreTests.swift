import Foundation
import PRLoopKit
import Testing

@MainActor @Suite struct PRSettingsStoreTests {
    private let pr = PRConfigs.pr

    private func store(_ responses: Result<PRConfig, any Error>...) async throws -> (PRSettingsStore, ScriptedDaemon) {
        let daemon = ScriptedDaemon(prConfig: [.success(try PRConfigs.config())] + responses)
        let store = PRSettingsStore(daemon: daemon)
        await store.show(pr)
        return (store, daemon)
    }

    @Test("show loads the PR's config and its markers")
    func loads() async throws {
        let (store, daemon) = try await store()
        #expect(store.config?.rev == "2e8fe284ec8f")
        #expect(store.markers?.source(of: "review.reviewers") == .pr)
        #expect(await daemon.calls == [.prConfig(pr)])
    }

    @Test("each change is one PATCH of that path against the last rev, and the response replaces the config")
    func livePatch() async throws {
        let skipped = try PRConfigs.config(merging: ["rev": "aaaaaaaaaaaa", "layers": ["pr": ["fix.enabled"]]])
        let (store, daemon) = try await store(.success(skipped))
        await store.set("fix.enabled", to: false)
        #expect(await daemon.calls.last == .patchPRConfig(pr, ["fix": ["enabled": false]], baseRev: "2e8fe284ec8f"))
        #expect(store.markers?.source(of: "fix.enabled") == .pr)
        #expect(store.config?.rev == "aaaaaaaaaaaa")
    }

    @Test("a null picks the built-in default over the project: a PUT of the override that keeps the null")
    func explicitNull() async throws {
        let (store, daemon) = try await store(.success(try PRConfigs.config()))
        let reviewers = try #require(store.config?.override?[["review", "reviewers"]])
        await store.set("fix.model", to: .null)
        #expect(
            await daemon.calls.last
                == .putPRConfig(
                    pr, ["review": ["reviewers": reviewers], "fix": ["model": .null]], baseRev: "2e8fe284ec8f"))
    }

    @Test("Use Default patches each path to null")
    func useDefault() async throws {
        let (store, daemon) = try await store(.success(try PRConfigs.cleared()))
        await store.useDefault(["review.reviewers", "fix.model"])
        #expect(
            await daemon.calls.last
                == .patchPRConfig(
                    pr, ["fix": ["model": .null], "review": ["reviewers": .null]], baseRev: "2e8fe284ec8f")
        )
    }

    @Test("a reviewer change sends the whole effective list, edited, since lists replace whole")
    func listCopy() async throws {
        let (store, daemon) = try await store(.success(try PRConfigs.config()))
        var reviewers = try #require(store.config?.effective.review.reviewers)
        reviewers[0].claude.effort = "max"
        await store.setReviewers(reviewers)
        let list = try JSONValue(encoding: reviewers)
        #expect(await daemon.calls.last == .patchPRConfig(pr, ["review": ["reviewers": list]], baseRev: "2e8fe284ec8f"))
    }

    @Test("Use Default for the whole PR sends DELETE and shows the cleared config")
    func delete() async throws {
        let (store, daemon) = try await store(.success(try PRConfigs.cleared()))
        await store.useDefaults()
        #expect(await daemon.calls.last == .deletePRConfig(pr))
        #expect(store.config?.override == nil)
        #expect(store.markers?.overridden == [])
    }

    @Test("a 412 reloads and says so; the change is not retried")
    func stale() async throws {
        let fresh = try PRConfigs.config(merging: ["rev": "bbbbbbbbbbbb"])
        let (store, daemon) = try await store(
            .failure(Settings.rejected(412, "stale_config")), .success(fresh))
        await store.set("review.enabled", to: false)
        #expect(store.wasReloaded)
        #expect(store.config?.rev == "bbbbbbbbbbbb")
        #expect(await daemon.calls.count == 3)
        #expect(await daemon.calls.last == .prConfig(pr))
    }

    @Test("a 422 keeps the config and shows each problem at its control")
    func invalid() async throws {
        let json = #"[{"path": "review.reviewers[0].codex.model", "message": "must be a string"}]"#
        let problems = try JSONDecoder().decode([APIErrorBody.Problem].self, from: Data(json.utf8))
        let (store, _) = try await store(.failure(Settings.rejected(422, "invalid_config", problems)))
        await store.set("review.reviewers", to: [])
        #expect(store.messages(at: "review.reviewers") == ["must be a string"])
        #expect(store.messages(at: "fix.model") == [])
        #expect(store.config?.rev == "2e8fe284ec8f")
    }

    @Test("a PR that left the queue reads as gone", arguments: ["not_in_queue", "unknown_repo"])
    func gone(code: String) async throws {
        let (store, _) = try await store(.failure(Settings.rejected(404, code)))
        await store.set("fix.enabled", to: false)
        #expect(store.isGone)
        #expect(store.config == nil)
    }

    @Test("another PR starts from scratch")
    func switchesPR() async throws {
        let (store, daemon) = try await store(.failure(Settings.rejected(404, "not_in_queue")))
        let other = PRRef(repo: "iprally/gitops", number: 412)
        await store.show(other)
        #expect(store.pr == other)
        #expect(store.isGone)
        #expect(store.config == nil)
        #expect(await daemon.calls.last == .prConfig(other))
    }
}
