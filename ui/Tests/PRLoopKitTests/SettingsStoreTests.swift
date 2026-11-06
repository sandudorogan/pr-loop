import PRLoopKit
import Testing

@MainActor @Suite struct SettingsStoreTests {
    private let gitops = Settings.gitops

    private func loaded(patch: [Result<ConfigEnvelope, any Error>] = []) async throws -> (SettingsStore, ScriptedDaemon)
    {
        let daemon = ScriptedDaemon(config: [.success(try Settings.envelope())], patch: patch)
        let store = SettingsStore(daemon: daemon)
        await store.load()
        return (store, daemon)
    }

    @Test("load fetches once and starts clean")
    func load() async throws {
        let (store, daemon) = try await loaded()
        await store.load()
        #expect(await daemon.calls == [.config])
        #expect(store.original?.rev == "ed1f0bca4af9")
        #expect(!store.isDirty)
    }

    @Test("an edit makes the draft dirty, and revert drops it")
    func dirtyRevert() async throws {
        let (store, _) = try await loaded()
        store.set("fix.workers", to: 1, in: .allRepos)
        #expect(store.isDirty)
        #expect(store.resolve("fix.workers", in: gitops).value == 1)
        store.revert()
        #expect(!store.isDirty)
        #expect(store.resolve("fix.workers", in: .allRepos).value == 3)
    }

    @Test("setting a value back to the original is not an edit")
    func editBack() async throws {
        let (store, _) = try await loaded()
        store.set("fix.workers", to: 1, in: .allRepos)
        store.set("fix.workers", to: 3, in: .allRepos)
        #expect(!store.isDirty)
    }

