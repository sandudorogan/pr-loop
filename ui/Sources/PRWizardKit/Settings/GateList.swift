public struct GateList: Hashable, Sendable {
    public private(set) var gates: [JSONValue]

    public init(_ value: JSONValue) {
        gates = if case .array(let gates) = value { gates } else { [] }
    }

    public var value: JSONValue { .array(gates) }

    public var configs: [GateConfig] { (try? value.decoded([GateConfig].self)) ?? [] }

    public func canMove(_ index: Int, by offset: Int) -> Bool {
        gates.indices.contains(index) && gates.indices.contains(index + offset)
            && gates[index][["kind"]] == gates[index + offset][["kind"]]
    }

    public mutating func move(_ index: Int, by offset: Int) {
        guard canMove(index, by: offset) else { return }
        gates.swapAt(index, index + offset)
    }

    public mutating func remove(at index: Int) {
        gates.remove(at: index)
    }

    public mutating func duplicate(at index: Int) {
        let name = gates[index][["name"]]?.string ?? ""
        gates.insert(gates[index].setting(.string("\(name) copy"), at: ["name"]), at: index + 1)
    }
}

extension GateList {
    public var canAdd: Bool { gates.count < GateDraft.maxGates }

    /// Replaces the gate at `index`, or inserts a new one (or one whose kind changed) at the end of its kind, so
    /// format gates stay ahead of test gates. Returns where the gate landed.
    @discardableResult public mutating func save(_ gate: GateConfig, at index: Int?) -> Int {
        guard let value = try? JSONValue(encoding: gate) else { return index ?? gates.count }
        if let index, gates[index][["kind"]]?.string == gate.kind.rawValue {
            gates[index] = value
            return index
        }
        if let index { gates.remove(at: index) }
        let landing =
            gates.lastIndex { $0[["kind"]]?.string == gate.kind.rawValue }.map { $0 + 1 }
            ?? (gate.kind == .format ? 0 : gates.count)
        gates.insert(value, at: landing)
        return landing
    }
}
