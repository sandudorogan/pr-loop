actor Gate {
    private var held: CheckedContinuation<Void, Never>?
    private var watcher: CheckedContinuation<Void, Never>?

    func pass() async {
        await withCheckedContinuation {
            held = $0
            watcher?.resume()
            watcher = nil
        }
    }

    func arrival() async {
        guard held == nil else { return }
        await withCheckedContinuation { watcher = $0 }
    }

    func open() {
        held?.resume()
        held = nil
    }
}
