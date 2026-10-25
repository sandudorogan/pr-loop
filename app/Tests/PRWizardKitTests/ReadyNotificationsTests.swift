import PRWizardKit
import Testing

@MainActor @Suite struct ReadyNotificationsTests {
    private func run(
        _ daemon: ScriptedDaemon, _ notifier: FakeNotifier, _ cursor: MemoryCursor, isEnabled: Bool = true
    ) async -> ReadyNotifications {
        let store = ReadyNotifications(
            daemon: daemon, notifier: notifier, cursor: cursor, isEnabled: { isEnabled }, sleep: Sleeper().sleep)
        await store.run()
        return store
    }

    @Test("first launch ever subscribes from now: saves the cursor, posts nothing, skips the snapshot")
    func firstLaunch() async throws {
        let daemon = ScriptedDaemon(events: [.success(try Events.page("e.58"))])
        let notifier = FakeNotifier()
        let cursor = MemoryCursor()
        _ = await run(daemon, notifier, cursor)
        #expect(cursor.saves == ["e.58"])
        #expect(await notifier.posts.isEmpty)
        #expect(await daemon.calls.first == .events(since: nil, wait: .zero))
        #expect(await !daemon.calls.contains(.queue(since: nil, wait: .zero)))
    }

    @Test("a relaunch catches up once against the snapshot, then long-polls from the new cursor")
    func catchUpOnce() async throws {
        let daemon = ScriptedDaemon(
            queue: [.success(try Snapshots.queue())],
            events: [
                .success(try Events.page("e.3", [Events.ready(2), Events.ready(3, number: 17201)])),
                .success(try Events.page("e.3")),
            ])
        let notifier = FakeNotifier()
        let cursor = MemoryCursor("e.1")
        _ = await run(daemon, notifier, cursor)
        #expect(await notifier.posts.map(\.key) == ["iprally/iprally#17166"])
        #expect(cursor.saves == ["e.3"])
        #expect(
            await daemon.calls == [
                .events(since: "e.1", wait: .zero), .queue(since: nil, wait: .zero),
                .events(since: "e.3", wait: .seconds(55)), .events(since: "e.3", wait: .seconds(55)),
            ])
    }

    @Test("live pages post without the snapshot check and remove by key")
    func live() async throws {
        let daemon = ScriptedDaemon(
            events: [
                .success(try Events.page("e.1")),
                .success(try Events.page("e.3", [Events.ready(2, number: 17201), Events.withdrawn(3, number: 17120)])),
            ])
        let notifier = FakeNotifier()
        let cursor = MemoryCursor("e.1")
        _ = await run(daemon, notifier, cursor)
        #expect(await notifier.posts.map(\.key) == ["iprally/iprally#17201"])
        #expect(await notifier.removes == ["iprally/iprally#17120"])
        #expect(cursor.saves == ["e.1", "e.3"])
    }

    @Test("reset: true replays through the snapshot filter, keeps the new cursor and posts an id once")
    func reset() async throws {
        let stale = Events.ready(1, number: 17201)
        let daemon = ScriptedDaemon(
            queue: [.success(try Snapshots.queue()), .success(try Snapshots.queue())],
            events: [
                .success(try Events.page("x.2", [Events.ready(2), stale], reset: true)),
                .success(try Events.page("y.2", [Events.ready(2), stale], reset: true)),
            ])
        let notifier = FakeNotifier()
        let cursor = MemoryCursor("old.9")
        _ = await run(daemon, notifier, cursor)
        #expect(await notifier.posts.map(\.key) == ["iprally/iprally#17166"])
        #expect(cursor.saves == ["x.2", "y.2"])
        #expect(await daemon.calls.count { $0 == .queue(since: nil, wait: .zero) } == 2)
    }

    @Test("the cursor moves after the ops ran, and a failed post holds it until the next page retries")
    func cursorAfterOps() async throws {
        let daemon = ScriptedDaemon(
            events: [
                .success(try Events.page("e.1")), .success(try Events.page("e.2", [Events.ready(2)])),
                .success(try Events.page("e.3", [Events.ready(3, number: 17201)])),
            ])
        let cursor = MemoryCursor("e.1")
        let notifier = FakeNotifier(cursor: cursor)
        await notifier.fail("ready_for_approval:iprally/iprally#17166@9f8e7d6c5b4a")
        _ = await run(daemon, notifier, cursor)
        #expect(cursor.saves == ["e.1", "e.3"])
        #expect(await notifier.posts.map(\.key) == ["iprally/iprally#17166", "iprally/iprally#17201"])
        #expect(await notifier.cursorsAtPost == ["e.1", "e.1"])
    }

    @Test(
        "toggle off or permission denied posts nothing, and the cursor keeps moving",
        arguments: [(false, NotificationAuthorization.authorized), (true, .denied)])
    func silent(isEnabled: Bool, status: NotificationAuthorization) async throws {
        let daemon = ScriptedDaemon(
            events: [.success(try Events.page("e.1")), .success(try Events.page("e.2", [Events.ready(2)]))])
        let notifier = FakeNotifier(status)
        let cursor = MemoryCursor("e.1")
        let store = await run(daemon, notifier, cursor, isEnabled: isEnabled)
        #expect(await notifier.posts.isEmpty)
        #expect(cursor.saves == ["e.1", "e.2"])
        #expect(store.authorization == status)
    }

    @Test("not determined with the toggle on asks once")
    func requestOnce() async {
        let notifier = FakeNotifier(.notDetermined, granted: .notDetermined)
        let store = ReadyNotifications(
            daemon: ScriptedDaemon(), notifier: notifier, cursor: MemoryCursor(), isEnabled: { true })
        await store.authorize()
        await store.authorize()
        #expect(await notifier.requests == 1)
    }

    @Test("a denial shows as the warning state; the toggle off never asks")
    func permission() async {
        let denied = ReadyNotifications(
            daemon: ScriptedDaemon(), notifier: FakeNotifier(.notDetermined, granted: .denied), cursor: MemoryCursor(),
            isEnabled: { true })
        await denied.authorize()
        #expect(denied.authorization == .denied)
        let notifier = FakeNotifier(.notDetermined)
        let off = ReadyNotifications(
            daemon: ScriptedDaemon(), notifier: notifier, cursor: MemoryCursor(), isEnabled: { false })
        await off.authorize()
        #expect(await notifier.requests == 0)
        #expect(off.authorization == .notDetermined)
    }
}
