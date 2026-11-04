import Foundation
import PRLoopKit
import Testing

@Suite struct HTTPCodecTests {
    private func text(_ request: HTTPRequest) -> String {
        String(decoding: HTTPCodec.encode(request), as: UTF8.self)
    }

    private func response(_ raw: String) throws(APIError) -> HTTPResponse {
        try HTTPCodec.decode(Data(raw.utf8))
    }

    @Test("a GET has no body and Content-Length 0")
    func encodesGet() {
        #expect(
            text(HTTPRequest(.get, "/v1/info"))
                == "GET /v1/info HTTP/1.1\r\nHost: pr-loop\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
    }

    @Test("a body sets its type and length")
    func encodesBody() {
        #expect(
            text(HTTPRequest(.post, "/v1/next", body: Data(#"{"a":1}"#.utf8)))
                == "POST /v1/next HTTP/1.1\r\nHost: pr-loop\r\nConnection: close\r\n"
                + "Content-Type: application/json\r\nContent-Length: 7\r\n\r\n{\"a\":1}")
    }

    @Test("query values escape everything but unreserved characters")
    func escapesQuery() {
        let request = HTTPRequest(
            .get, "/v1/history",
            query: [URLQueryItem(name: "repo", value: "iprally/iprally"), URLQueryItem(name: "q", value: "a+b c&d")])
        #expect(text(request).hasPrefix("GET /v1/history?repo=iprally%2Fiprally&q=a%2Bb%20c%26d HTTP/1.1\r\n"))
    }

    @Test("a response keeps status, lowercased headers and body")
    func decodesResponse() throws {
        let parsed = try response(
            "HTTP/1.1 409 Conflict\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}")
        #expect(parsed.status == 409)
        #expect(parsed.headers["content-type"] == "application/json")
        #expect(parsed.body == Data("{}".utf8))
        #expect(parsed.isSuccess == false)
    }

    @Test(
        "malformed responses fail as decoding errors",
        arguments: [
            "",
            "garbage\r\n\r\n",
            "HTTP/1.1 OK\r\nContent-Length: 0\r\n\r\n",
            "HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\n{}",
            "HTTP/1.1 200 OK\r\n\r\n{}",
            "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n",
            "HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n",
            "HTTP/1.1 304 Not Modified\r\nContent-Length: 0\r\n\r\n",
        ])
    func rejects(raw: String) {
        #expect {
            try response(raw)
        } throws: { error in
            if case APIError.decoding = error { true } else { false }
        }
    }
}
