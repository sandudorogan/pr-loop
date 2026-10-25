import Foundation
import PRWizardKit

actor FakeTransport: HTTPTransport {
    private let response: HTTPResponse
    private(set) var requests: [HTTPRequest] = []
    private(set) var timeouts: [Duration] = []

    init(status: Int = 200, body: Data) {
        response = HTTPResponse(status: status, body: body)
    }

    init(status: Int = 200, fixture: String) throws {
        self.init(status: status, body: try Fixture.data(fixture))
    }

    func send(_ request: HTTPRequest, timeout: Duration) async throws -> HTTPResponse {
        requests.append(request)
        timeouts.append(timeout)
        return response
    }

    var last: HTTPRequest? { requests.last }

    var lastBody: JSONValue? {
        get throws { try last?.body.map { try JSONDecoder().decode(JSONValue.self, from: $0) } }
    }
}
