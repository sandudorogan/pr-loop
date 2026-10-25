import Foundation
import PRWizardKit
import Testing

private let socket = ProcessInfo.processInfo.environment["PR_WIZARD_CONTRACT_SOCKET"]

@Suite(.serialized, .enabled(if: socket != nil, "script/contract sets PR_WIZARD_CONTRACT_SOCKET"))
struct ContractTests {
    private let daemon = DaemonClient(transport: UnixSocketTransport(path: socket ?? ""))
    private let colleague = PRRef(repo: "iprally/iprally", number: 17166)
    private let seeded = PRRef(repo: "iprally/iprally", number: 17201)
    private let mine = PRRef(repo: "iprally/gitops", number: 412)

    @Test("info speaks api 1")
    func info() async throws {
        let info = try await daemon.info()
        #expect(info.name == "pr-wizard")
        #expect(info.api == 1)
    }

    @Test("a queue long-poll wakes on refresh")
    func queueWakes() async throws {
        let rev = try await daemon.queue(since: nil, wait: .zero).rev
        let poll = Task { try await daemon.queue(since: rev, wait: .seconds(30)) }
        try await Task.sleep(for: .milliseconds(200))
        let start = ContinuousClock.now
        try await daemon.refresh()
        let woken = try await poll.value
        #expect(woken.rev != rev)
        #expect(ContinuousClock.now - start < .seconds(10))
    }

    @Test("refresh appends a ready_for_approval after the cursor")
    func events() async throws {
        let subscribed = try await daemon.events(since: nil, wait: .zero)
        #expect(subscribed.events.isEmpty)
        try await daemon.refresh()
        let page = try await daemon.events(since: subscribed.cursor, wait: .zero)
        #expect(!page.isReset)
        #expect(page.cursor != subscribed.cursor)
        #expect(page.events.contains { $0.type == .readyForApproval && $0.ref == colleague })
    }

    @Test("history lists entries for one repo")
    func history() async throws {
        let entries = try await daemon.history(repo: "iprally/iprally", limit: 5)
        #expect(!entries.isEmpty)
        #expect(entries.allSatisfy { $0.repo == "iprally/iprally" })
    }

    @Test("config round-trips through PATCH and PUT")
    func configWrites() async throws {
        let loaded = try await daemon.config()
        let patched = try await daemon.patchConfig(["review": ["workers": 2]], baseRev: loaded.rev)
        #expect(patched.config.review.workers == 2)
        let restored = try await daemon.putConfig(loaded.rawConfig, baseRev: patched.rev)
        #expect(restored.rev == loaded.rev)
    }

    @Test("a stale base_rev is a 412")
    func staleConfig() async throws {
        let error = await #expect(throws: APIError.self) {
            try await daemon.patchConfig(["review": ["workers": 2]], baseRev: "000000000000")
        }
        guard case .http(412, "stale_config", _, []) = error else {
            Issue.record("\(String(describing: error))")
            return
        }
    }

    @Test("an invalid config is a 422 with bracket paths")
    func invalidConfig() async throws {
        let rev = try await daemon.config().rev
        let patch: JSONValue = ["review": ["workers": 0], "projects": ["iprally/gitops": ["fix": ["workers": 0]]]]
        let error = await #expect(throws: APIError.self) { try await daemon.patchConfig(patch, baseRev: rev) }
        guard case .http(422, "invalid_config", _, let details) = error else {
            Issue.record("\(String(describing: error))")
            return
        }
        #expect(Set(details.map(\.path)) == ["review.workers", #"projects["iprally/gitops"].fix.workers"#])
    }

    @Test("every listed prompt decodes")
    func prompts() async throws {
        let names = try await daemon.config().choices.prompts
        #expect(!names.isEmpty)
        for name in names {
            #expect(try await daemon.prompt(named: name).name == name)
        }
    }

    @Test("next bumps a queued PR")
    func next() async throws {
        let result = try await daemon.moveToFront([seeded])
        #expect(result.next.first == seeded.id)
        #expect(result.results.map(\.isBumped) == [true])
    }

    @Test("review now settles a colleague's PR as ready")
    func review() async throws {
        try await daemon.review(colleague)
        let item = try await daemon.queue(since: nil, wait: .zero).items.first { $0.ref == colleague }
        #expect(item?.group == .ready)
    }

    @Test("fix re-arms my PR")
    func fix() async throws {
        try await daemon.fix(mine)
        let item = try await daemon.queue(since: nil, wait: .zero).items.first { $0.ref == mine }
        #expect(item?.fix?.status == "nothing-to-fix")
    }

    @Test("pause and resume flip the snapshot")
    func pause() async throws {
        #expect(try await daemon.setPaused(true))
        #expect(try await daemon.queue(since: nil, wait: .zero).isPaused)
        #expect(try await daemon.setPaused(false) == false)
    }

    @Test("a PR override patches and deletes")
    func prConfig() async throws {
        let loaded = try await daemon.prConfig(seeded)
        #expect(loaded.layers.pr.contains("review.reviewers"))
        let patched = try await daemon.patchPRConfig(seeded, ["fix": ["enabled": false]], baseRev: loaded.rev)
        #expect(patched.layers.pr.contains("fix.enabled"))
        let dropped = try await daemon.deletePRConfig(seeded)
        #expect(dropped.override == nil)
        #expect(dropped.layers.pr.isEmpty)
    }
}