    @Test("one draft spans scopes, and one patch carries every scope's edits")
    func spansScopes() async throws {
        let (store, _) = try await loaded()
        store.set("review.workers", to: 2, in: .allRepos)
        store.set("fix.enabled", to: false, in: .project("sandudorogan/dataspex"))
        #expect(store.hasEdits(in: .allRepos))
        #expect(store.hasEdits(in: .project("sandudorogan/dataspex")))
        #expect(!store.hasEdits(in: gitops))
        #expect(
            store.patch == [
                "review": ["workers": 2], "projects": ["sandudorogan/dataspex": ["fix": ["enabled": false]]],
            ])
    }

    @Test("Use Default sends null, and an emptied override drops whole")
    func useDefault() async throws {
        let (store, _) = try await loaded()
        store.useDefault("review.enabled", in: gitops)
        #expect(store.resolve("review.enabled", in: gitops).source == .defaults)
        #expect(store.patch == ["projects": ["iprally/gitops": .null]])
    }

    @Test("leaving a default list copies it into the override, and returning drops the copy")
    func listCopy() async throws {
        let (store, _) = try await loaded()
        store.setUsesDefault(false, for: "review.reviewers", in: gitops)
        let copy = store.resolve("review.reviewers", in: gitops)
        #expect(copy.source == .project("iprally/gitops"))
        #expect(copy.value == store.resolve("review.reviewers", in: .allRepos).value)
        #expect(store.hasEdits(in: gitops))
        store.setUsesDefault(true, for: "review.reviewers", in: gitops)
        #expect(!store.isDirty)
    }

    @Test("apply 200 sends base_rev and the patch, takes the response, and records where it saved")
    func applied() async throws {
        let saved = try Settings.envelope(merging: ["rev": "aaaaaaaaaaaa", "config": ["fix": ["workers": 1]]])
        let (store, daemon) = try await loaded(patch: [.success(saved)])
        store.set("fix.workers", to: 1, in: .allRepos)
        await store.apply()
        #expect(await daemon.calls.last == .patchConfig(["fix": ["workers": 1]], baseRev: "ed1f0bca4af9"))
        #expect(store.original?.rev == "aaaaaaaaaaaa")
        #expect(!store.isDirty)
        #expect(store.savedTo == "/Users/sandu.dorogan/.local/share/chezmoi/.pr-loop/config.json")
        store.set("fix.workers", to: 2, in: .allRepos)
        #expect(store.savedTo == nil)
    }

    @Test("an explicit null in a project override goes out as the whole document")
    func explicitNull() async throws {
        let (store, daemon) = try await loaded(patch: [.success(try Settings.envelope())])
        store.set("fix.model", to: "gpt-6-astra", in: .allRepos)
        store.set("fix.model", to: .null, in: gitops)
        let draft = store.draft.config
        await store.apply()
        #expect(await daemon.calls.last == .putConfig(draft, baseRev: "ed1f0bca4af9"))
        #expect(draft[["projects", "iprally/gitops", "fix", "model"]] == .null)
    }

    @Test("a null at the top level is a delete, so it stays a patch")
    func topLevelNull() async throws {
        let set = try Settings.envelope(merging: ["config": ["fix": ["model": "gpt-6-astra"]]])
        let daemon = ScriptedDaemon(config: [.success(set)], patch: [.success(try Settings.envelope())])
        let store = SettingsStore(daemon: daemon)
        await store.load()
        store.set("fix.model", to: .null, in: .allRepos)
        await store.apply()
        #expect(await daemon.calls.last == .patchConfig(["fix": ["model": .null]], baseRev: "ed1f0bca4af9"))
    }

    @Test("an explicit null override in the file survives the load")
    func keepsNull() async throws {
        let null = try Settings.envelope(merging: [
            "config": ["projects": ["iprally/gitops": ["fix": ["model": .null]]]]
        ])
        let store = SettingsStore(daemon: ScriptedDaemon(config: [.success(null)]))
        await store.load()
        let model = store.resolve("fix.model", in: gitops)
        #expect(model.value == .null)
        #expect(model.source == .project("iprally/gitops"))
    }

    @Test("apply 412 keeps the draft and flags it stale until Reload")
    func stale() async throws {
        let daemon = ScriptedDaemon(
            config: [
                .success(try Settings.envelope()), .success(try Settings.envelope(merging: ["rev": "bbbbbbbbbbbb"])),
            ],
            patch: [.failure(Settings.rejected(412, "stale_config"))])
        let store = SettingsStore(daemon: daemon)
        await store.load()
        store.set("fix.workers", to: 1, in: .allRepos)
        await store.apply()
        #expect(store.isStale)
        #expect(store.isDirty)
        await store.reload()
        #expect(!store.isStale)
        #expect(!store.isDirty)
        #expect(store.original?.rev == "bbbbbbbbbbbb")
    }

    @Test("apply 422 maps every detail to its scope and key, and keeps the draft")
    func invalid() async throws {
        let details = try Fixture.decode(APIErrorBody.self, from: "error-invalid-config.json").error.details ?? []
        let (store, _) = try await loaded(patch: [.failure(Settings.rejected(422, "invalid_config", details))])
        store.set("review.workers", to: 9, in: .allRepos)
        store.set("fix.workers", to: 9, in: gitops)
        await store.apply()
        #expect(store.errors.messages(at: "review.workers", in: .allRepos) == ["must be an integer from 1 to 8"])
        #expect(store.errors.messages(at: "fix.workers", in: gitops) == ["must be an integer from 1 to 8"])
        #expect(store.isDirty)
        #expect(store.savedTo == nil)
        store.revert()
        #expect(store.errors.isEmpty)
    }

    @Test("any other failure lands in failure and keeps the draft")
    func down() async throws {
        let (store, _) = try await loaded(patch: [.failure(APIError.down)])
        store.set("fix.workers", to: 1, in: .allRepos)
        await store.apply()
        #expect(store.failure as? APIError == .down)
        #expect(store.isDirty)
    }

    @Test("apply with no edits sends nothing")
    func nothing() async throws {
        let (store, daemon) = try await loaded()
        await store.apply()
        #expect(await daemon.calls == [.config])
    }
}
