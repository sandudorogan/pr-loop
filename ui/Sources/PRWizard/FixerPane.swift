import PRWizardKit
import SwiftUI

struct FixerPane: View {
    private struct Viewed: Identifiable {
        let id: String
    }

    private static let keys = [
        "fix.engine", "fix.model", "fix.effort", "fix.prompt", "fix.merge_prompt", "fix.test_retries", "fix.ci_tries",
        "fix.ci_apps", "fix.max_errors", "fix.turn_timeout_s", "fix.pass_timeout_s", "fix.gates",
    ]

    @Environment(QueueStore.self) private var queue
    @Environment(SettingsStore.self) private var settings
    @State private var viewed: Viewed?

    var body: some View {
        ScopedPane(width: 600, keys: Self.keys) { scope in
            if let choices = settings.original?.choices {
                let project = queue.projects.first { $0.id == scope.rawValue }?.project
                if let line = PRWizardKit.ConventionsLine(scope, project: project) {
                    Section { ConventionsLine(line: line, checkout: project?.checkout?.path) }
                }
                engine(choices, scope)
                Section("Prompts") {
                    prompt("Fix turn", "fix.prompt", choices, scope)
                    prompt("Base merge", "fix.merge_prompt", choices, scope)
                }
                GatesList(scope: scope, project: project)
                limits(scope)
            }
        }
        .sheet(item: $viewed) { PromptSheet(name: $0.id) }
    }

    private func engine(_ choices: Choices, _ scope: SettingsScope) -> some View {
        let model = settings.text("fix.model", in: scope)
        let effort = settings.text("fix.effort", in: scope)
        let efforts = EffortChoices(choices, model: model.wrappedValue, effort: effort.wrappedValue)
        return Section("Engine") {
            LabeledContent("Engine") {
                Text("Codex \(Text("(needs resumable sessions)").foregroundStyle(.secondary))")
            }
            SettingRow(key: "fix.model", scope: scope) {
                ModelField(
                    title: "Model", model: model, defaultLabel: choices.codexModelLabel,
                    suggestions: choices.codexModels.map(\.model))
            }
            SettingRow(key: "fix.effort", scope: scope) {
                Picker("Effort", selection: effort) {
                    Text(verbatim: efforts.defaultLabel).tag(String?.none)
                    Divider()
                    ForEach(efforts.efforts, id: \.self) { Text(verbatim: $0).tag(Optional($0)) }
                }
            }
        }
    }

    private func prompt(_ title: String, _ key: String, _ choices: Choices, _ scope: SettingsScope) -> some View {
        let name = settings.text(key, in: scope)
        return SettingRow(key: key, scope: scope) {
            Picker(title, selection: name) {
                ForEach(choices.prompts, id: \.self) { Text(verbatim: $0).tag(Optional($0)) }
            }
            Button("View…") { viewed = name.wrappedValue.map(Viewed.init) }
        }
    }

    private func limits(_ scope: SettingsScope) -> some View {
        Section("Limits") {
            stepper("Test retries after a red gate", "fix.test_retries", 0...5, scope)
            stepper("Looks at one red CI job", "fix.ci_tries", 1...10, scope)
            SettingRow(key: "fix.ci_apps", scope: scope) {
                TextField(
                    "CI checks come from", value: settings.words("fix.ci_apps", in: scope), format: WordListFormat()
                )
                .help("GitHub App slugs whose check runs count as CI")
            }
            stepper("Park after failed passes in a row", "fix.max_errors", 1...10, scope)
            SettingRow(key: "fix.turn_timeout_s", scope: scope) {
                DurationField(
                    title: "Timeout per Codex turn", seconds: settings.number("fix.turn_timeout_s", in: scope))
            }
            SettingRow(key: "fix.pass_timeout_s", scope: scope) {
                DurationField(
                    title: "Timeout per pass", seconds: settings.number("fix.pass_timeout_s", in: scope),
                    bareUnit: .hours)
            }
        }
    }

    private func stepper(_ title: String, _ key: String, _ range: ClosedRange<Int>, _ scope: SettingsScope)
        -> some View
    {
        let value = settings.number(key, in: scope)
        return SettingRow(key: key, scope: scope) {
            Stepper(value: value, in: range) { LabeledContent(title, value: "\(value.wrappedValue)") }
        }
    }
}
