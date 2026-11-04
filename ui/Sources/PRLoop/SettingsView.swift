import SwiftUI

struct SettingsView: View {
    @AppStorage(AppStorageKey.settingsPane) private var pane = SettingsPane.general

    var body: some View {
        TabView(selection: $pane) {
            Tab("General", systemImage: "gearshape", value: .general) { GeneralPane() }
            Tab("Lanes", systemImage: "arrow.triangle.branch", value: .lanes) { LanesPane() }
            Tab("Reviewers", systemImage: "person.3", value: .reviewers) { ReviewersPane() }
            Tab("Fixer", systemImage: "wrench.and.screwdriver", value: .fixer) { FixerPane() }
        }
    }
}
