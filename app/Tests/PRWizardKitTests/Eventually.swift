@MainActor func eventually(_ condition: () -> Bool) async -> Bool {
    for _ in 0..<1000 where !condition() { await Task.yield() }
    return condition()
}
