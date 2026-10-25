import PRWizardKit
import SwiftUI

/// Edits one reviewer value. The caller owns where it lives, and passes the markers and 422 messages per field.
struct ReviewerForm: View {
    private struct Viewed: Identifiable {
        let id: String
    }

    @Binding var reviewer: ReviewerConfig
    let choices: Choices
    var marker: (String) -> OverrideMarker? = { _ in nil }
    var errors: (String) -> [String] = { _ in [] }
    @State private var viewed: Viewed?

    var body: some View {
        Form {
            row("id", caption: "Renaming re-reviews heads it already did.") {
                TextField("ID", text: $reviewer.id).monospaced()
            }
            row("label") { TextField("Label", text: $reviewer.label) }
            row("engine") {
                Picker("Engine", selection: $reviewer.engine) {
                    ForEach(choices.engines.map(Engine.init(rawValue:)), id: \.self) {
                        Text(verbatim: $0.rawValue.capitalized).tag($0)
                    }
                }
                .pickerStyle(.segmented)
                .fixedSize()
            }
            if reviewer.engine == .codex { codex } else { claude }
            row("prompt") {
                Picker("Prompt", selection: $reviewer.prompt) {
                    ForEach(choices.prompts, id: \.self) { Text(verbatim: $0).tag($0) }
                }
                .fixedSize()
                Button("View…") { viewed = Viewed(id: reviewer.prompt) }
            }
            row("fallback") {
                LabeledContent("Fallback") {
                    Toggle(
                        "Run on \(reviewer.engine == .codex ? "Claude" : "Codex") at the usage limit",
                        isOn: $reviewer.hasFallback)
                }
            }
            row("advisory") {
                LabeledContent("Advisory") {
                    Toggle("Findings alone still read as Ready", isOn: $reviewer.isAdvisory)
                }
            }
            row("needs_conventions") {
                LabeledContent("Conventions") {
                    Toggle("Needs project conventions", isOn: $reviewer.needsConventions)
                }
            }
        }
        .formStyle(.columns)
        .sheet(item: $viewed) { PromptSheet(name: $0.id) }
    }

    @ViewBuilder private var claude: some View {
        row("claude.model") {
            ModelField(
                title: "Model", model: $reviewer.claude.model, defaultLabel: "Default",
                suggestions: choices.claudeModels)
        }
        row("claude.effort") { effort("Effort", $reviewer.claude.effort) }
        row("claude.incremental") {
            LabeledContent("Later rounds") {
                Toggle("Lighter run on incremental diffs", isOn: $reviewer.claude.hasIncremental)
            }
        }
        if reviewer.claude.hasIncremental {
            row("claude.incremental.model") {
                ModelField(
                    title: "Later model",
                    model: Binding {
                        reviewer.claude.incremental?.model
                    } set: {
                        reviewer.claude.incremental?.model = $0
                    }, defaultLabel: "Default", suggestions: choices.claudeModels)
            }
            row("claude.incremental.effort") {
                effort(
                    "Later effort",
                    Binding {
                        reviewer.claude.incremental?.effort
                    } set: {
                        reviewer.claude.incremental?.effort = $0
                    })
            }
        }
    }

    @ViewBuilder private var codex: some View {
        let efforts = EffortChoices(choices, model: reviewer.codex.model, effort: reviewer.codex.effort)
        row("codex.model") {
            ModelField(
                title: "Model", model: $reviewer.codex.model, defaultLabel: choices.codexModelLabel,
                suggestions: choices.codexModels.map(\.model))
        }
        row("codex.effort") {
            Picker("Effort", selection: $reviewer.codex.effort) {
                Text(verbatim: efforts.defaultLabel).tag(String?.none)
                Divider()
                ForEach(efforts.efforts, id: \.self) { Text(verbatim: $0).tag(Optional($0)) }
            }
            .fixedSize()
        }
        if reviewer.hasFallback {
            row("claude.model") {
                ModelField(
                    title: "Fallback Claude model", model: $reviewer.claude.model, defaultLabel: "Default",
                    suggestions: choices.claudeModels)
            }
        }
    }

    private func effort(_ title: String, _ selection: Binding<String?>) -> some View {
        let efforts =
            choices.claudeEfforts
            + [selection.wrappedValue].compactMap { $0 }.filter {
                !choices.claudeEfforts.contains($0)
            }
        return Picker(title, selection: selection) {
            Text("Default").tag(String?.none)
            Divider()
            ForEach(efforts, id: \.self) { Text(verbatim: $0).tag(Optional($0)) }
        }
        .fixedSize()
    }

    private func row(_ field: String, caption: String? = nil, @ViewBuilder control: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                control()
                marker(field)
            }
            if let caption { Text(verbatim: caption).font(.caption).foregroundStyle(.secondary) }
            FieldError(messages: errors(field))
        }
    }
}
