import Foundation

public struct HistoryRow: Hashable, Identifiable, Sendable {
    public let entry: HistoryEntry

    public init(_ entry: HistoryEntry) {
        self.entry = entry
    }

    public var id: String { entry.key }

    public var stateLabel: String {
        switch entry.state {
        case .settled: "Open"
        case .merged: "Merged"
        case .closed: "Closed"
        case .unknown(let value): value.capitalized
        }
    }

    public var outcome: StatusStyle { StatusStyle(entry.outcome) }
}
