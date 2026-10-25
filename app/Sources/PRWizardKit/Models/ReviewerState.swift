public enum ReviewerState: OpenEnum {
    case running, waiting, posted, clean, failed, limited
    case unknown(String)

    public static let known: [Self] = [.running, .waiting, .posted, .clean, .failed, .limited]

    public var rawValue: String {
        switch self {
        case .running: "running"
        case .waiting: "waiting"
        case .posted: "posted"
        case .clean: "clean"
        case .failed: "failed"
        case .limited: "limited"
        case .unknown(let value): value
        }
    }
}
