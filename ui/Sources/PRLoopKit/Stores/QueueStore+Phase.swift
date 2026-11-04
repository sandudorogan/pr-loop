import Foundation

extension QueueStore {
    public enum Phase: Sendable {
        case idle
        case connecting
        case live(QueueSnapshot)
        case stale(QueueSnapshot, any Error, retryAt: Date)
        case down(any Error, retryAt: Date)
        case incompatible(api: Int)

        public var isDisconnected: Bool {
            switch self {
            case .down, .stale: true
            default: false
            }
        }

        public var snapshot: QueueSnapshot? {
            switch self {
            case .live(let snapshot), .stale(let snapshot, _, _): snapshot
            default: nil
            }
        }
    }
}
