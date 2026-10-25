import Foundation
import PRWizardKit

enum Events {
    static let ready17166 = "9f8e7d6c5b4a39281706f5e4d3c2b1a098f7e6d5"

    static func event(
        _ type: String, _ seq: Int, repo: String = "iprally/iprally", number: Int = 17166, head: String = ready17166,
        verdict: String? = "quality-only"
    ) -> JSONValue {
        let key = "\(repo)#\(number)"
        return .object([
            "id": .string("\(type):\(key)@\(head.prefix(12))"), "seq": .number(Double(seq)), "type": .string(type),
            "key": .string(key), "repo": .string(repo), "number": .number(Double(number)),
            "title": .string("refactor(ui): one sub per hop in the filters"),
            "url": .string("https://github.com/\(repo)/pull/\(number)"), "author": .string("colleague"),
            "head": .string(head), "verdict": verdict.map(JSONValue.string) ?? .null,
            "at": .string("2026-10-24T17:40:02+03:00"),
        ])
    }

    static func ready(_ seq: Int, number: Int = 17166, repo: String = "iprally/iprally", head: String = ready17166)
        -> JSONValue
    {
        event("ready_for_approval", seq, repo: repo, number: number, head: head)
    }

    static func withdrawn(_ seq: Int, number: Int = 17166, head: String = "1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e")
        -> JSONValue
    {
        event("ready_withdrawn", seq, number: number, head: head, verdict: nil)
    }

    static func page(_ cursor: String, _ events: [JSONValue] = [], reset: Bool = false) throws -> EventPage {
        let page: JSONValue = .object(["cursor": .string(cursor), "reset": .bool(reset), "events": .array(events)])
        return try JSONDecoder.daemon.decode(EventPage.self, from: JSONEncoder().encode(page))
    }
}
