import PRWizardKit
import Testing

@Suite struct GateListTests {
    private let iprally: GateList

    init() throws {
        let config = try Settings.envelope().rawConfig
        iprally = GateList(config[["projects", "iprally/iprally", "fix", "gates"]] ?? .null)
    }

    private func gate(_ name: String, _ kind: String) -> JSONValue {
        ["name": .string(name), "kind": .string(kind), "when": ["*"], "run": "true"]
    }

    @Test("iprally's gates read in run order")
    func reads() {
        #expect(iprally.configs.map(\.name) == ["cljfmt", "Karma"])
        #expect(iprally.configs.map(\.kind) == [.format, .test])
    }

    @Test(
        "a gate moves only within its kind and inside the list",
        arguments: [
            (0, 1, true), (1, -1, true), (1, 1, false), (2, -1, false), (3, 1, false), (0, -1, false), (3, -1, true),
        ])
    func reorder(index: Int, offset: Int, allowed: Bool) {
        let list = GateList([gate("a", "format"), gate("b", "format"), gate("c", "test"), gate("d", "test")])
        #expect(list.canMove(index, by: offset) == allowed)
    }

    @Test("move swaps neighbours, and a refused move changes nothing")
    func move() {
        var list = GateList([gate("a", "format"), gate("b", "format"), gate("c", "test")])
        list.move(0, by: 1)
        #expect(list.configs.map(\.name) == ["b", "a", "c"])
        list.move(1, by: 1)
        #expect(list.configs.map(\.name) == ["b", "a", "c"])
    }

    @Test("duplicate puts a copy right after, unknown keys and all")
    func duplicate() {
        var list = GateList([gate("a", "format"), gate("c", "test")])
        list.duplicate(at: 0)
        #expect(list.configs.map(\.name) == ["a", "a copy", "c"])
        list.remove(at: 0)
        #expect(list.value == [gate("a copy", "format"), gate("c", "test")])
    }

    @Test("an empty list has no gates")
    func empty() {
        #expect(GateList([]).configs.isEmpty)
    }
}
