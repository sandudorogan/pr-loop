import Observation

@MainActor @Observable public final class PeekModel {
    public enum Phase: Hashable, Sendable {
        case idle
        case dwelling(String)
        case shown(String)
        case leaving(String)
    }

    public typealias Sleep = @Sendable (Duration) async throws -> Void

    public static let dwell = Duration.milliseconds(600)
    public static let grace = Duration.milliseconds(300)

    public private(set) var phase = Phase.idle

    @ObservationIgnored private let sleep: Sleep
    @ObservationIgnored private var timer: Task<Void, Never>?

    public init(sleep: @escaping Sleep = { try await Task.sleep(for: $0) }) {
        self.sleep = sleep
    }

    public var shownID: String? {
        switch phase {
        case .shown(let id), .leaving(let id): id
        case .idle, .dwelling: nil
        }
    }

    public func enter(_ id: String) {
        switch phase {
        case .dwelling(id): return
        case .shown(id), .leaving(id): set(.shown(id))
        default: set(.dwelling(id), then: .shown(id), after: Self.dwell)
        }
    }

    public func exit(_ id: String) {
        switch phase {
        case .dwelling(id): set(.idle)
        case .shown(id): set(.leaving(id), then: .idle, after: Self.grace)
        default: return
        }
    }

    public func toggle(_ id: String) {
        set(shownID == id ? .idle : .shown(id))
    }

    public func dismiss() {
        set(.idle)
    }

    private func set(_ phase: Phase, then next: Phase? = nil, after delay: Duration = .zero) {
        timer?.cancel()
        self.phase = phase
        timer = next.map { next in
            Task { [sleep] in
                guard (try? await sleep(delay)) != nil, !Task.isCancelled else { return }
                self.phase = next
            }
        }
    }
}
