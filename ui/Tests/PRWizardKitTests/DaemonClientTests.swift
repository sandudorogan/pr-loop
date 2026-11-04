import Foundation
import PRWizardKit
import Testing

@Suite struct DaemonClientTests {
    private let gitops = PRRef(repo: "iprally/gitops", number: 412)

    private func query(_ items: [String: String]) -> [URLQueryItem] {
        items.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) }
    }

    @Test("info reads GET /v1/info")
    func info() async throws {
        let transport = try FakeTransport(fixture: "info.json")
        let info = try await DaemonClient(transport: transport).info()
        #expect(info.api == 1)
        #expect(await transport.last == HTTPRequest(.get, "/v1/info"))
        #expect(await transport.timeouts == [.seconds(10)])
    }

    @Test("info from another API version is incompatible")
    func incompatible() async throws {
        var info = try JSONDecoder().decode([String: JSONValue].self, from: Fixture.data("info.json"))
        info["api"] = .number(2)
        let transport = FakeTransport(body: try JSONEncoder().encode(info))
        await #expect(throws: APIError.incompatible(api: 2)) { try await DaemonClient(transport: transport).info() }
    }

    @Test("queue long-polls with since and wait, timeout wait + 10 s")
    func queue() async throws {
        let transport = try FakeTransport(fixture: "queue.json")
        _ = try await DaemonClient(transport: transport).queue(since: "3f9a", wait: .seconds(55))
        #expect(await transport.last?.path == "/v1/queue")
        #expect(
            await transport.last?.query == [
                URLQueryItem(name: "since", value: "3f9a"), URLQueryItem(name: "wait", value: "55"),
            ])
        #expect(await transport.timeouts == [.seconds(65)])
    }

    @Test("events with no cursor send only wait")
    func events() async throws {
        let transport = try FakeTransport(fixture: "events.json")
        let page = try await DaemonClient(transport: transport).events(since: nil, wait: .zero)
        #expect(page.cursor == "k3f9a2.58")
        #expect(await transport.last == HTTPRequest(.get, "/v1/events", query: query(["wait": "0"])))
    }

    @Test("config reads GET /v1/config")
    func config() async throws {
        let transport = try FakeTransport(fixture: "config.json")
        #expect(try await DaemonClient(transport: transport).config().rev == "5c663cb8963c")
        #expect(await transport.last == HTTPRequest(.get, "/v1/config"))
    }

    @Test("patchConfig sends the merge patch with its base rev")
    func patchConfig() async throws {
        let transport = try FakeTransport(fixture: "config.json")
        let patch: JSONValue = .object(["fix": .object(["workers": .number(1)])])
        _ = try await DaemonClient(transport: transport).patchConfig(patch, baseRev: "3f9a0c1d2e4b")
        #expect(await transport.last?.method == .patch)
        #expect(await transport.last?.path == "/v1/config")
        #expect(try await transport.lastBody == .object(["base_rev": .string("3f9a0c1d2e4b"), "patch": patch]))
    }

    @Test("putConfig sends the whole document with its base rev")
    func putConfig() async throws {
        let transport = try FakeTransport(fixture: "config.json")
        let config: JSONValue = ["projects": ["iprally/gitops": ["fix": ["model": .null]]]]
        _ = try await DaemonClient(transport: transport).putConfig(config, baseRev: "3f9a0c1d2e4b")
        #expect(await transport.last?.method == .put)
        #expect(await transport.last?.path == "/v1/config")
        #expect(try await transport.lastBody == ["base_rev": "3f9a0c1d2e4b", "config": config])
    }

    @Test("a stale base rev is a 412 stale_config")
    func staleConfig() async throws {
        let body = #"{"error": {"code": "stale_config", "message": "the config changed since rev 3f9a0c1d2e4b"}}"#
        let transport = FakeTransport(status: 412, body: Data(body.utf8))
        await #expect(
            throws: APIError.http(
                status: 412, code: "stale_config", message: "the config changed since rev 3f9a0c1d2e4b", details: [])
        ) { try await DaemonClient(transport: transport).patchConfig(.object([:]), baseRev: "3f9a0c1d2e4b") }
    }

    @Test("an invalid patch is a 422 with every problem")
    func invalidPatch() async throws {
        let transport = try FakeTransport(status: 422, fixture: "error-invalid-config.json")
        let error = await #expect(throws: APIError.self) {
            try await DaemonClient(transport: transport).patchConfig(.object([:]), baseRev: "3f9a0c1d2e4b")
        }
        guard case .http(422, "invalid_config", _, let details) = error else {
            Issue.record("\(String(describing: error))")
            return
        }
        #expect(details.count == 2)
    }

    @Test("prompt reads GET /v1/prompts/{name}")
    func prompt() async throws {
        let transport = try FakeTransport(fixture: "prompt.json")
        #expect(try await DaemonClient(transport: transport).prompt(named: "merge.md").name == "merge.md")
        #expect(await transport.last == HTTPRequest(.get, "/v1/prompts/merge.md"))
    }

    @Test("history sends limit and the optional repo")
    func history() async throws {
        let transport = try FakeTransport(fixture: "history.json")
        let client = DaemonClient(transport: transport)
        #expect(try await client.history(repo: nil, limit: 20).count == 1)
        #expect(await transport.last?.query == query(["limit": "20"]))
        _ = try await client.history(repo: "iprally/gitops", limit: 5)
        #expect(await transport.last?.query == query(["limit": "5", "repo": "iprally/gitops"]))
    }

    @Test("refresh posts /v1/refresh")
    func refresh() async throws {
        let transport = FakeTransport(status: 202, body: Data(#"{"accepted": true}"#.utf8))
        try await DaemonClient(transport: transport).refresh()
        #expect(await transport.last == HTTPRequest(.post, "/v1/refresh"))
    }

    @Test("moveToFront posts the refs in order")
    func moveToFront() async throws {
        let transport = try FakeTransport(fixture: "next.json")
        let prs = [PRRef(repo: "iprally/iprally", number: 17201), gitops]
        let result = try await DaemonClient(transport: transport).moveToFront(prs)
        #expect(result.next.count == 2)
        #expect(await transport.last?.path == "/v1/next")
        let refs: [JSONValue] = [
            .object(["repo": .string("iprally/iprally"), "number": .number(17201)]),
            .object(["repo": .string("iprally/gitops"), "number": .number(412)]),
        ]
        #expect(try await transport.lastBody == .object(["prs": .array(refs)]))
    }

    @Test("review and fix post to the PR's path")
    func actions() async throws {
        let transport = try FakeTransport(status: 202, fixture: "accepted.json")
        let client = DaemonClient(transport: transport)
        try await client.review(gitops)
        try await client.fix(gitops)
        #expect(
            await transport.requests == [
                HTTPRequest(.post, "/v1/prs/iprally/gitops/412/review"),
                HTTPRequest(.post, "/v1/prs/iprally/gitops/412/fix"),
            ])
    }

    @Test("pausing a PR posts its own route", arguments: [true, false])
    func pausePR(paused: Bool) async throws {
        let transport = FakeTransport(body: Data(#"{"key": "iprally/gitops#412", "paused": \#(paused)}"#.utf8))
        #expect(try await DaemonClient(transport: transport).setPaused(gitops, paused) == paused)
        #expect(await transport.last == HTTPRequest(.post, "/v1/prs/iprally/gitops/412/\(paused ? "pause" : "resume")"))
    }

    @Test("done and todo post their own routes", arguments: [true, false])
    func done(done: Bool) async throws {
        let transport = FakeTransport(body: Data(#"{"key": "iprally/gitops#412", "done": \#(done)}"#.utf8))
        #expect(try await DaemonClient(transport: transport).setDone(gitops, done) == done)
        #expect(await transport.last == HTTPRequest(.post, "/v1/prs/iprally/gitops/412/\(done ? "done" : "todo")"))
    }

    @Test("pause and resume post their routes and return the state", arguments: [true, false])
    func pause(paused: Bool) async throws {
        let transport = FakeTransport(body: Data(#"{"paused": \#(paused)}"#.utf8))
        #expect(try await DaemonClient(transport: transport).setPaused(paused) == paused)
        #expect(await transport.last == HTTPRequest(.post, paused ? "/v1/pause" : "/v1/resume"))
    }

    @Test("an error body becomes APIError.http")
    func busy() async throws {
        let transport = try FakeTransport(status: 409, fixture: "error-busy.json")
        await #expect(
            throws: APIError.http(
                status: 409, code: "busy", message: "a live run already holds iprally/iprally#17190", details: [])
        ) { try await DaemonClient(transport: transport).review(gitops) }
    }

    @Test("invalid_config keeps every detail")
    func invalidConfig() async throws {
        let transport = try FakeTransport(status: 422, fixture: "error-invalid-config.json")
        let error = await #expect(throws: APIError.self) { try await DaemonClient(transport: transport).refresh() }
        guard case .http(422, "invalid_config", _, let details) = error else {
            Issue.record("\(String(describing: error))")
            return
        }
        #expect(details.map(\.path) == ["review.workers", #"projects["iprally/gitops"].fix.workers"#])
    }

    @Test("a body that does not decode is a decoding error", arguments: [200, 500])
    func undecodable(status: Int) async throws {
        let transport = FakeTransport(status: status, body: Data("{}".utf8))
        let error = await #expect(throws: APIError.self) { try await DaemonClient(transport: transport).info() }
        guard case .decoding = error else {
            Issue.record("\(String(describing: error))")
            return
        }
    }

    @Test("the PR config routes carry the ref in the path, and PATCH sends its base rev")
    func prConfig() async throws {
        let transport = try FakeTransport(fixture: "pr-config.json")
        let client = DaemonClient(transport: transport)
        let config = try await client.prConfig(gitops)
        _ = try await client.patchPRConfig(gitops, ["fix": ["enabled": false]], baseRev: config.rev)
        _ = try await client.deletePRConfig(gitops)
        _ = try await client.putPRConfig(gitops, ["fix": ["model": .null]], baseRev: config.rev)
        #expect(await transport.requests.map(\.method) == [.get, .patch, .delete, .put])
        #expect(Set(await transport.requests.map(\.path)) == ["/v1/prs/iprally/gitops/412/config"])
        #expect(
            try await transport.requests[1].body.map(JSONValue.init(parsing:)) == [
                "base_rev": "2e8fe284ec8f", "patch": ["fix": ["enabled": false]],
            ])
        #expect(config.layers.pr == ["review.reviewers"])
        #expect(config.effective.review.reviewers.map(\.id) == ["opus"])
    }

    @Test("a PR that left the queue is a 404 not_in_queue")
    func prNotInQueue() async throws {
        let body =
            #"{"error": {"code": "not_in_queue", "message": "iprally/gitops#412 is not in the last queue fetch"}}"#
        let transport = FakeTransport(status: 404, body: Data(body.utf8))
        let error = await #expect(throws: APIError.self) {
            try await DaemonClient(transport: transport).prConfig(gitops)
        }
        guard case .http(404, "not_in_queue", _, _) = error else {
            Issue.record("\(String(describing: error))")
            return
        }
    }
}
