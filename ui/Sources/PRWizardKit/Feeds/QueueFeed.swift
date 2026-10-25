public struct QueueFeed: AsyncSequence, Sendable {
    public struct Update: Hashable, Sendable {
        public let info: DaemonInfo?
        public let snapshot: QueueSnapshot
    }

    private let poll: LongPoll<Update>

    public init(
        daemon: any DaemonAPI, wait: Duration = .seconds(55),
        sleep: @escaping LongPoll<Update>.Sleep = { try await Task.sleep(for: $0) }
    ) {
        poll = LongPoll(
            cursor: nil,
            connect: { _ in try await Update(info: daemon.info(), snapshot: daemon.queue(since: nil, wait: .zero)) },
            poll: { try await Update(info: nil, snapshot: daemon.queue(since: $0, wait: wait)) },
            next: { $0.snapshot.rev },
            sleep: sleep)
    }

    public func makeAsyncIterator() -> LongPoll<Update>.Iterator {
        poll.makeAsyncIterator()
    }
}
