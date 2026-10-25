import PRWizardKit
import SwiftUI

struct LanesPane: View {
    @Environment(SettingsStore.self) private var settings

    var body: some View {
        ScopedPane(width: 600, keys: ["review.enabled", "fix.enabled"]) { scope in
            Section("Lanes") {
                SettingRow(key: "review.enabled", scope: scope) {
                    Toggle("Review lane", isOn: settings.isOn("review.enabled", in: scope))
                }
                SettingRow(key: "fix.enabled", scope: scope) {
                    Toggle("Fix lane", isOn: settings.isOn("fix.enabled", in: scope))
                }
            }
        }
    }
}
