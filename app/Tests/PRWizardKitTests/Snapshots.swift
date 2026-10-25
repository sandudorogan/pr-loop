import Foundation
import PRWizardKit

enum Snapshots {
    static func info() throws -> DaemonInfo {
        try Fixture.decode(DaemonInfo.self, from: "info.json")
    }

    static func queue(rev: String = "b71e09c4d2a35f18", lanes: JSONValue? = nil) throws -> QueueSnapshot {
        var queue = try JSONDecoder().decode([String: JSONValue].self, from: Fixture.data("queue.json"))
        queue["rev"] = .string(rev)
        queue["lanes"] = lanes ?? queue["lanes"]
        return try JSONDecoder.daemon.decode(QueueSnapshot.self, from: JSONEncoder().encode(queue))
    }

    static func pool(_ lane: String, _ repo: String, workers: Int = 2, busy: Int = 0) -> JSONValue {
        .object([
            "id": .string("\(lane):\(repo)"), "lane": .string(lane), "repo": .string(repo),
            "workers": .number(Double(workers)), "busy": .number(Double(busy)), "pending": .number(0),
        ])
    }
}
