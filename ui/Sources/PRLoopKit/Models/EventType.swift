public enum EventType: OpenEnum {
    case readyForApproval, readyWithdrawn
    case unknown(String)

    public static let known: [Self] = [.readyForApproval, .readyWithdrawn]

    public var rawValue: String {
        switch self {
        case .readyForApproval: "ready_for_approval"
        case .readyWithdrawn: "ready_withdrawn"
        case .unknown(let value): value
        }
    }
}
