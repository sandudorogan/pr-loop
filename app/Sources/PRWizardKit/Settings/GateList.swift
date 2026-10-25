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
