public enum APIError: Error, Hashable, Sendable {
    case down
    case timeout
    case http(status: Int, code: String, message: String, details: [APIErrorBody.Problem])
    case decoding(String)
    case incompatible(api: Int)
}
