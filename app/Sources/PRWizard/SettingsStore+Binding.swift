import PRWizardKit
import SwiftUI

extension SettingsStore {
    func isOn(_ key: String, in scope: SettingsScope) -> Binding<Bool> {
        Binding {
            self.resolve(key, in: scope).value == true
        } set: {
            self.set(key, to: .bool($0), in: scope)
        }
    }

    func number(_ key: String, in scope: SettingsScope) -> Binding<Int> {
        Binding {
            self.resolve(key, in: scope).value.int ?? 0
        } set: {
            self.set(key, to: .number(Double($0)), in: scope)
        }
    }

    func text(_ key: String, in scope: SettingsScope) -> Binding<String?> {
        Binding {
            self.resolve(key, in: scope).value.string
        } set: {
            self.set(key, to: $0.map(JSONValue.string) ?? .null, in: scope)
        }
    }

    func words(_ key: String, in scope: SettingsScope) -> Binding<[String]> {
        Binding {
            self.resolve(key, in: scope).value.strings
        } set: {
            self.set(key, to: .array($0.map(JSONValue.string)), in: scope)
        }
    }
}
