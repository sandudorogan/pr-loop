import PRWizardKit

actor ScriptedDaemon: DaemonAPI {
    enum Call: Hashable {
        case info
        case queue(since: String?, wait: Duration)
        case events(since: String?, wait: Duration)
        case history(repo: String?, limit: Int)
        case refresh
        case moveToFront([PRRef])
        case review(PRRef)
        case fix(PRRef)
        case setPaused(Bool)
        case setPRPaused(PRRef, Bool)
        case config
        case patchConfig(JSONValue, baseRev: String)
        case putConfig(JSONValue, baseRev: String)
        case prConfig(PRRef)
        case patchPRConfig(PRRef, JSONValue, baseRev: String)
        case deletePRConfig(PRRef)
    }

    private struct Unscripted: Error {}

    private var infos: [Result<DaemonInfo, any Error>]
    private var snapshots: [Result<QueueSnapshot, any Error>]
    private var histories: [Result<[HistoryEntry], any Error>]
    private var configs: [Result<ConfigEnvelope, any Error>]
    private var patches: [Result<ConfigEnvelope, any Error>]
    private var pages: [Result<EventPage, any Error>]
    private var prConfigs: [Result<PRConfig, any Error>]
    private var errors: [Call: any Error] = [:]
    private let gate: Gate?
    private(set) var calls: [Call] = []

    init(
        info: [Result<DaemonInfo, any Error>] = [], queue: [Result<QueueSnapshot, any Error>] = [],
        history: [Result<[HistoryEntry], any Error>] = [], config: [Result<ConfigEnvelope, any Error>] = [],
        patch: [Result<ConfigEnvelope, any Error>] = [], events: [Result<EventPage, any Error>] = [],
        prConfig: [Result<PRConfig, any Error>] = [], gate: Gate? = nil
    ) {
        infos = info
        snapshots = queue
        histories = history
        configs = config
        patches = patch
        pages = events
        prConfigs = prConfig
        self.gate = gate
    }

    func fail(_ call: Call, with error: any Error) {
        errors[call] = error
    }

    func serve(_ snapshot: QueueSnapshot) {
        snapshots.append(.success(snapshot))
    }

    func info() async throws -> DaemonInfo {
        calls.append(.info)
        return try Self.next(&infos)
    }

    func queue(since rev: String?, wait: Duration) async throws -> QueueSnapshot {
        calls.append(.queue(since: rev, wait: wait))
        return try Self.next(&snapshots)
    }

    func events(since cursor: String?, wait: Duration) async throws -> EventPage {
        calls.append(.events(since: cursor, wait: wait))
        return try Self.next(&pages)
    }

    func config() async throws -> ConfigEnvelope {
        calls.append(.config)
        return try Self.next(&configs)
    }

    func patchConfig(_ patch: JSONValue, baseRev: String) async throws -> ConfigEnvelope {
        calls.append(.patchConfig(patch, baseRev: baseRev))
        return try Self.next(&patches)
    }

    func putConfig(_ config: JSONValue, baseRev: String) async throws -> ConfigEnvelope {
        calls.append(.putConfig(config, baseRev: baseRev))
        return try Self.next(&patches)
    }

    func prompt(named name: String) async throws -> Prompt { throw Unscripted() }
    func history(repo: String?, limit: Int) async throws -> [HistoryEntry] {
        calls.append(.history(repo: repo, limit: limit))
        return try Self.next(&histories)
    }

    func refresh() async throws { try await act(.refresh) }
    func moveToFront(_ prs: [PRRef]) async throws -> NextResult {
        try await act(.moveToFront(prs))
        return try Fixture.decode(NextResult.self, from: "next.json")
    }
    func review(_ pr: PRRef) async throws { try await act(.review(pr)) }
    func fix(_ pr: PRRef) async throws { try await act(.fix(pr)) }
    func setPaused(_ paused: Bool) async throws -> Bool {
        try await act(.setPaused(paused))
        return paused
    }
    func setPaused(_ pr: PRRef, _ paused: Bool) async throws -> Bool {
        try await act(.setPRPaused(pr, paused))
        return paused
    }

    func prConfig(_ pr: PRRef) async throws -> PRConfig {
        calls.append(.prConfig(pr))
        return try Self.next(&prConfigs)
    }

    func patchPRConfig(_ pr: PRRef, _ patch: JSONValue, baseRev: String) async throws -> PRConfig {
        calls.append(.patchPRConfig(pr, patch, baseRev: baseRev))
        return try Self.next(&prConfigs)
    }

    func deletePRConfig(_ pr: PRRef) async throws -> PRConfig {
        calls.append(.deletePRConfig(pr))
        return try Self.next(&prConfigs)
    }

    private func act(_ call: Call) async throws {
        calls.append(call)
        await gate?.pass()
        if let error = errors[call] { throw error }
    }

    private static func next<Value>(_ script: inout [Result<Value, any Error>]) throws -> Value {
        guard !script.isEmpty else { throw CancellationError() }
        return try script.removeFirst().get()
    }
}
