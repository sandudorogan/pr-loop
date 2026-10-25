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
}
