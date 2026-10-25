import Foundation
import PRWizardKit
import Testing

enum Snapshots {
    private struct Lists: Decodable {
        let items: [[String: JSONValue]]
        let projects: [[String: JSONValue]]
    }

    static func item(_ index: Int, _ patch: [String: JSONValue] = [:]) throws -> QueueItem {
        try patched(QueueItem.self, \.items, index, patch)
    }

    static func project(_ index: Int, _ patch: [String: JSONValue] = [:]) throws -> Project {
        try patched(Project.self, \.projects, index, patch)
    }

    private static func patched<Value: Decodable>(
        _ type: Value.Type, _ list: KeyPath<Lists, [[String: JSONValue]]>, _ index: Int,
        _ patch: [String: JSONValue]
    ) throws -> Value {
        let object = try JSONDecoder().decode(Lists.self, from: Fixture.data("queue.json"))[keyPath: list][index]
        return try JSONDecoder.daemon.decode(type, from: JSONEncoder().encode(object.merging(patch) { $1 }))
    }

    static func info() throws -> DaemonInfo {
        try Fixture.decode(DaemonInfo.self, from: "info.json")
    }

    static func queue(
        rev: String = "b71e09c4d2a35f18", lanes: JSONValue? = nil, items: (([JSONValue]) -> [JSONValue])? = nil,
        fetchedAt: String? = nil
    ) throws -> QueueSnapshot {
        var queue = try JSONDecoder().decode([String: JSONValue].self, from: Fixture.data("queue.json"))
        queue["rev"] = .string(rev)
        if let fetchedAt { queue["refresh"] = .object(["last_at": .string(fetchedAt), "last_error": .null]) }
        queue["lanes"] = lanes ?? queue["lanes"]
        if let items, case .array(let list) = queue["items"] { queue["items"] = .array(items(list)) }
        return try JSONDecoder.daemon.decode(QueueSnapshot.self, from: JSONEncoder().encode(queue))
    }

    static func pool(_ lane: String, _ repo: String, workers: Int = 2, busy: Int = 0) -> JSONValue {
        .object([
            "id": .string("\(lane):\(repo)"), "lane": .string(lane), "repo": .string(repo),
            "workers": .number(Double(workers)), "busy": .number(Double(busy)), "pending": .number(0),
        ])
    }
}

extension Snapshots {
    static func historyEntry(_ patch: [String: JSONValue] = [:]) throws -> HistoryEntry {
        var page = try JSONDecoder().decode([String: [[String: JSONValue]]].self, from: Fixture.data("history.json"))
        let entry = try #require(page["entries"]?.first)
        page["entries"] = [entry.merging(patch) { $1 }]
        return try JSONDecoder.daemon.decode(
            HistoryPage.self, from: JSONEncoder().encode(page)
        ).entries[0]
    }
}
