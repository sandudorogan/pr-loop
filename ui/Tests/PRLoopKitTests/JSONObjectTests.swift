import Foundation
import PRLoopKit
import Testing

@Suite struct JSONObjectTests {
    private func keyPaths(_ value: JSONValue, _ prefix: String = "") -> [String] {
        switch value {
        case .object(let object): object.flatMap { [prefix + $0.key] + keyPaths($0.value, prefix + $0.key + "/") }
        case .array(let values): values.flatMap { keyPaths($0, prefix) }
        default: []
        }
    }

    @Test("parse then write returns the same bytes, keys unsorted")
    func wireRoundTrip() throws {
        let text = #"{"b":1,"a":[true,null,"x\n\"q\"\\ \u0001é😀"],"c":{"z":0.5,"y":-2,"x":{}},"d":[]}"#
        #expect(String(decoding: try JSONValue(parsing: Data(text.utf8)).data, as: UTF8.self) == text)
    }

    @Test("a \\u escape and a surrogate pair read as the characters")
    func escapes() throws {
        let value = try JSONValue(parsing: Data(#"["é😀"]"#.utf8))
        #expect(value == ["é😀"])
    }

    @Test("bad JSON throws", arguments: ["", "{", #"{"a" 1}"#, "[1,]", "tru", #"{"a":1} x"#, #""open"#])
    func malformed(text: String) {
        #expect(throws: DecodingError.self) { try JSONValue(parsing: Data(text.utf8)) }
    }

    @Test("equality ignores the key order, a changed value still differs")
    func equality() throws {
        let one = try JSONValue(parsing: Data(#"{"a":1,"b":{"c":2,"d":3}}"#.utf8))
        let two = try JSONValue(parsing: Data(#"{"b":{"d":3,"c":2},"a":1}"#.utf8))
        #expect(one == two)
        #expect(one.hashValue == two.hashValue)
        #expect(one != (try JSONValue(parsing: Data(#"{"a":1,"b":{"c":2,"d":4}}"#.utf8))))
    }

    @Test("setting keeps a key's place, adding appends, removing closes the gap, merging keeps the base order")
    func edits() {
        var object: JSONObject = ["b": 1, "a": 2, "c": 3]
        object["a"] = 9
        object["d"] = 4
        object["b"] = nil
        #expect(object.keys == ["a", "c", "d"])
        let merged = object.merging(["e": 5, "a": 0]) { $1 }
        #expect(merged.keys == ["a", "c", "d", "e"])
        #expect(merged["a"] == 0)
    }

    @Test("the config fixture keeps every key in file order through parse, write and parse")
    func fixtureOrder() throws {
        let tree = try JSONValue(parsing: Fixture.data("config.json"))
        let paths = keyPaths(tree)
        #expect(paths != paths.sorted())
        #expect(try keyPaths(JSONValue(parsing: tree.data)) == paths)
        #expect(try keyPaths(tree.decoded(JSONValue.self)) == paths)
        let config = try #require(tree[["config"]])
        guard case .object(let object) = config else {
            Issue.record("config is not an object")
            return
        }
        #expect(object.keys == ["version", "detect", "lanes", "projects", "review", "fix", "refresh"])
    }

    @Test("the envelope's raw config and a typed model's unknown keys keep the source order")
    func decodedOrder() throws {
        let raw = try Settings.envelope().rawConfig
        #expect(keyPaths(raw) == keyPaths(try JSONValue(parsing: Fixture.data("config.json"))[["config"]] ?? .null))
        let gate = try JSONValue(parsing: Data(#"{"name":"g","kind":"format","when":[],"run":"x","z":1,"a":2}"#.utf8))
        #expect(try gate.decoded(GateConfig.self).unknown.keys == ["z", "a"])
        #expect(
            try keyPaths(JSONValue(encoding: gate.decoded(GateConfig.self))) == [
                "name", "kind", "when", "run", "z", "a",
            ])
    }
}
