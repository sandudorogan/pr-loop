import Foundation
import PRLoopKit

enum PRConfigs {
    static let pr = PRRef(repo: "iprally/iprally", number: 17201)

    static func config(merging patch: JSONValue = [:]) throws -> PRConfig {
        let tree = try JSONValue(parsing: Fixture.data("pr-config.json"))
        return try JSONValue.merged(tree, patch).decoded(PRConfig.self, using: .daemon)
    }

    static func cleared() throws -> PRConfig {
        try config(merging: ["override": .null, "rev": "bf21a9e8fbc5", "layers": ["pr": []]])
    }
}
