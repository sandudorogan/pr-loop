import Foundation
import PRWizardKit
import Testing

extension QueueStore.Phase {
    fileprivate var summary: String {
        switch self {
        case .idle: "idle"
        case .connecting: "connecting"
        case .live(let snapshot): "live \(snapshot.rev)"
        case .stale(let snapshot, let error, let retryAt):
            "stale \(snapshot.rev) \(error) \(retryAt.timeIntervalSince1970)"
        case .down(let error, let retryAt): "down \(error) \(retryAt.timeIntervalSince1970)"
        case .incompatible(let api): "incompatible \(api)"
        }
    }
}

private actor Launches: DaemonLauncher {
    private(set) var count = 0

    func run(_ executable: String, _ arguments: [String]) {}

    func start() {
        count += 1
    }
}

@MainActor @Suite struct QueueStoreTests {
    private let pr = PRRef(repo: "iprally/iprally", number: 17190)
    private let gitops = PRRef(repo: "iprally/gitops", number: 412)
    private let busy = APIError.http(status: 409, code: "busy", message: "a live run holds it", details: [])

    private func store(_ daemon: ScriptedDaemon, sleeper: Sleeper = Sleeper()) -> QueueStore {
        QueueStore(daemon: daemon, now: { Date(timeIntervalSince1970: 1000) }, sleep: sleeper.sleep)
    }

    @Test("start connects, stop goes idle")
    func startStop() {
        let store = store(ScriptedDaemon())
        #expect(store.phase.summary == "idle")
        store.start()
        #expect(store.phase.summary == "connecting")
        store.stop()
        #expect(store.phase.summary == "idle")
    }

    @Test("the first snapshot goes live with the daemon info")
    func live() async throws {
        let store = store(
            ScriptedDaemon(info: [.success(try Snapshots.info())], queue: [.success(try Snapshots.queue(rev: "a"))]))
        await store.run()
        #expect(store.phase.summary == "live a")
        #expect(store.info?.label == "local.pr-wizard")
        #expect(store.projects.count == 4)
    }

    @Test("down before any snapshot, then live on reconnect")
    func down() async throws {
        let gate = Gate()
        let store = store(
            ScriptedDaemon(
                info: [.failure(APIError.down), .success(try Snapshots.info())],
                queue: [.success(try Snapshots.queue(rev: "a"))]),
            sleeper: Sleeper(gate: gate))
        let run = Task { await store.run() }
        await gate.arrival()
        #expect(store.phase.summary == "down down 1002.0")
        #expect(store.phase.isDisconnected)
        #expect(store.projects.isEmpty)
        await gate.open()
        await run.value
        #expect(store.phase.summary == "live a")
    }

    @Test("a failure after a snapshot keeps it stale, info is fetched once per connect")
    func stale() async throws {
        let gate = Gate()
        let daemon = ScriptedDaemon(
            info: [.success(try Snapshots.info()), .success(try Snapshots.info())],
            queue: [
                .success(try Snapshots.queue(rev: "a")), .failure(APIError.timeout),
                .success(try Snapshots.queue(rev: "b")),
            ])
        let store = store(daemon, sleeper: Sleeper(gate: gate))
        let run = Task { await store.run() }
        await gate.arrival()
        #expect(store.phase.summary == "stale a timeout 1002.0")
        #expect(store.projects.count == 4)
        await gate.open()
        await run.value
        #expect(store.phase.summary == "live b")
        #expect(await daemon.calls.count { $0 == .info } == 2)
    }

    @Test("another API version is terminal")
    func incompatible() async throws {
        let sleeper = Sleeper()
        let daemon = ScriptedDaemon(info: [.failure(APIError.incompatible(api: 2)), .success(try Snapshots.info())])
        let store = store(daemon, sleeper: sleeper)
        await store.run()
        #expect(store.phase.summary == "incompatible 2")
        #expect(await daemon.calls == [.info])
        #expect(await sleeper.durations.isEmpty)
    }

