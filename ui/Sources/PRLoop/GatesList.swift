import PRLoopKit
import SwiftUI

struct GatesList: View {
    private struct Row: Identifiable {
        let id: Int
        let gate: GateConfig
    }

    private struct Editing: Identifiable {
        let id = UUID()
        let index: Int?
        let gate: GateConfig?
    }

    let scope: SettingsScope
    let project: Project?
    @Environment(SettingsStore.self) private var settings
    @State private var selection: Int?
    @State private var editing: Editing?
    @State private var confirmsDefault = false

    private var gates: GateList { GateList(settings.resolve("fix.gates", in: scope).value) }
    private var isInherited: Bool { scope != .allRepos && !settings.draft.isOverridden("fix.gates", in: scope) }
    private var name: String { ProjectSummary.shortName(of: scope.rawValue) }

    var body: some View {
        let rows = gates.configs.enumerated().map { Row(id: $0.offset, gate: $0.element) }
        Section {
            if scope != .allRepos { usesDefault }
            if rows.isEmpty {
                Text("No local gates. Codex runs the checks the conventions name, and CI grades the rest.")
                    .foregroundStyle(.secondary)
            } else {
                table(rows)
            }
            bar(rows)
            ForEach(settings.errors.gates(in: scope), id: \.self) { FieldError(messages: [problem($0, rows)]) }
        } header: {
            HStack {
                Text("Gates")
                Spacer()
                if !isInherited, project?.gates.contains(where: { $0.source == "default" }) == true {
                    Text(verbatim: "Built-in override for \(name)").font(.caption).foregroundStyle(.secondary)
                }
            }
        } footer: {
            Text("Format gates run first, then test gates. A gate moves only within its kind.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .onChange(of: scope) { selection = nil }
        .sheet(item: $editing) { editing in
            GateEditorSheet(scope: scope, index: editing.index, gate: editing.gate) { selection = $0 }
        }
        .confirmationDialog(question, isPresented: $confirmsDefault) {
            Button("Remove Gates", role: .destructive) { settings.useDefault("fix.gates", in: scope) }
        } message: {
            Text(
                GateList(settings.resolve("fix.gates", in: .allRepos).value).gates.isEmpty
                    ? "The fixer then runs no local checks there." : "The fixer then runs the default gates there.")
        }
    }

    private var question: String {
        let names = gates.configs.map(\.name).formatted(.list(type: .and))
        return "Remove \(name)'s \(names) gates?"
    }

    private var usesDefault: some View {
        let defaults = GateList(settings.resolve("fix.gates", in: .allRepos).value).configs.map(\.name)
        return HStack {
            Toggle(
                "Use the default gates (\(defaults.isEmpty ? "none" : defaults.joined(separator: ", ")))",
                isOn: Binding {
                    isInherited
                } set: {
                    $0 ? useDefault() : settings.setUsesDefault(false, for: "fix.gates", in: scope)
                })
            OverrideMarker(kind: isInherited ? .inherited : .overridden, useDefault: useDefault)
        }
    }

    private func useDefault() {
        if gates.gates.isEmpty { settings.useDefault("fix.gates", in: scope) } else { confirmsDefault = true }
    }

    private func table(_ rows: [Row]) -> some View {
        Table(rows, selection: $selection) {
            TableColumn("Name") { row in
                HStack(spacing: 4) {
                    if settings.errors.gates(in: scope).contains(where: { $0.index == row.id }) {
                        Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Tone.attention.color)
                            .accessibilityLabel("Has errors")
                    }
                    Text(verbatim: row.gate.name)
                }
            }
            TableColumn("Kind") { Text(verbatim: $0.gate.kind.rawValue) }.width(50)
            TableColumn("When") { row in
                Text(verbatim: row.gate.when.joined(separator: " ")).help(row.gate.when.joined(separator: "\n"))
            }
            .width(min: 160)
            TableColumn("Timeout") { Text(verbatim: $0.gate.timeout.map(DurationFormat().format) ?? "–") }.width(60)
            TableColumn("Slot") { row in
                Text(verbatim: row.gate.usesSlot == true ? "●" : "–")
                    .accessibilityLabel(row.gate.usesSlot == true ? "Uses a machine slot" : "No machine slot")
            }
            .width(30)
        }
        .contextMenu(forSelectionType: Int.self) { _ in
        } primaryAction: { ids in
            if let id = ids.first { editing = Editing(index: id, gate: rows[id].gate) }
        }
        .frame(height: CGFloat(rows.count) * 24 + 28)
    }

    private func bar(_ rows: [Row]) -> some View {
        let index = selection.flatMap { rows.indices.contains($0) ? $0 : nil }
        return HStack(spacing: 2) {
            Button("Add Gate", systemImage: "plus") { editing = Editing(index: nil, gate: nil) }
                .disabled(!gates.canAdd)
            Button("Remove Gate", systemImage: "minus") { edit(index) { $0.remove(at: $1) } }
                .disabled(index == nil)
            Button("Duplicate Gate", systemImage: "plus.square.on.square") {
                edit(index, select: 1) { $0.duplicate(at: $1) }
            }
            .disabled(index == nil || !gates.canAdd)
            Button("Move Up", systemImage: "arrow.up") { edit(index, select: -1) { $0.move($1, by: -1) } }
                .disabled(index.map { !gates.canMove($0, by: -1) } ?? true)
            Button("Move Down", systemImage: "arrow.down") { edit(index, select: 1) { $0.move($1, by: 1) } }
                .disabled(index.map { !gates.canMove($0, by: 1) } ?? true)
            Spacer()
            Button("Edit…") { index.map { editing = Editing(index: $0, gate: rows[$0].gate) } }
                .disabled(index == nil)
        }
        .labelStyle(.iconOnly)
        .buttonStyle(.borderless)
        .disabled(isInherited)
    }

    private func problem(_ problem: FieldErrors.GateProblem, _ rows: [Row]) -> String {
        let gate = problem.index.flatMap { rows.indices.contains($0) ? rows[$0].gate.name : nil } ?? "Gates"
        return "\(gate)\(problem.field.isEmpty ? "" : " \(problem.field)"): \(problem.message)"
    }

    private func edit(_ index: Int?, select offset: Int? = nil, _ change: (inout GateList, Int) -> Void) {
        guard let index else { return }
        var list = gates
        change(&list, index)
        settings.set("fix.gates", to: list.value, in: scope)
        selection = offset.map { index + $0 }
    }
}
