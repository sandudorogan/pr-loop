import Foundation
import PRWizardKit
import Testing

@Suite struct UnixSocketTransportTests {
    private func reply(_ status: String, _ body: String) -> Data {
        Data(
            "HTTP/1.1 \(status)\r\nContent-Type: application/json\r\nContent-Length: \(body.utf8.count)\r\nConnection: close\r\n\r\n\(body)"
                .utf8)
    }

    @Test("a 200 round-trips over the socket")
    func ok() async throws {
        let server = try TestSocketServer(reply: reply("200 OK", #"{"paused": true}"#))
        defer { server.stop() }
        let response = try await UnixSocketTransport(path: server.path).send(
            HTTPRequest(.post, "/v1/pause"), timeout: .seconds(5))
        #expect(response.status == 200)
        #expect(response.body == Data(#"{"paused": true}"#.utf8))
    }

    @Test("a 4xx error body reaches the client as APIError.http")
    func errorBody() async throws {
        let server = try TestSocketServer(
            reply: reply("409 Conflict", String(decoding: try Fixture.data("error-busy.json"), as: UTF8.self)))
        defer { server.stop() }
        let client = DaemonClient(transport: UnixSocketTransport(path: server.path))
        let error = await #expect(throws: APIError.self) {
            try await client.fix(PRRef(repo: "iprally/iprally", number: 17190))
        }
        guard case .http(409, "busy", _, _) = error else {
            Issue.record("\(String(describing: error))")
            return
        }
    }

    @Test("no socket file means down")
    func missing() async {
        await #expect(throws: APIError.down) {
            try await UnixSocketTransport(path: TestSocketServer.temporaryPath()).send(
                HTTPRequest(.get, "/v1/info"), timeout: .seconds(5))
        }
    }

    @Test("a stale socket file means down")
    func refused() async throws {
        let path = try TestSocketServer.stale()
        defer { unlink(path) }
        await #expect(throws: APIError.down) {
            try await UnixSocketTransport(path: path).send(HTTPRequest(.get, "/v1/info"), timeout: .seconds(5))
        }
    }

    @Test("a server that never answers times out")
    func timeout() async throws {
        let server = try TestSocketServer(reply: nil)
        defer { server.stop() }
        await #expect(throws: APIError.timeout) {
            try await UnixSocketTransport(path: server.path).send(
                HTTPRequest(.get, "/v1/queue"), timeout: .milliseconds(200))
        }
    }
}
