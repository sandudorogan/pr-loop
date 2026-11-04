import PRLoopKit
import SwiftUI

/// A menu, not a `Picker`: a menu-style `Picker` ignores `.disabled` on its items.
struct ScopePicker: View {
    @Binding var scope: SettingsScope
    let options: [ScopeOption]
    @Environment(SettingsStore.self) private var settings

    var body: some View {
        LabeledContent("Scope") {
            Menu {
                ForEach(options) { option in
                    Toggle(
                        isOn: Binding {
                            scope == option.scope
                        } set: { _ in
                            scope = option.scope
                        }
                    ) {
                        item(option)
                    }
                    .disabled(!option.isEnabled)
                    .help(option.help ?? "")
                    if option.scope == .allRepos { Divider() }
                }
            } label: {
                options.first { $0.scope == scope }.map(item)
            }
            .fixedSize()
        }
    }

    @ViewBuilder private func item(_ option: ScopeOption) -> some View {
        let text = Text(verbatim: "\(option.title)  ·  \(option.detail)")
        if settings.errors.contains(option.scope) {
            Label {
                text
            } icon: {
                Image(systemName: "exclamationmark.triangle.fill")
            }
        } else if settings.hasEdits(in: option.scope) {
            Label {
                text
            } icon: {
                Image(systemName: "pencil")
            }
        } else {
            text
        }
    }
}
