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
}
