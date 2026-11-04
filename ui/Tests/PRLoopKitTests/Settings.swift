import Foundation
import PRLoopKit

enum Settings {
    static let gitops = SettingsScope.project("iprally/gitops")

    static func envelope(merging patch: JSONValue = [:]) throws -> ConfigEnvelope {
        let tree = try JSONValue(parsing: Fixture.data("config.json"))
        return try JSONValue.merged(tree, patch).decoded(ConfigEnvelope.self, using: .daemon)
    }

    static func rejected(_ status: Int, _ code: String, _ details: [APIErrorBody.Problem] = []) -> APIError {
        .http(status: status, code: code, message: code, details: details)
    }
}
