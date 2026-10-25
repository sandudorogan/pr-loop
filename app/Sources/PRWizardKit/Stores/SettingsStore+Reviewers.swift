import Foundation

extension SettingsStore {
    public static let maxReviewers = 8

    public func reviewers(in scope: SettingsScope) -> [ReviewerConfig] {
        (try? resolve("review.reviewers", in: scope).value.decoded([ReviewerConfig].self)) ?? []
    }

    public func updateReviewer(at index: Int, in scope: SettingsScope, _ change: (inout ReviewerConfig) -> Void) {
        editReviewers(in: scope) { change(&$0[index]) }
    }

    public func canAddReviewer(in scope: SettingsScope) -> Bool {
        reviewers(in: scope).count < Self.maxReviewers
    }

    /// Validation needs one enabled reviewer, so the last enabled one stays.
    public func canRemoveReviewer(at index: Int, in scope: SettingsScope) -> Bool {
        let reviewers = reviewers(in: scope)
        return reviewers.count > 1 && (!reviewers[index].isEnabled || reviewers.count { $0.isEnabled } > 1)
    }

    /// Appends a copy of the reviewer at `index` and returns where it landed.
    @discardableResult public func addReviewer(copying index: Int, in scope: SettingsScope) -> Int {
        insertCopy(of: index, at: reviewers(in: scope).count, in: scope)
    }

    @discardableResult public func duplicateReviewer(at index: Int, in scope: SettingsScope) -> Int {
        insertCopy(of: index, at: index + 1, in: scope)
    }

    public func removeReviewer(at index: Int, in scope: SettingsScope) {
        editReviewers(in: scope) { $0.remove(at: index) }
    }

    /// Moves the reviewers at `offsets` before `destination` and returns where the first of them landed.
    @discardableResult public func moveReviewers(
        fromOffsets offsets: IndexSet, toOffset destination: Int, in scope: SettingsScope
    ) -> Int {
        let landing = destination - offsets.count { $0 < destination }
        editReviewers(in: scope) { reviewers in
            let moved = offsets.map { reviewers[$0] }
            reviewers = reviewers.enumerated().filter { !offsets.contains($0.offset) }.map(\.element)
            reviewers.insert(contentsOf: moved, at: landing)
        }
        return landing
    }

    private func insertCopy(of index: Int, at position: Int, in scope: SettingsScope) -> Int {
        editReviewers(in: scope) { reviewers in
            var copy = reviewers[index]
            copy.id = ReviewerConfig.uniqueID(from: copy.id, among: Set(reviewers.map(\.id)))
            copy.label = "\(copy.label) copy"
            reviewers.insert(copy, at: position)
        }
        return position
    }

    private func editReviewers(in scope: SettingsScope, _ change: (inout [ReviewerConfig]) -> Void) {
        var reviewers = reviewers(in: scope)
        change(&reviewers)
        if let value = try? JSONValue(encoding: reviewers) { set("review.reviewers", to: value, in: scope) }
    }
}
