public struct EventFeed: AsyncSequence, Sendable {
    public struct Update: Hashable, Sendable {
        public let page: EventPage
        public let snapshot: QueueSnapshot?

        public var ops: [NotificationOp] {
            snapshot.map { CatchUp.plan(page, in: $0) } ?? LivePlan.plan(page)
        }
    }

    private let poll: LongPoll<Update>

    public init(
        daemon: any DaemonAPI, cursor: String?, wait: Duration = .seconds(55),
        sleep: @escaping LongPoll<Update>.Sleep = { try await Task.sleep(for: $0) }
    ) {
        poll = LongPoll(
            cursor: cursor,
            connect: { try await Self.update(daemon.events(since: $0, wait: .zero), daemon, isCatchUp: true) },
            poll: { try await Self.update(daemon.events(since: $0, wait: wait), daemon, isCatchUp: false) },
            next: { $0.page.cursor },
            sleep: sleep)
    }

    public func makeAsyncIterator() -> LongPoll<Update>.Iterator {
        poll.makeAsyncIterator()
    }

    private static func update(_ page: EventPage, _ daemon: any DaemonAPI, isCatchUp: Bool) async throws -> Update {
        let needsSnapshot = (isCatchUp || page.isReset) && !page.events.isEmpty
        return try await Update(page: page, snapshot: needsSnapshot ? daemon.queue(since: nil, wait: .zero) : nil)
    }
}
