public struct StringPair: Hashable, Sendable {
    public var from = ""
    public var to = ""

    public init(from: String = "", to: String = "") {
        self.from = from
        self.to = to
    }
}
