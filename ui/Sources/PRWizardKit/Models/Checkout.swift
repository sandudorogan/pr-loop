public struct Checkout: Codable, Hashable, Sendable {
    public let path: String
    public let source: CheckoutSource
}
