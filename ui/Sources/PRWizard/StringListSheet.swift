import PRWizardKit
import SwiftUI

/// Edits a list setting in the draft. In a project scope the list overrides whole, so a toggle keeps the default.
struct StringListSheet: View {
    let title: String
    let key: String
    let scope: SettingsScope
    let limit: Int
    @Environment(SettingsStore.self) private var settings
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let entries = settings.strings(key, in: scope)
        let usesDefault = scope != .allRepos && !settings.draft.isOverridden(key, in: scope)
        VStack(spacing: 0) {
            Form {
                if scope != .allRepos {
                    Toggle(
                        "Use the default list",
                        isOn: Binding {
                            usesDefault
                        } set: {
                            settings.setUsesDefault($0, for: key, in: scope)
                        })
                }
                Section(title) {
                    ForEach(entries.indices, id: \.self) { index in
                        HStack {
                            TextField(title, text: item(index)).labelsHidden()
                            Button("Remove", systemImage: "minus.circle") {
                                settings.setStrings(
                                    key, to: entries.enumerated().filter { $0.offset != index }.map(\.element),
                                    in: scope)
                            }
                            .labelStyle(.iconOnly).buttonStyle(.borderless).disabled(entries.count == 1)
                        }
                    }
                    Button("Add", systemImage: "plus") { settings.setStrings(key, to: entries + [""], in: scope) }
                        .disabled(entries.count >= limit)
                    FieldError(messages: settings.errors.messages(within: key, in: scope))
                }
                .disabled(usesDefault)
            }
            .formStyle(.grouped)
            HStack {
                Spacer()
                Button("Done") { dismiss() }.keyboardShortcut(.defaultAction)
            }
            .padding()
        }
        .frame(width: 440, height: 380)
    }

    private func item(_ index: Int) -> Binding<String> {
        Binding {
            let entries = settings.strings(key, in: scope)
            return entries.indices.contains(index) ? entries[index] : ""
        } set: {
            var entries = settings.strings(key, in: scope)
            if entries.indices.contains(index) { entries[index] = $0 }
            settings.setStrings(key, to: entries, in: scope)
        }
    }
}
