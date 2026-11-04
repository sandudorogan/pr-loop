import PRLoopKit
import SwiftUI

struct PRReviewerRow: View {
    let reviewer: ReviewerConfig
    let choices: Choices
    let update: (ReviewerConfig) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Toggle(
                reviewer.label,
                isOn: Binding {
                    reviewer.isEnabled
                } set: { on in
                    edit { $0.isEnabled = on }
                })
            if reviewer.engine == .codex {
                let efforts = EffortChoices(choices, model: reviewer.codex.model, effort: reviewer.codex.effort)
                pickers(
                    model: \.codex.model, models: choices.codexModels.map(\.model),
                    modelDefault: choices.codexModelLabel,
                    effort: \.codex.effort, efforts: efforts.efforts, effortDefault: efforts.defaultLabel)
            } else {
                pickers(
                    model: \.claude.model, models: choices.claudeModels, modelDefault: "Default",
                    effort: \.claude.effort, efforts: choices.claudeEfforts, effortDefault: "Default")
            }
        }
    }

    private func pickers(
        model: WritableKeyPath<ReviewerConfig, String?>, models: [String], modelDefault: String,
        effort: WritableKeyPath<ReviewerConfig, String?>, efforts: [String], effortDefault: String
    ) -> some View {
        HStack {
            OptionPicker(
                title: "Model", selection: reviewer[keyPath: model], options: models, defaultLabel: modelDefault
            ) {
                value in edit { $0[keyPath: model] = value }
            }
            OptionPicker(
                title: "Effort", selection: reviewer[keyPath: effort], options: efforts, defaultLabel: effortDefault
            ) { value in edit { $0[keyPath: effort] = value } }
        }
        .controlSize(.small)
        .disabled(!reviewer.isEnabled)
    }

    private func edit(_ change: (inout ReviewerConfig) -> Void) {
        var changed = reviewer
        change(&changed)
        update(changed)
    }
}