    @Test("actions reach the daemon with their PRRef")
    func actions() async {
        let daemon = ScriptedDaemon()
        let store = store(daemon)
        await store.review(pr)
        await store.fix(gitops)
        await store.moveToFront([gitops, pr])
        await store.refresh()
        await store.setPaused(true)
        #expect(
            await daemon.calls == [.review(pr), .fix(gitops), .moveToFront([gitops, pr]), .refresh, .setPaused(true)])
        #expect(store.lastActionError == nil)
    }

    @Test("an action is pending while its request runs")
    func pending() async {
        let gate = Gate()
        let store = store(ScriptedDaemon(gate: gate))
        let bump = Task { await store.moveToFront([gitops, pr]) }
        await gate.arrival()
        #expect(store.pendingActions == [.moveToFront(gitops), .moveToFront(pr)])
        await gate.open()
        await bump.value
        #expect(store.pendingActions.isEmpty)
    }

    @Test("409 busy shows for 6 s and clears the pending state")
    func busyBanner() async {
        let gate = Gate()
        let daemon = ScriptedDaemon()
        await daemon.fail(.review(pr), with: busy)
        let sleeper = Sleeper(gate: gate)
        let store = store(daemon, sleeper: sleeper)
        let review = Task { await store.review(pr) }
        await gate.arrival()
        #expect(store.lastActionError?.message == "iprally#17190 is in a live run")
        #expect(store.pendingActions.isEmpty)
        await gate.open()
        await review.value
        #expect(await eventually { store.lastActionError == nil })
        #expect(await sleeper.durations == [.seconds(6)])
    }

    @Test("a failed action returns before its banner clears")
    func failureReturns() async {
        let gate = Gate()
        let daemon = ScriptedDaemon()
        await daemon.fail(.review(pr), with: busy)
        let store = store(daemon, sleeper: Sleeper(gate: gate))
        await store.review(pr)
        #expect(store.lastActionError != nil)
        await gate.arrival()
        await gate.open()
        #expect(await eventually { store.lastActionError == nil })
    }

    @Test("retry reconnects at once, without waiting out the backoff")
    func retry() async throws {
        let gate = Gate()
        let daemon = ScriptedDaemon(
            info: [.failure(APIError.down), .success(try Snapshots.info())],
            queue: [.success(try Snapshots.queue(rev: "a"))])
        let store = store(daemon, sleeper: Sleeper(gate: gate))
        store.start()
        await gate.arrival()
        #expect(store.phase.summary == "down down 1002.0")
        store.retry()
        #expect(await eventually { store.snapshot?.rev == "a" })
        await gate.open()
        store.stop()
    }

    @Test("start daemon kickstarts it, then reconnects at once")
    func startDaemon() async throws {
        let gate = Gate()
        let launches = Launches()
        let store = store(
            ScriptedDaemon(
                info: [.failure(APIError.down), .success(try Snapshots.info())],
                queue: [.success(try Snapshots.queue(rev: "a"))]),
            sleeper: Sleeper(gate: gate))
        store.start()
        await gate.arrival()
        await store.startDaemon(with: launches)
        #expect(await launches.count == 1)
        #expect(await eventually { store.snapshot?.rev == "a" })
        #expect(!store.phase.isDisconnected)
        await gate.open()
        store.stop()
    }

    @Test(
        "an action failure reads as a sentence",
        arguments: [
            (APIError.down, "PR Wizard is not running"),
            (APIError.http(status: 409, code: "not_mine", message: "not your PR", details: []), "not your PR"),
        ])
    func failureMessage(error: APIError, message: String) async {
        let gate = Gate()
        let daemon = ScriptedDaemon()
        await daemon.fail(.fix(gitops), with: error)
        let store = store(daemon, sleeper: Sleeper(gate: gate))
        let fix = Task { await store.fix(gitops) }
        await gate.arrival()
        #expect(store.lastActionError?.message == message)
        await gate.open()
        await fix.value
    }
}
