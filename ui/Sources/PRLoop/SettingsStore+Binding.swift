import PRLoopKit
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

extension SettingsStore {
    func intBinding(_ key: String, in scope: SettingsScope, per unit: Int = 1) -> Binding<Int> {
        Binding {
            self.int(key, in: scope, per: unit)
        } set: {
            self.setInt(key, to: $0, in: scope, per: unit)
        }
    }

    func stringsBinding(_ key: String, in scope: SettingsScope) -> Binding<[String]> {
        Binding {
            self.strings(key, in: scope)
        } set: {
            self.setStrings(key, to: $0, in: scope)
        }
    }
}
