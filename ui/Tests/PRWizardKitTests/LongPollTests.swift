import PRWizardKit
import Testing

@Suite struct LongPollTests {
    private func events(_ feed: QueueFeed) async -> [String] {
        var events: [String] = []
        for await event in feed {
            switch event {
            case .value(let update): events.append("\(update.info == nil ? "" : "info ")\(update.snapshot.rev)")
            case .failure(let error, let delay): events.append("\(error) \(delay)")
            }
        }
        return events
    }

    @Test("backs off 2, 4, 8, 16, 30, 30 s", arguments: [(0, 2), (1, 4), (2, 8), (3, 16), (4, 30), (5, 30), (64, 30)])
    func backoff(attempt: Int, seconds: Int) {
        #expect(Backoff.delay(attempt) == .seconds(seconds))
    }

    @Test("connect reads info and the queue at once, then long-polls on the rev")
    func cursor() async throws {
        let daemon = ScriptedDaemon(
            info: [.success(try Snapshots.info())],
            queue: [
                .success(try Snapshots.queue(rev: "a")), .success(try Snapshots.queue(rev: "a")),
                .success(try Snapshots.queue(rev: "b")),
            ])
        let sleeper = Sleeper()
        #expect(await events(QueueFeed(daemon: daemon, sleep: sleeper.sleep)) == ["info a", "b"])
        #expect(
            await daemon.calls == [
                .info, .queue(since: nil, wait: .zero), .queue(since: "a", wait: .seconds(55)),
                .queue(since: "a", wait: .seconds(55)), .queue(since: "b", wait: .seconds(55)),
            ])
        #expect(await sleeper.durations.isEmpty)
    }

    @Test("a failure backs off, reconnects with info and resets the backoff")
    func reconnect() async throws {
        let down = [Result<DaemonInfo, any Error>](repeating: .failure(APIError.down), count: 6)
        let daemon = ScriptedDaemon(
            info: down + [.success(try Snapshots.info()), .success(try Snapshots.info())],
            queue: [
                .success(try Snapshots.queue(rev: "a")), .failure(APIError.timeout),
                .success(try Snapshots.queue(rev: "a")),
            ])
        let sleeper = Sleeper()
        let events = await events(QueueFeed(daemon: daemon, sleep: sleeper.sleep))
        #expect(events.suffix(3) == ["info a", "timeout 2.0 seconds", "info a"])
        #expect(await sleeper.durations == [2, 4, 8, 16, 30, 30, 2].map { .seconds($0) })
        #expect(await daemon.calls.count { $0 == .info } == 8)
    }

    @Test("cancellation stops the loop")
    func cancellation() async throws {
        let gate = Gate()
        let daemon = ScriptedDaemon(info: [.failure(APIError.down), .success(try Snapshots.info())])
        let feed = QueueFeed(daemon: daemon, sleep: Sleeper(gate: gate).sleep)
        let loop = Task { await events(feed) }
        await gate.arrival()
        loop.cancel()
        await gate.open()
        #expect(await loop.value == ["down 2.0 seconds"])
        #expect(await daemon.calls == [.info])
    }
}
