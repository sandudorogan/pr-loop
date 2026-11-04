import Foundation
import PRLoopKit
import Testing

@Suite struct ConfigPatchTests {
    struct Oracle: Decodable {
        struct Case: Decodable {
            let target: JSONValue
            let patch: JSONValue
        }

        let configs: [JSONValue]
        let patches: [Case]
    }

    static let oracle = Result { try JSONDecoder().decode(Oracle.self, from: Fixture.oracle()) }

    @Test("the patch merge_patch takes from base to target", arguments: 0..<6)
    func matchesDaemon(index: Int) throws {
        let oracle = try Self.oracle.get()
        #expect(ConfigPatch.diff(oracle.configs[0], oracle.patches[index].target) == oracle.patches[index].patch)
    }

    @Test("equal trees need no patch")
    func unchanged() {
        #expect(ConfigPatch.diff(["a": [1, 2]], ["a": [1, 2]]) == nil)
    }

    @Test("a changed leaf sends only its path")
    func leaf() {
        let base: JSONValue = ["fix": ["workers": 3, "engine": "codex"], "lanes": ["separate": false]]
        let target: JSONValue = ["fix": ["workers": 1, "engine": "codex"], "lanes": ["separate": false]]
        #expect(ConfigPatch.diff(base, target) == ["fix": ["workers": 1]])
    }

    @Test("a dropped key becomes null, an added key its value")
    func droppedAndAdded() {
        let base: JSONValue = ["projects": ["iprally/gitops": ["review": ["enabled": false]]]]
        let target: JSONValue = ["projects": ["acme/new": ["fix": ["enabled": false]]]]
        #expect(
            ConfigPatch.diff(base, target)
                == ["projects": ["iprally/gitops": .null, "acme/new": ["fix": ["enabled": false]]]])
    }

    @Test("an array replaces whole")
    func array() {
        #expect(ConfigPatch.diff(["trivial": ["*.md", "*.lock"]], ["trivial": ["*.md"]]) == ["trivial": ["*.md"]])
    }
}
