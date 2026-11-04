import Foundation
import Observation

@MainActor @Observable public final class QueueStore {
    public private(set) var phase = Phase.idle
    public private(set) var info: DaemonInfo?
    public private(set) var pendingActions: Set<PendingAction> = []
    public private(set) var lastActionError: ActionFailure?
    public var isRefreshing: Bool { pendingActions.contains(.refresh) || refreshingFrom != nil }

    public var snapshot: QueueSnapshot? { phase.snapshot }
    public var projects: [ProjectSummary] {
        snapshot.map { snapshot in snapshot.projects.map { ProjectSummary($0, in: snapshot) } } ?? []
    }

    private let daemon: any DaemonAPI
    private let wait: Duration
    private let now: () -> Date
    private let sleep: LongPoll<QueueFeed.Update>.Sleep
    private var task: Task<Void, Never>?
    private var refreshingFrom: RefreshStatus?

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

    /// Stays refreshing past the 202 until a snapshot shows the daemon finished a fetch.
    public func refresh() async {
        refreshingFrom = snapshot?.refresh
        if !(await perform([.refresh], on: nil) { try await daemon.refresh() }) { refreshingFrom = nil }
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

    public func setPaused(_ prs: [PRRef], _ paused: Bool) async {
        await perform(prs.map(PendingAction.pause), on: prs.first) {
            for pr in prs { _ = try await daemon.setPaused(pr, paused) }
        }
    }

    public func setDone(_ prs: [PRRef], _ done: Bool) async {
        await perform(prs.map(PendingAction.done), on: prs.first) {
            for pr in prs { _ = try await daemon.setDone(pr, done) }
        }
    }

    private func apply(_ event: FeedEvent<QueueFeed.Update>) {
        switch event {
        case .value(let update):
            info = update.info ?? info
            phase = .live(update.snapshot)
            if update.snapshot.refresh.lastAt != refreshingFrom?.lastAt { refreshingFrom = nil }
        case .failure(APIError.incompatible(let api), _):
            refreshingFrom = nil
            phase = .incompatible(api: api)
        case .failure(let error, let delay):
            refreshingFrom = nil
            let retryAt = now().addingTimeInterval(delay / .seconds(1))
            phase = snapshot.map { .stale($0, error, retryAt: retryAt) } ?? .down(error, retryAt: retryAt)
        }
    }

    @discardableResult
    private func perform(_ actions: [PendingAction], on pr: PRRef?, _ request: () async throws -> Void) async -> Bool {
        pendingActions.formUnion(actions)
        do {
            try await request()
            pendingActions.subtract(actions)
            return true
        } catch {
            pendingActions.subtract(actions)
            let failure = ActionFailure(pr: pr, error: error)
            lastActionError = failure
            Task {
                try? await sleep(.seconds(6))
                if lastActionError?.id == failure.id { lastActionError = nil }
            }
            return false
        }
    }
}
