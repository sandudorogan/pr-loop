import Foundation

/// The owner's order of the sections and of each section's stages. Kinds missing from a stored layout (an older
/// app wrote it) keep their default place at the end.
public struct QueueLayout: Hashable, Sendable {
    public private(set) var sections: [QueueSection.Kind]
    public private(set) var stages: [QueueSection.Kind: [QueueStage.Kind]]

    public init(
        sections: [QueueSection.Kind] = QueueSection.Kind.allCases,
        stages: [QueueSection.Kind: [QueueStage.Kind]] = [:]
    ) {
        self.sections = sections
        self.stages = stages
    }

    public var sectionOrder: [QueueSection.Kind] { Self.complete(sections) }

    public func stageOrder(of section: QueueSection.Kind) -> [QueueStage.Kind] {
        Self.complete(stages[section] ?? [])
    }

    /// Drops a dragged header (`dragID`) on another header of the same level: the dragged one takes its place.
    @discardableResult
    public mutating func drop(_ dragged: String, on target: String) -> Bool {
        switch (Self.parse(dragged), Self.parse(target)) {
        case (.section(let from), .section(let to)):
            sections = Self.move(from, to: to, in: sectionOrder)
        case (.stage(let section, let from), .stage(let other, let to)) where section == other:
            stages[section] = Self.move(from, to: to, in: stageOrder(of: section))
        default:
            return false
        }
        return true
    }

    private enum Header {
        case section(QueueSection.Kind)
        case stage(QueueSection.Kind, QueueStage.Kind)
    }

    private static func parse(_ dragID: String) -> Header? {
        let parts = dragID.split(separator: ":", maxSplits: 1).map(String.init)
        guard parts.count == 2 else { return nil }
        let path = parts[1].split(separator: ".").map(String.init)
        switch (parts[0], path.count) {
        case ("section", 1): return QueueSection.Kind(rawValue: path[0]).map(Header.section)
        case ("stage", 2):
            guard let section = QueueSection.Kind(rawValue: path[0]), let stage = QueueStage.Kind(rawValue: path[1])
            else { return nil }
            return .stage(section, stage)
        default: return nil
        }
    }

    private static func move<T: Equatable>(_ item: T, to target: T, in order: [T]) -> [T] {
        guard let to = order.firstIndex(of: target), item != target else { return order }
        var moved = order.filter { $0 != item }
        moved.insert(item, at: to)
        return moved
    }

    private static func complete<T: CaseIterable & Equatable>(_ stored: [T]) -> [T] {
        stored + T.allCases.filter { !stored.contains($0) }
    }
}

/// `@AppStorage` keeps the layout as JSON. It goes through `Stored`: a `Codable` type that is also
/// `RawRepresentable` as a String encodes itself through `rawValue`, which recurses until the stack overflows.
extension QueueLayout: RawRepresentable {
    private struct Stored: Codable {
        let sections: [QueueSection.Kind]
        let stages: [QueueSection.Kind: [QueueStage.Kind]]
    }

    public init?(rawValue: String) {
        guard let stored = try? JSONDecoder().decode(Stored.self, from: Data(rawValue.utf8)) else { return nil }
        self.init(sections: stored.sections, stages: stored.stages)
    }

    public var rawValue: String {
        let data = try? JSONEncoder().encode(Stored(sections: sections, stages: stages))
        return data.map { String(decoding: $0, as: UTF8.self) } ?? "{}"
    }
}
