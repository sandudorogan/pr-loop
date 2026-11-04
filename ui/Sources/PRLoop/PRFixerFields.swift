import PRLoopKit
import SwiftUI

struct PRFixerFields: View {
    let effective: FixConfig
    let projectGates: [GateConfig]?
    let choices: Choices
    let markers: PRMarkers
    @Environment(PRSettingsStore.self) private var store

    var body: some View {
        let efforts = EffortChoices(choices, model: effective.model, effort: effective.effort)
        row("fix.model") {
            OptionPicker(
                title: "Model", selection: effective.model, options: choices.codexModels.map(\.model),
                defaultLabel: choices.codexModelLabel, choose: text("fix.model"))
        }
        row("fix.effort") {
            OptionPicker(
                title: "Effort", selection: effective.effort, options: efforts.efforts,
                defaultLabel: efforts.defaultLabel, choose: text("fix.effort"))
        }
        row("fix.prompt") { prompt("Fix turn", "fix.prompt", effective.prompt) }
        row("fix.merge_prompt") { prompt("Base merge", "fix.merge_prompt", effective.mergePrompt) }
        row("fix.gates") {
            VStack(alignment: .leading) {
                ForEach(gates, id: \.name) { gate in
                    Toggle(
                        gate.name,
                        isOn: Binding {
                            isOn(gate)
                        } set: {
                            setGate(gate, on: $0)
                        })
                }
                if gates.isEmpty { Text("No local gates").foregroundStyle(.secondary) }
            }
        }
        stepper("Test retries", "fix.test_retries", effective.testRetries, 0...5)
        stepper("Red CI job looks", "fix.ci_tries", effective.ciTries, 1...10)
        stepper("Park after failed passes", "fix.max_errors", effective.maxErrors, 1...10)
        row("fix.turn_timeout_s") {
            DurationField(title: "Codex turn", seconds: number("fix.turn_timeout_s", effective.turnTimeout))
        }
        row("fix.pass_timeout_s") {
            DurationField(
                title: "Whole pass", seconds: number("fix.pass_timeout_s", effective.passTimeout), bareUnit: .hours)
        }
    }

    private var gates: [GateConfig] { projectGates ?? effective.gates }

    private func isOn(_ gate: GateConfig) -> Bool {
        effective.gates.contains { $0.name == gate.name }
    }

    private func setGate(_ gate: GateConfig, on: Bool) {
        let kept = gates.filter { $0.name == gate.name ? on : isOn($0) }
        Task {
            if kept == gates {
                await store.useDefault(["fix.gates"])
            } else if let list = try? JSONValue(encoding: kept) {
                await store.set("fix.gates", to: list)
            }
        }
    }

    private func prompt(_ title: String, _ path: String, _ name: String) -> some View {
        Picker(
            title,
            selection: Binding {
                name
            } set: { value in
                Task { await store.set(path, to: .string(value)) }
            }
        ) {
            ForEach(choices.prompts, id: \.self) { Text(verbatim: $0).tag($0) }
        }
    }

    private func stepper(_ title: String, _ path: String, _ value: Int, _ range: ClosedRange<Int>) -> some View {
        row(path) {
            Stepper(value: number(path, value), in: range) { LabeledContent(title, value: "\(value)") }
        }
    }

    private func number(_ path: String, _ value: Int) -> Binding<Int> {
        Binding {
            value
        } set: { new in
            Task { await store.set(path, to: .number(Double(new))) }
        }
    }

    private func text(_ path: String) -> (String?) -> Void {
        { value in Task { await store.set(path, to: value.map(JSONValue.string) ?? .null) } }
    }

    private func row(_ path: String, @ViewBuilder control: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                control()
                OverrideMarker(kind: markers.source(of: path).kind) { Task { await store.useDefault([path]) } }
            }
            FieldError(messages: store.messages(at: path))
        }
    }
}
