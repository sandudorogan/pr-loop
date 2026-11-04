import Foundation
import PRLoopKit
import Testing

@Suite struct CoreModelTests {
    @Test("JSONValue keeps every JSON kind")
    func jsonValueKinds() throws {
        let json = #"{"a": [null, true, 1.5, "s", {}]}"#
        let value = try JSONDecoder().decode(JSONValue.self, from: Data(json.utf8))
        #expect(value == .object(["a": .array([.null, .bool(true), .number(1.5), .string("s"), .object([:])])]))
    }

    @Test("a PR ref's id is the wire key")
    func refID() {
        #expect(PRRef(repo: "iprally/gitops", number: 412).id == "iprally/gitops#412")
    }
}
