public protocol HTTPTransport: Sendable {
    func send(_ request: HTTPRequest, timeout: Duration) async throws -> HTTPResponse
}
