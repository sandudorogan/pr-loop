import Foundation

public struct DaemonClient: DaemonAPI {
    private static let timeout = Duration.seconds(10)

    private let transport: any HTTPTransport

    public init(transport: any HTTPTransport) {
        self.transport = transport
    }

    public func info() async throws -> DaemonInfo {
        let info: DaemonInfo = try await send(HTTPRequest(.get, "/v1/info"))
        guard info.api == 1 else { throw APIError.incompatible(api: info.api) }
        return info
    }

    public func queue(since rev: String?, wait: Duration) async throws -> QueueSnapshot {
        try await send(
            HTTPRequest(.get, "/v1/queue", query: longPoll(since: rev, wait: wait)), timeout: wait + .seconds(10))
    }

    public func events(since cursor: String?, wait: Duration) async throws -> EventPage {
        try await send(
            HTTPRequest(.get, "/v1/events", query: longPoll(since: cursor, wait: wait)), timeout: wait + .seconds(10))
    }

    public func config() async throws -> ConfigEnvelope {
        try await send(HTTPRequest(.get, "/v1/config"))
    }

    public func patchConfig(_ patch: JSONValue, baseRev: String) async throws -> ConfigEnvelope {
        let body: JSONValue = .object(["base_rev": .string(baseRev), "patch": patch])
        return try await send(HTTPRequest(.patch, "/v1/config", body: JSONEncoder().encode(body)))
    }

    public func putConfig(_ config: JSONValue, baseRev: String) async throws -> ConfigEnvelope {
        let body: JSONValue = .object(["base_rev": .string(baseRev), "config": config])
        return try await send(HTTPRequest(.put, "/v1/config", body: JSONEncoder().encode(body)))
    }

    public func prompt(named name: String) async throws -> Prompt {
        try await send(HTTPRequest(.get, "/v1/prompts/\(name)"))
    }

    public func history(repo: String?, limit: Int) async throws -> [HistoryEntry] {
        let query =
            [URLQueryItem(name: "limit", value: String(limit))]
            + (repo.map { [URLQueryItem(name: "repo", value: $0)] } ?? [])
        let page: HistoryPage = try await send(HTTPRequest(.get, "/v1/history", query: query))
        return page.entries
    }

    public func refresh() async throws {
        let _: Accepted = try await send(HTTPRequest(.post, "/v1/refresh"))
    }

    public func moveToFront(_ prs: [PRRef]) async throws -> NextResult {
        try await send(HTTPRequest(.post, "/v1/next", body: JSONEncoder().encode(["prs": prs])))
    }

    public func review(_ pr: PRRef) async throws {
        let _: Accepted = try await send(HTTPRequest(.post, "\(path(of: pr))/review"))
    }

    public func fix(_ pr: PRRef) async throws {
        let _: Accepted = try await send(HTTPRequest(.post, "\(path(of: pr))/fix"))
    }

    public func setPaused(_ paused: Bool) async throws -> Bool {
        let state: PauseState = try await send(HTTPRequest(.post, paused ? "/v1/pause" : "/v1/resume"))
        return state.isPaused
    }

    private func send<Value: Decodable>(_ request: HTTPRequest, timeout: Duration = timeout) async throws -> Value {
        let response = try await transport.send(request, timeout: timeout)
        guard response.isSuccess else {
            let body = try decode(APIErrorBody.self, from: response.body).error
            throw APIError.http(
                status: response.status, code: body.code, message: body.message, details: body.details ?? [])
        }
        return try decode(Value.self, from: response.body)
    }

    private func decode<Value: Decodable>(_ type: Value.Type, from data: Data) throws(APIError) -> Value {
        do {
            return try JSONDecoder.daemon.decode(type, from: data)
        } catch {
            throw .decoding(String(describing: error))
        }
    }

    private func longPoll(since cursor: String?, wait: Duration) -> [URLQueryItem] {
        (cursor.map { [URLQueryItem(name: "since", value: $0)] } ?? []) + [
            URLQueryItem(name: "wait", value: String(wait.components.seconds))
        ]
    }

    private func path(of pr: PRRef) -> String {
        "/v1/prs/\(pr.repo)/\(pr.number)"
    }
}
