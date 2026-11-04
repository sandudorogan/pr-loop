public enum HistoryState: OpenEnum {
    case settled, merged, closed
    case unknown(String)

    public static let known: [Self] = [.settled, .merged, .closed]

    public var rawValue: String {
        switch self {
        case .settled: "settled"
        case .merged: "merged"
        case .closed: "closed"
        case .unknown(let value): value
        }
    }
}
