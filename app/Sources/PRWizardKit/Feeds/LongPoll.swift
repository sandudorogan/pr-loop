public struct LongPoll<Value: Sendable>: AsyncSequence, Sendable {
    public typealias Element = FeedEvent<Value>
    public typealias Fetch = @Sendable (String?) async throws -> Value
    public typealias Sleep = @Sendable (Duration) async throws -> Void

    private let cursor: String?
    private let connect: Fetch
    private let poll: Fetch
    private let next: @Sendable (Value) -> String
    private let sleep: Sleep

    public init(
        cursor: String?, connect: @escaping Fetch, poll: @escaping Fetch, next: @escaping @Sendable (Value) -> String,
        sleep: @escaping Sleep
    ) {
        self.cursor = cursor
        self.connect = connect
        self.poll = poll
        self.next = next
        self.sleep = sleep
    }

    public func makeAsyncIterator() -> Iterator {
        Iterator(feed: self, cursor: cursor)
    }

    public struct Iterator: AsyncIteratorProtocol {
        fileprivate let feed: LongPoll
        fileprivate var cursor: String?
        private var isConnected = false
        private var failures = 0
        private var backoff: Duration?

        fileprivate init(feed: LongPoll, cursor: String?) {
            self.feed = feed
            self.cursor = cursor
        }

        public mutating func next() async -> Element? {
            while !Task.isCancelled {
                if let delay = backoff {
                    backoff = nil
                    do { try await feed.sleep(delay) } catch { return nil }
                    continue
                }
                do {
                    let value = try await (isConnected ? feed.poll : feed.connect)(cursor)
                    try Task.checkCancellation()
                    let wasConnected = isConnected
                    let previous = cursor
                    cursor = feed.next(value)
                    isConnected = true
                    failures = 0
                    if !wasConnected || cursor != previous { return .value(value) }
                } catch is CancellationError {
                    return nil
                } catch {
                    guard !Task.isCancelled else { return nil }
                    isConnected = false
                    let delay = Backoff.delay(failures)
                    failures += 1
                    backoff = delay
                    return .failure(error, retryIn: delay)
                }
            }
            return nil
        }
    }
}
