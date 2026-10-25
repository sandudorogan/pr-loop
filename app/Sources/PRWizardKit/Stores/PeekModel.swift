import Observation

@MainActor @Observable public final class PeekModel {
    public private(set) var shownID: String?

    public init() {}

    public func toggle(_ id: String) {
        shownID = shownID == id ? nil : id
    }

    /// Space on a table row: toggles the peek of the one selected row (`nil` is none, or one with no findings).
    /// Returns whether it took the key, so any other Space reaches its text field.
    public func toggleOnSpace(_ id: String?) -> Bool {
        guard let id else { return false }
        toggle(id)
        return true
    }

    public func dismiss() {
        shownID = nil
    }
}
