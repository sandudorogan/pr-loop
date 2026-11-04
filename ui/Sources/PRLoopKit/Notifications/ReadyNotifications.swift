import Observation

@MainActor @Observable public final class ReadyNotifications {
    public private(set) var authorization = NotificationAuthorization.notDetermined

    private let daemon: any DaemonAPI
    private let notifier: any Notifier
    private let cursor: any EventCursor
    private let isEnabled: () -> Bool
    private let sleep: LongPoll<EventFeed.Update>.Sleep
    private var task: Task<Void, Never>?
    private var hasRequested = false
    private var unposted: [ReadyNotification] = []
    private var posted: Set<String> = []

    public init(
        daemon: any DaemonAPI, notifier: any Notifier, cursor: any EventCursor, isEnabled: @escaping () -> Bool,
        sleep: @escaping LongPoll<EventFeed.Update>.Sleep = { try await Task.sleep(for: $0) }
    ) {
        self.daemon = daemon
        self.notifier = notifier
        self.cursor = cursor
        self.isEnabled = isEnabled
        self.sleep = sleep
    }

    public func start() {
        guard task == nil else { return }
        task = Task { await run() }
    }

    public func stop() {
        task?.cancel()
        task = nil
    }

    public func run() async {
        await authorize()
        for await event in EventFeed(daemon: daemon, cursor: cursor.lastSeen(), sleep: sleep) {
            if case .value(let update) = event { await apply(update) }
        }
    }

    public func authorize() async {
        authorization = await notifier.authorization()
        guard authorization == .notDetermined, isEnabled(), !hasRequested else { return }
        hasRequested = true
        authorization = await notifier.requestAuthorization()
    }

    private func apply(_ update: EventFeed.Update) async {
        let ops = unposted.map(NotificationOp.post) + update.ops
        unposted = []
        authorization = await notifier.authorization()
        let isPosting = isEnabled() && authorization.allowsPosting
        for op in ops {
            switch op {
            case .post(let notification) where isPosting && !posted.contains(notification.id):
                do {
                    try await notifier.post(notification)
                    posted.insert(notification.id)
                } catch {
                    unposted.append(notification)
                }
            case .post: break
            case .remove(let key): await notifier.removeDelivered(key: key)
            }
        }
        if unposted.isEmpty { cursor.save(update.page.cursor) }
    }
}
