import Foundation

extension Findings {
    public var header: String {
        "Round \(round) · head \(InspectorModel.short(head)) · \(atFloor) at or above the fix floor"
    }

    public var staleNote: String? { isCurrent ? nil : "Not reviewed at this head" }

    public var reviewedAt: Date? { reviewers.map(\.at).max() }

    public var conventionsLine: String {
        conventions.isEmpty ? "No project conventions" : "Followed " + conventions.joined(separator: " · ")
    }

    public var conventionsFooter: String {
        guard conventions.count > 3 else { return conventionsLine }
        return "Followed " + conventions.prefix(3).joined(separator: " · ") + " +\(conventions.count - 3)"
    }
}
