import Foundation
import PRWizardKit

enum Fixture {
    static let directory = URL(filePath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .appending(path: "contract/api/v1")

    static func data(_ name: String) throws -> Data {
        try Data(contentsOf: directory.appending(path: name))
    }

    static func oracle() throws -> Data {
        try Data(
            contentsOf: directory.deletingLastPathComponent().deletingLastPathComponent().appending(
                path: "oracle/config.json"))
    }

    static func decode<Value: Decodable>(_ type: Value.Type, from name: String) throws -> Value {
        try JSONValue(parsing: data(name)).decoded(type, using: .daemon)
    }
}
