import Foundation

public enum HTTPCodec {
    private static let unreserved = CharacterSet(
        charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    private static let separator = Data("\r\n\r\n".utf8)

    public static func encode(_ request: HTTPRequest) -> Data {
        let body = request.body ?? Data()
        let lines =
            ["\(request.method.rawValue) \(target(of: request)) HTTP/1.1", "Host: pr-wizard", "Connection: close"]
            + (request.body == nil ? [] : ["Content-Type: application/json"])
            + ["Content-Length: \(body.count)", "", ""]
        return Data(lines.joined(separator: "\r\n").utf8) + body
    }

    public static func decode(_ data: Data) throws(APIError) -> HTTPResponse {
        guard let end = data.firstRange(of: separator),
            let head = String(data: data[..<end.lowerBound], encoding: .utf8)
        else { throw .decoding("no HTTP header") }
        let lines = head.components(separatedBy: "\r\n")
        let statusLine = lines[0].split(separator: " ", maxSplits: 2)
        guard statusLine.count >= 2, statusLine[0].hasPrefix("HTTP/1."), let status = Int(statusLine[1]) else {
            throw .decoding("bad status line: \(lines[0])")
        }
        let headers = Dictionary(
            lines.dropFirst().compactMap { line in
                line.firstIndex(of: ":").map {
                    (line[..<$0].lowercased(), line[line.index(after: $0)...].trimmingCharacters(in: .whitespaces))
                }
            }, uniquingKeysWith: { _, last in last })
        guard headers["transfer-encoding"] == nil else { throw .decoding("chunked body") }
        guard status != 204, status != 304 else { throw .decoding("status \(status) has no body") }
        let body = data[end.upperBound...]
        guard let length = headers["content-length"].flatMap(Int.init) else { throw .decoding("no Content-Length") }
        guard body.count == length else { throw .decoding("body is \(body.count) bytes, Content-Length \(length)") }
        return HTTPResponse(status: status, headers: headers, body: Data(body))
    }

    private static func target(of request: HTTPRequest) -> String {
        let query = request.query.map { "\(escaped($0.name))=\(escaped($0.value ?? ""))" }
        return query.isEmpty ? request.path : "\(request.path)?\(query.joined(separator: "&"))"
    }

    private static func escaped(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: unreserved) ?? value
    }
}
