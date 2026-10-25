import PRWizardKit
import SwiftUI

struct SettingRow<Control: View>: View {
    let key: String
    let scope: SettingsScope
    @ViewBuilder let control: Control
    @Environment(SettingsStore.self) private var settings

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                control
                if scope != .allRepos { OverrideMarker(key, in: scope, store: settings) }
            }
            FieldError(messages: settings.errors.messages(within: key, in: scope))
        }
    }
}
