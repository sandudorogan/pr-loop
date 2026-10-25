import Foundation
import Observation

@MainActor @Observable public final class QueueStore {
    public private(set) var phase = Phase.idle
    public private(set) var info: DaemonInfo?
    public private(set) var pendingActions: Set<PendingAction> = []
    public private(set) var lastActionError: ActionFailure?

    public var snapshot: QueueSnapshot? { phase.snapshot }
    public var projects: [ProjectSummary] {
        snapshot.map { snapshot in snapshot.projects.map { ProjectSummary($0, in: snapshot) } } ?? []
    }

    private let daemon: any DaemonAPI
    private let wait: Duration
    private let now: () -> Date
    private let sleep: LongPoll<QueueFeed.Update>.Sleep
    private var task: Task<Void, Never>?

    public init(
        daemon: any DaemonAPI, wait: Duration = .seconds(55), now: @escaping () -> Date = { Date() },
        sleep: @escaping LongPoll<QueueFeed.Update>.Sleep = { try await Task.sleep(for: $0) }
    ) {
        self.daemon = daemon
        self.wait = wait
        self.now = now
        self.sleep = sleep
    }

    public func start() {
        guard task == nil else { return }
        phase = .connecting
        task = Task { await run() }
    }

    public func retry() {
        task?.cancel()
        task = Task { await run() }
    }

    public func stop() {
        task?.cancel()
        task = nil
        phase = .idle
    }

    public func run() async {
        if case .idle = phase { phase = .connecting }
        for await event in QueueFeed(daemon: daemon, wait: wait, sleep: sleep) {
            apply(event)
            if case .incompatible = phase { return }
        }
    }

    public func refresh() async {
        await perform([.refresh], on: nil) { try await daemon.refresh() }
    }

    public func moveToFront(_ prs: [PRRef]) async {
        await perform(prs.map(PendingAction.moveToFront), on: prs.first) { _ = try await daemon.moveToFront(prs) }
    }

    public func review(_ pr: PRRef) async {
        await perform([.review(pr)], on: pr) { try await daemon.review(pr) }
    }

    public func fix(_ pr: PRRef) async {
        await perform([.fix(pr)], on: pr) { try await daemon.fix(pr) }
    }

    public func startDaemon(with launcher: any DaemonLauncher) async {
        await perform([.startDaemon], on: nil) { try await launcher.start() }
        retry()
    }

    public func setPaused(_ paused: Bool) async {
        await perform([.setPaused(paused)], on: nil) { _ = try await daemon.setPaused(paused) }
    }

    private func apply(_ event: FeedEvent<QueueFeed.Update>) {
        switch event {
        case .value(let update):
            info = update.info ?? info
            phase = .live(update.snapshot)
        case .failure(APIError.incompatible(let api), _):
            phase = .incompatible(api: api)
        case .failure(let error, let delay):
            let retryAt = now().addingTimeInterval(delay / .seconds(1))
            phase = snapshot.map { .stale($0, error, retryAt: retryAt) } ?? .down(error, retryAt: retryAt)
        }
    }

    private func perform(_ actions: [PendingAction], on pr: PRRef?, _ request: () async throws -> Void) async {
        pendingActions.formUnion(actions)
        do {
            try await request()
            pendingActions.subtract(actions)
        } catch {
            pendingActions.subtract(actions)
            let failure = ActionFailure(pr: pr, error: error)
            lastActionError = failure
            Task {
                try? await sleep(.seconds(6))
                if lastActionError?.id == failure.id { lastActionError = nil }
            }
        }
    }
}
