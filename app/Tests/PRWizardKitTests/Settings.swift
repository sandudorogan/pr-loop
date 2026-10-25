import Foundation
import PRWizardKit

enum Settings {
    static let gitops = SettingsScope.project("iprally/gitops")

    static func envelope(merging patch: JSONValue = [:]) throws -> ConfigEnvelope {
        let tree = try JSONDecoder().decode(JSONValue.self, from: Fixture.data("config.json"))
        return try JSONDecoder.daemon.decode(
            ConfigEnvelope.self, from: JSONEncoder().encode(JSONValue.merged(tree, patch)))
    }

    static func rejected(_ status: Int, _ code: String, _ details: [APIErrorBody.Problem] = []) -> APIError {
        .http(status: status, code: code, message: code, details: details)
    }
}
