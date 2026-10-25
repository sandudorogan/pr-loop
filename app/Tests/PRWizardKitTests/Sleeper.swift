actor Sleeper {
    private let gate: Gate?
    private(set) var durations: [Duration] = []

    init(gate: Gate? = nil) {
        self.gate = gate
    }

    nonisolated var sleep: @Sendable (Duration) async throws -> Void {
        { await self.record($0) }
    }

    private func record(_ duration: Duration) async {
        durations.append(duration)
        await gate?.pass()
    }
}
